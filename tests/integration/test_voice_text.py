import asyncio

import pytest
from conftest import eventually

from wrs_agent import AgentError, System, launch, step
from wrs_agent.processes import LocalStack
from wrs_agent.schemas import TextInput
from wrs_agent.transport import RemoteError, Transport

pytestmark = pytest.mark.zenoh


async def test_text_controls_scope_idempotence_and_replacement():
    async with System.launch(duration=1.5) as system:
        task = await system.start(step("move_named_pose", pose="B"), step("speak", text="working"))
        await eventually(system.status, lambda s: len(s["active_actions"]) == 2)
        epoch = (await system.snapshot()).control_epoch
        assert (
            await system.send_text("停止", input_id="utterance", is_final=False)
        ).disposition == "ignore"
        assert (await system.send_text("不要停止")).disposition == "clarify"
        assert (await system.send_text("嗯")).disposition == "ignore"
        assert (await system.send_text("做到哪一步了")).overview["task_id"] == task.id
        assert (await system.snapshot()).control_epoch == epoch
        tts_stop = await system.send_text("停止播报")
        assert tts_stop.accepted
        assert (await system.snapshot()).control_epoch == epoch
        receipt = await system.send_text("停止", input_id="utterance")
        assert receipt.accepted and receipt.task_id == task.id
        assert (await task.status()).state == "HELD"
        replacement = await task.replace(step("move_named_pose", pose="C"))
        assert await system.send_text("停止", input_id="utterance") == receipt
        assert (await replacement.wait()).state == "SUCCEEDED"
        assert (await task.wait()).state == "CANCELLED"
        with pytest.raises(AgentError, match="event_id_conflict"):
            await system.send_text("home", input_id="utterance")


async def test_final_text_goal_receipt_can_be_reconnected_and_deduplicated():
    async with LocalStack(duration=0.02) as stack:
        system = stack.system
        receipt = await system.send_text("put A in B", input_id="recognized-goal")
        assert receipt.accepted and receipt.disposition == "goal"
        assert await system.send_text("put A in B", input_id="recognized-goal") == receipt
        async with System.connect(
            stack.endpoint, site=stack.site, env_id=stack.env_id, _token=stack.token
        ) as second:
            planned = await second.planning(receipt.request_id).wait()
            assert (await planned.task.wait()).state == "SUCCEEDED"
        assert (await system.status())["planner_calls"] == 1
        unknown = await system.send_text("some unrecognized speech")
        assert (await system.planning(unknown.request_id).wait()).state == "CLARIFY"
        assert (await system.clients["wrs"].transport.request("request/health", {}))[
            "executions"
        ] == 4


async def test_text_stop_invalidates_hung_planning_and_cannot_stop_later_task():
    async with LocalStack(deferred=True, duration=0.1) as stack:
        system = stack.system
        receipt = await system.send_text("put A in B")
        await eventually(system.status, lambda s: s["planning"] == "WAITING")
        stop = await system.send_text("停止", input_id="stop-planning")
        assert stop.accepted
        assert (await system.planning(receipt.request_id).wait()).state == "STALE"
        await system.agent.request("request/test/planner/release", {}, control=True)
        assert (await system.resume()).accepted
        task = await system.start(step("move_named_pose", pose="B"))
        assert await system.send_text("停止", input_id="stop-planning") == stop
        assert (await task.wait()).state == "SUCCEEDED"
        assert (await system.clients["wrs"].transport.request("request/health", {}))[
            "executions"
        ] == 1


async def test_text_endpoint_checks_control_intent_and_authentication():
    async with LocalStack(duration=0.02) as stack:
        system = stack.system
        bus = system._transports[system.roles["voice"]]
        with pytest.raises(RemoteError, match="control_intent_required"):
            await bus.request(
                "request/voice/control_text",
                TextInput(text="put A in B").model_dump(),
                control=True,
            )
        with pytest.raises(RemoteError, match="use_voice_control_endpoint"):
            await bus.request("request/voice/text", TextInput(text="停止").model_dump())
        rogue = Transport(
            stack.endpoint, stack.site, bus.env_id, "not-the-session-token", "voice-test"
        )
        try:
            with pytest.raises(RemoteError, match="unauthorized"):
                await rogue.request(
                    "request/voice/control_text", TextInput(text="停止").model_dump(), control=True
                )
        finally:
            await rogue.close()
        assert (await system.snapshot()).control_epoch == 0


async def test_text_stop_fences_robot_even_when_agent_is_offline():
    async with LocalStack(duration=2) as stack:
        system = stack.system
        action = await system.action("move_named_pose", pose="B")
        agent = stack.processes[3]
        agent.terminate()
        await asyncio.to_thread(agent.wait, timeout=3)
        receipt = await system.send_text("停止")
        assert receipt.phase == "UNKNOWN" and not receipt.accepted
        assert (await action.wait()).state == "CANCELLED"
        assert (await system.snapshot()).stop_confirmed


def test_sync_text_input_uses_same_receipt_and_planning_handles():
    with launch(duration=0.02) as system:
        receipt = system.send_text("put A in B")
        plan = system.planning(receipt.request_id).wait()
        assert plan.task.wait().state == "SUCCEEDED"


async def test_text_stop_of_speech_only_task_ignores_offline_robot():
    async with LocalStack(duration=2) as stack:
        system = stack.system
        task = await system.start(step("speak", text="still speaking"))
        await eventually(system.status, lambda s: len(s["active_actions"]) == 1)
        robot = stack.processes[1]
        robot.terminate()
        await asyncio.to_thread(robot.wait, timeout=3)
        receipt = await system.send_text("停止")
        assert receipt.accepted and receipt.task_id == task.id
        assert receipt.phase in {"STOPPING", "STOPPED"}
        assert (await task.status()).state == "HELD"
        await eventually(lambda: system.snapshot("tts"), lambda s: s.stop_confirmed)
