"""Cancellation must finish without a successor and invalidate in-flight work."""

import asyncio

import pytest
from conftest import control, eventually
from test_runtime import OfflineNode, motion

from wrs_agent.bindings import load_bindings
from wrs_agent.nodes.tts.backend import make_mock_tts
from wrs_agent.runtime import Runtime
from wrs_agent.schemas import ActionStatus, Plan, Step, TaskCancelRequest, TaskRequest


async def test_cancel_fences_idle_tts_before_delayed_submit(tmp_path):
    speech = make_mock_tts(tmp_path / "speech.db", duration=0.1)
    node = OfflineNode(speech)
    entered, release = asyncio.Event(), asyncio.Event()
    original = node._submit

    async def delayed(request):
        entered.set()
        await release.wait()
        return await original(request)

    node._submit = delayed
    runtime = Runtime({"tts": node}, load_bindings()[1])
    plan = Plan(steps=[Step(step_id="say", skill="speak", args={"text": "late"})])
    try:
        task = await runtime.start(TaskRequest(request_id="start", plan=plan))
        await asyncio.wait_for(entered.wait(), 1)
        assert speech.active is None
        receipt = await runtime.cancel(
            TaskCancelRequest(request_id="stop", task_id=task["task_id"])
        )
        assert receipt["phase"] == "STOPPING"
        await eventually(speech.snapshot, lambda s: s.control_epoch > 0)
        assert runtime.execution.state == "CANCELLING"
        release.set()
        await eventually(runtime.snapshot, lambda s: s["state"] == "CANCELLED")
        assert speech.executions == 0 and speech.admission == "OPEN"
        await runtime.start(TaskRequest(request_id="next", plan=plan))
        await eventually(runtime.snapshot, lambda s: s["state"] == "SUCCEEDED")
        assert speech.executions == 1
    finally:
        release.set()
        await runtime.close()
        await speech.close()


async def test_cancel_only_one_queued_task(make_env):
    env = make_env(duration=0.1)
    runtime = Runtime({"wrs": OfflineNode(env)}, load_bindings()[1])
    try:
        first = await runtime.start(TaskRequest(request_id="first", plan=motion("B")))
        skipped = await runtime.enqueue(TaskRequest(request_id="skip", plan=motion("home")))
        last = await runtime.enqueue(TaskRequest(request_id="last", plan=motion("C")))
        receipt = await runtime.cancel(
            TaskCancelRequest(request_id="stop-queued", task_id=skipped["task_id"])
        )
        assert receipt["phase"] == "STOPPED" and env.epoch == 0
        await eventually(
            runtime.snapshot,
            lambda s: s["task_id"] == last["task_id"] and s["state"] == "SUCCEEDED",
        )
        assert runtime.task_status(first["task_id"])["state"] == "SUCCEEDED"
        assert runtime.task_status(skipped["task_id"])["state"] == "CANCELLED"
        assert env.executions == 2 and env.world.pose == "C"
    finally:
        await runtime.close()
        await env.close()


@pytest.mark.parametrize("when", ["before", "after"])
async def test_task_cancel_never_clears_an_independent_device_hold(make_env, when):
    env = make_env(duration=0.3)
    node = OfflineNode(env)
    runtime = Runtime({"wrs": node}, load_bindings()[1])
    original = runtime._wait_stopped

    async def held_again(name, task):
        await env.hold(control(env))
        return await original(name, task)

    try:
        task = await runtime.start(TaskRequest(request_id="start", plan=motion()))
        await eventually(env.snapshot, lambda s: s.active_action is not None)
        if when == "before":
            await env.hold(control(env))
        else:
            runtime._wait_stopped = held_again
        await runtime.cancel(TaskCancelRequest(request_id="stop", task_id=task["task_id"]))
        await eventually(runtime.snapshot, lambda s: s["state"] == "CANCELLED")
        assert env.admission == "HELD" and env.stop_confirmed
        await runtime.start(TaskRequest(request_id="next", plan=motion("C")))
        await eventually(runtime.snapshot, lambda s: s["state"] == "FAILED")
        assert env.world.pose != "C" and env.admission == "HELD"
    finally:
        await runtime.close()
        await env.close()


async def test_restart_during_cancel_does_not_control_new_instance(make_env):
    old, new = make_env(duration=0.3), make_env()
    node = OfflineNode(old)
    runtime = Runtime({"wrs": node}, load_bindings()[1])
    original = runtime._wait_stopped

    async def restarted(name, task):
        node.executor = new
        return await original(name, task)

    runtime._wait_stopped = restarted
    try:
        task = await runtime.start(TaskRequest(request_id="start", plan=motion()))
        await eventually(old.snapshot, lambda s: s.active_action is not None)
        await runtime.cancel(TaskCancelRequest(request_id="stop", task_id=task["task_id"]))
        await eventually(runtime.snapshot, lambda s: s["state"] == "UNKNOWN")
        assert runtime.execution.error.code == "node_instance_changed"
        assert new.epoch == 0 and new.executions == 0
    finally:
        await runtime.close()
        await old.close()
        await new.close()


@pytest.mark.parametrize("result", ["delayed", "unknown", "missing", "unverified"])
async def test_cancel_reconciles_action_outcome(make_env, result):
    env = make_env(duration=0.3)
    node = OfflineNode(env)
    runtime = Runtime({"wrs": node}, load_bindings()[1])
    original = node.status
    lagged = 0

    async def observed(action_id):
        nonlocal lagged
        if env.active is None and env.epoch > 0:
            if result == "missing":
                return None
            if result == "unknown":
                return ActionStatus(action_id=action_id, state="UNKNOWN")
            if result == "unverified":
                return ActionStatus(action_id=action_id, state="SUCCEEDED", verification="PENDING")
            if lagged < 2:
                lagged += 1
                return ActionStatus(action_id=action_id, state="CANCELLING")
        return await original(action_id)

    node.status = observed
    try:
        task = await runtime.start(TaskRequest(request_id="start", plan=motion()))
        await eventually(runtime.snapshot, lambda s: bool(s["active_actions"]))
        await runtime.cancel(TaskCancelRequest(request_id="stop", task_id=task["task_id"]))
        expected = "CANCELLED" if result == "delayed" else "UNKNOWN"
        await eventually(runtime.snapshot, lambda s: s["state"] == expected)
        assert env.admission == ("OPEN" if result == "delayed" else "HELD")
        if result == "delayed":
            assert lagged == 2
    finally:
        await runtime.close()
        await env.close()
