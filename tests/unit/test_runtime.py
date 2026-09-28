import asyncio

import httpx
import pytest
from conftest import control, eventually
from llm_fixtures import REPLY, chat_reply

from wrs_agent.bindings import load_bindings
from wrs_agent.nodes.action_rpc import ActionClient
from wrs_agent.planner import ModelPlanner
from wrs_agent.runtime import Runtime
from wrs_agent.schemas import GoalRequest, Plan, Step, TaskCancelRequest, TaskRequest, new_id


class OfflineNode(ActionClient):
    """Unit-only boundary fixture; never used as network integration evidence."""

    def __init__(self, executor):
        self.executor = executor
        self.node_id = executor.node_id

    async def validate(self, steps, *, boot_id):
        from wrs_agent.schemas import SkillCheck
        return self.executor.validate(SkillCheck(boot_id=boot_id, steps=list(steps)))

    async def features(self):
        return self.executor.features()

    async def snapshot(self, *, control=False):
        return self.executor.snapshot()

    async def context(self, *, control=False):
        return self.executor.context()

    async def control(self, kind, request):
        return await self.executor.control(kind, request)

    async def _submit(self, request):
        return await self.executor.submit(request)

    async def status(self, action_id):
        return self.executor.status(action_id)


async def test_late_model_after_stop_is_rejected(make_env, make_llm):
    env = make_env()
    entered, gate = asyncio.Event(), asyncio.Event()

    async def respond(request):
        entered.set()
        await gate.wait()
        return httpx.Response(200, content=REPLY.read_bytes())

    provider = make_llm(respond)
    _, bindings = load_bindings()
    runtime = Runtime({"wrs": OfflineNode(env)}, bindings, ModelPlanner(provider))
    try:
        await runtime.goal(GoalRequest(request_id="goal", goal="pick A"))
        await asyncio.wait_for(entered.wait(), 1)
        assert runtime.task_id is None
        before = env.epoch
        await env.hold(control(env))
        gate.set()
        await runtime.planning.worker
        assert env.epoch > before
        assert runtime.task_id is None
        assert runtime.planning.state == "STALE"
        assert env.executions == 0 and env.admission == "HELD"
    finally:
        await runtime.close()
        await env.close()
        await provider.aclose()


async def test_invalid_model_plan_finishes_failed_without_actions(make_env, make_llm):
    env = make_env()
    provider = make_llm(
        '{"kind":"execute","plan":{"steps":[{"step_id":"bad","skill":"unregistered"}]}}'
    )
    runtime = Runtime({"wrs": OfflineNode(env)}, load_bindings()[1], ModelPlanner(provider))
    try:
        await runtime.goal(GoalRequest(request_id="bad-plan", goal="put A in B"))
        await runtime.planning.worker
        assert runtime.execution.state == "FAILED" and runtime.planning.state == "FAILED"
        assert env.executions == 0 and not runtime.cache.entries
    finally:
        await runtime.close()
        await env.close()


async def test_late_model_error_does_not_overwrite_hold(make_env, make_llm):
    entered, gate = asyncio.Event(), asyncio.Event()

    async def obsolete(request):
        entered.set()
        await gate.wait()
        return httpx.Response(503)

    env = make_env()
    provider = make_llm(obsolete)
    runtime = Runtime({"wrs": OfflineNode(env)}, load_bindings()[1], ModelPlanner(provider))
    try:
        await runtime.goal(GoalRequest(request_id="late-error", goal="put A in B"))
        await entered.wait()
        await env.hold(control(env))
        gate.set()
        await runtime.planning.worker
        assert env.admission == "HELD" and runtime.planning.state == "STALE"
        assert runtime.task_id is None and runtime.execution.state == "IDLE"
        assert runtime.execution.reason == "" and env.executions == 0
    finally:
        await runtime.close()
        await env.close()


def motion(pose="B"):
    return Plan(steps=[Step(step_id="move", skill="move_named_pose", args={"pose": pose})])


@pytest.mark.parametrize("late_error", [False, True], ids=["reply", "error"])
async def test_old_planner_cannot_change_new_execution(make_env, make_llm, late_error):
    entered, gate = asyncio.Event(), asyncio.Event()

    async def respond(request):
        entered.set()
        await gate.wait()
        if late_error:
            return httpx.Response(503)
        return httpx.Response(200, json=chat_reply(
            '{"kind":"execute","plan":{"steps":['
            '{"step_id":"old","skill":"pick","args":{"object":"A"}}]}}'
        ))

    env = make_env(duration=0.1)
    provider = make_llm(respond)
    runtime = Runtime({"wrs": OfflineNode(env)}, load_bindings()[1], ModelPlanner(provider))
    try:
        ack = await runtime.goal(GoalRequest(request_id="old-goal", goal="pick A"))
        await entered.wait()
        assert ack["request_id"] == "old-goal" and runtime.task_id is None
        newer = await runtime.start(TaskRequest(request_id="new-execution", plan=motion()))
        gate.set()
        await runtime.planning.worker
        await eventually(runtime.snapshot, lambda s: s["state"] == "SUCCEEDED")
        assert runtime.task_id == newer["task_id"]
        assert runtime.planning.state == "IDLE" and runtime.execution.reason == ""
        assert env.executions == 1 and env.world.pose == "B"
        assert all(r[0]["task_revision"] == 0 for r in env.records.values())
    finally:
        await runtime.close()
        await env.close()
        await provider.aclose()


