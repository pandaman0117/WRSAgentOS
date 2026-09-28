import pytest
from conftest import eventually

from wrs_agent import AgentError
from wrs_agent.processes import LocalStack

pytestmark = pytest.mark.zenoh

BINDINGS = "tests/fixtures/asr.toml"


async def hold(system, script_line):
    """One button press. The script line is whatever the mock capture returns for it."""
    started = await system.listen_begin()
    assert started.capturing
    await system.listen_end(started.press_id)
    result = await eventually(
        lambda: system.listen_result(started.press_id), lambda r: not r.capturing
    )
    assert result.text == script_line
    return result


async def test_transcript_returns_to_the_caller_and_only_the_stop_is_routed(llm_server):
    async with LocalStack(
        bindings=BINDINGS, live_model=True, duration=2, asr_script=["put A in B", "停止"]
    ) as stack:
        system = stack.system
        assert stack.system.roles["asr"] in (await system.nodes())
        assert (await system.nodes())[stack.system.roles["asr"]]["features"] == [
            "input.transcribe"
        ]

        goal = await hold(system, "put A in B")
        # The ASR node does not submit goals: admission stays with the caller.
        assert goal.receipt is None and not goal.reason
        assert (await system.status())["task_id"] is None

        receipt = await system.send_text(goal.text, input_id=goal.press_id)
        assert receipt.accepted and receipt.disposition == "goal"
        planned = await system.planning(receipt.request_id).wait()
        task = planned.task
        await eventually(system.status, lambda s: s["active_actions"])

        stop = await hold(system, "停止")
        # A stop never waits for the caller to relay it.
        assert stop.receipt.accepted and stop.receipt.task_id == task.id
        assert (await task.wait()).state == "CANCELLED"
        assert (await system.snapshot()).stop_confirmed


async def test_the_node_keeps_one_microphone_and_replays_finished_presses():
    async with LocalStack(bindings=BINDINGS, duration=0.02, asr_script=["put A in B"]) as stack:
        system = stack.system
        started = await system.listen_begin()
        assert await system.listen_begin(started.press_id) == started
        with pytest.raises(AgentError, match="asr_busy"):
            await system.listen_begin()
        await system.listen_end(started.press_id)
        result = await eventually(
            lambda: system.listen_result(started.press_id), lambda r: not r.capturing
        )
        assert await system.listen_result(started.press_id) == result
        with pytest.raises(AgentError, match="asr_press_finished"):
            await system.listen_begin(started.press_id)
        with pytest.raises(AgentError, match="asr_press_not_found"):
            await system.listen_result("never-pressed")
