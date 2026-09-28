import asyncio

import httpx
import pytest
from conftest import eventually
from llm_fixtures import REPLY
from test_runtime import OfflineNode, motion

from wrs_agent.bindings import load_bindings
from wrs_agent.planner import ModelPlanner
from wrs_agent.policy import text_intent
from wrs_agent.runtime import Runtime
from wrs_agent.schemas import (
    GoalRequest,
    InterruptRequest,
    TaskRequest,
    TextInput,
)


@pytest.mark.parametrize(
    "text,kind",
    [
        ("停止", "stop"),
        ("停！", "stop"),
        ("不要动", "stop"),
        ("STOP", "stop"),
        ("停，改放到 C", "stop"),
        ("停止播报", "cancel_tts"),
        ("别说了", "cancel_tts"),
        ("做到哪一步了？", "query"),
        ("嗯", "ignore"),
        ("谢谢", "ignore"),
        ("不要停止", "clarify"),
        ("他说“停止”", "clarify"),
        ("为什么要停止", "clarify"),
        ("先做完再拿 D", "clarify"),
        ("改放到 C", "clarify"),
        ("put A in B", "goal"),
    ],
)
def test_text_policy_is_explicit_and_conservative(text, kind):
    assert text_intent(TextInput(text=text))[0] == kind


def test_partial_and_low_confidence_never_execute():
    assert text_intent(TextInput(text="停", is_final=False))[0] == "ignore"
    assert text_intent(TextInput(text="停", confidence=0.4))[0] == "clarify"


async def test_interrupt_binds_task_once_and_does_not_retarget_new_task(make_env):
    env = make_env(duration=0.15)
    runtime = Runtime({"wrs": OfflineNode(env)}, load_bindings()[1])
    try:
        first = await runtime.start(TaskRequest(request_id="first", plan=motion()))
        await eventually(env.snapshot, lambda s: s.active_action is not None)
        stop = InterruptRequest(request_id="operator-stop")
        one, two = await asyncio.gather(runtime.interrupt(stop), runtime.interrupt(stop))
        assert one == two and one["accepted"] and one["task_id"] == first["task_id"]
        await eventually(runtime.snapshot, lambda s: s["state"] == "CANCELLED")
        after = env.epoch
        replacement = await runtime.start(TaskRequest(request_id="next", plan=motion("C")))
        await eventually(runtime.snapshot, lambda s: s["state"] == "RUNNING")
        assert await runtime.interrupt(stop) == one
        await eventually(runtime.snapshot, lambda s: s["state"] == "SUCCEEDED")
        assert runtime.task_id == replacement["task_id"]
        assert env.epoch == after  # Duplicate stop did not change control.
    finally:
        await runtime.close()
        await env.close()


async def test_interrupt_planning_without_task_rejects_late_result(make_env, make_llm):
    env = make_env()
    entered, gate = asyncio.Event(), asyncio.Event()

    async def respond(request):
        entered.set()
        await gate.wait()
        return httpx.Response(200, content=REPLY.read_bytes())

    model = make_llm(respond)
    runtime = Runtime({"wrs": OfflineNode(env)}, load_bindings()[1], ModelPlanner(model))
    try:
        await runtime.goal(GoalRequest(request_id="planning", goal="put A in B"))
        await entered.wait()
        receipt = await runtime.interrupt(InterruptRequest(request_id="stop"))
        assert receipt["task_id"] is None and receipt["accepted"]
        assert runtime.goal_status("planning")["state"] == "STALE"
        gate.set()
        # The model call is dropped, so no late reply can arrive to be checked at all.
        await asyncio.gather(runtime.planning.worker, return_exceptions=True)
        assert runtime.planning.worker.cancelled()
        assert env.executions == 0 and runtime.task_id is None
    finally:
        await runtime.close()
        await env.close()