async def test_task_and_queued_plan_are_detached_and_keep_their_ids(make_env):
    env = make_env(duration=0.05)
    runtime = Runtime({"wrs": OfflineNode(env)}, load_bindings()[1])
    try:
        first, second = motion("B"), motion("C")
        a = await runtime.start(TaskRequest(request_id="first", plan=first))
        b = await runtime.enqueue(TaskRequest(request_id="second", plan=second))
        first.steps[0].args["pose"] = "not-a-pose"
        first.steps.clear()
        second.steps[0].args["pose"] = "not-a-pose"
        second.steps[0].depends_on.append("missing")
        await eventually(
            runtime.snapshot, lambda s: s["task_id"] == b["task_id"] and s["state"] == "SUCCEEDED"
        )
        assert a["task_id"] != b["task_id"]
        assert env.executions == 2 and env.world.pose == "C"
        assert {r[0]["task_id"] for r in env.records.values()} == {a["task_id"], b["task_id"]}
        with pytest.raises(ValueError, match="stale_task"):
            await runtime.cancel(TaskCancelRequest(request_id="late", task_id=a["task_id"]))
    finally:
        await runtime.close()
        await env.close()


async def test_cancel_then_start_keeps_ids_and_rejects_late_controls(make_env):
    env = make_env(duration=0.1)
    runtime = Runtime({"wrs": OfflineNode(env)}, load_bindings()[1])
    try:
        a = await runtime.start(TaskRequest(request_id="first", plan=motion()))
        await eventually(
            env.snapshot,
            lambda w: (
                w.active_action is not None and env.status(w.active_action).state == "RUNNING"
            ),
        )
        old_action = env.active
        stop = TaskCancelRequest(request_id="cancel-a", task_id=a["task_id"])
        receipt = await runtime.cancel(stop)
        assert receipt["accepted"] and receipt["phase"] == "STOPPING"
        with pytest.raises(ValueError, match="task_busy"):
            await runtime.start(TaskRequest(request_id="too-early", plan=motion("C")))
        await eventually(runtime.snapshot, lambda s: s["state"] == "CANCELLED")
        request = TaskRequest(request_id="second", plan=motion("C"))
        b = await runtime.start(request)
        assert b["task_id"] != a["task_id"] and "supersedes" not in b
        assert await runtime.start(request) == b
        with pytest.raises(ValueError, match="stale_task"):
            await runtime.cancel(TaskCancelRequest(request_id=new_id(), task_id=a["task_id"]))
        assert await runtime.cancel(stop) == receipt
        await eventually(runtime.snapshot, lambda s: s["state"] == "SUCCEEDED")
        assert env.status(old_action).state == "CANCELLED"
        assert runtime.task_status(a["task_id"])["state"] == "CANCELLED"
        assert env.executions == 2 and env.world.pose == "C"
    finally:
        await runtime.close()
        await env.close()


@pytest.mark.parametrize("replacement_skill", ["move_named_pose", "speak"])
async def test_unconfirmed_stop_cannot_start_new_task(make_env, tmp_path, replacement_skill):
    from wrs_agent.nodes.tts.backend import make_mock_tts

    env = make_env(duration=0.1, fault="stop_unknown")
    tts = make_mock_tts(tmp_path / "tts.sqlite3", duration=0.1)
    runtime = Runtime({"wrs": OfflineNode(env), "tts": OfflineNode(tts)}, load_bindings()[1])
    try:
        a = await runtime.start(TaskRequest(request_id="first", plan=motion()))
        await asyncio.wait_for(env.world.started.wait(), 1)
        await runtime.cancel(TaskCancelRequest(request_id="hold", task_id=a["task_id"]))
        replacement = (
            motion("C")
            if replacement_skill == "move_named_pose"
            else Plan(steps=[Step(step_id="say", skill="speak", args={"text": "must not start"})])
        )
        await eventually(runtime.snapshot, lambda s: s["state"] == "UNKNOWN")
        with pytest.raises(ValueError, match="task_busy"):
            await runtime.start(TaskRequest(request_id="next", plan=replacement))
        assert env.executions == 1 and env.world.pose != "C"
        assert tts.executions == 0
    finally:
        await runtime.close()
        await env.close()
        await tts.close()


@pytest.mark.parametrize("late_failure", ["timeout", "failed_status"])
async def test_late_action_failure_does_not_fence_or_overwrite_new_task(make_env, late_failure):
    from wrs_agent.schemas import ActionStatus

    env = make_env(duration=0.2)
    node = OfflineNode(env)
    entered, release = asyncio.Event(), asyncio.Event()
    original_status = node.status

    async def delayed(action_id):
        if not entered.is_set():
            entered.set()
            await release.wait()
            if late_failure == "timeout":
                raise TimeoutError("old status timeout")
            return ActionStatus(action_id=action_id, state="FAILED", reason="old failure")
        return await original_status(action_id)

    node.status = delayed
    runtime = Runtime({"wrs": node}, load_bindings()[1])
    try:
        a = await runtime.start(TaskRequest(request_id="a", plan=motion()))
        await entered.wait()
        await runtime.cancel(TaskCancelRequest(request_id="hold", task_id=a["task_id"]))
        await eventually(runtime.snapshot, lambda s: s["state"] == "CANCELLED")
        b = await runtime.start(TaskRequest(request_id="b", plan=motion("C")))
        await eventually(runtime.snapshot, lambda s: s["state"] == "RUNNING")
        epoch = env.epoch
        release.set()
        await eventually(runtime.snapshot, lambda s: s["state"] == "SUCCEEDED")
        assert runtime.task_id == b["task_id"] and runtime.execution.reason == ""
        assert env.epoch == epoch and env.world.pose == "C"
    finally:
        release.set()
        await runtime.close()
        await env.close()
