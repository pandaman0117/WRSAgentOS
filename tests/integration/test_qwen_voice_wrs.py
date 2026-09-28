"""Real WRS/Zenoh/Voice with a deterministic audio boundary; never opens sound devices."""

import runpy

import pytest
from conftest import eventually

from wrs_agent.processes import ROOT, LocalStack, python_command
from wrs_agent.schemas import ActionState

pytestmark = [pytest.mark.zenoh, pytest.mark.wrs]


async def test_voice_example_cancels_real_wrs_and_speech_worker(tmp_path):
    entry = runpy.run_path(str(ROOT / "examples/voice/06_push_to_talk.py"))
    config = ROOT / "examples/voice/wrs_bindings.toml"
    async with LocalStack(backend="wrs", bindings=config, duration=2.0) as stack:
        # Replace only this test-owned TTS process, preserving the production adapter and RPCs.
        bus = stack.system._transports["tts"]
        await bus.request("request/node/tts/shutdown", {}, control=True)
        process = stack.processes[2]  # router, WRS, TTS, Agent, Voice
        await eventually(process.poll, lambda code: code is not None)
        script = tmp_path / "speaker.py"
        script.write_text(
            "import asyncio\n"
            "from wrs_agent.nodes.tts.backend import SpeechBackend, make_speech_executor\n"
            "from wrs_agent.nodes import Node\n"
            "from wrs_agent.nodes.serve import serve_node\n"
            "def render(text, stopped):\n"
            "    stopped.wait(3.0)\n"
            "    return ([0.0], 24000)\n"
            "def play(*args):\n"
            "    raise AssertionError('cancelled audio must never play')\n"
            "class Speaker(Node):\n"
            "    node_type = 'tts'\n"
            "    async def setup(self):\n"
            "        self.actions(make_speech_executor(self.journal, "
            "SpeechBackend(render, play)))\n"
            f"asyncio.run(serve_node(Speaker, endpoint={stack.endpoint!r}, "
            f"env_id={stack.env_id!r}, bindings={str(config)!r}, "
            f"journal={str(tmp_path / 'speaker.db')!r}))\n",
            encoding="utf-8",
        )
        replacement = stack._spawn("qwen-boundary", python_command(script))
        # _wait_ready checks every owned process; the intentionally closed old TTS is removed.
        stack.processes.remove(process)
        await stack._wait_ready("tts")
        system = stack.system
        captured = await system.snapshot(node="wrs")
        await entry["dispatch"](system, "向上", captured)
        overview = await system.status()
        task = system.task(overview["task_id"])

        async def both_running():
            snapshots = [await system.snapshot(node=n) for n in ("wrs", "tts")]
            return all(s.active_action for s in snapshots)

        await eventually(both_running, bool)
        receipt = await system.send_text("停止")
        assert receipt.accepted and receipt.task_id == task.id
        assert (await task.wait()).state == ActionState.CANCELLED
        assert (await system.snapshot(node="wrs")).stop_confirmed
        speaker = await system.snapshot(node="tts")
        assert speaker.stop_confirmed and speaker.data.completed == 0
        assert replacement.poll() is None


async def test_continuous_voice_stop_invalidates_pending_plan_without_waiting_for_model(llm_server):
    entry = runpy.run_path(str(ROOT / "examples/voice/08_listen_goals.py"))
    config = ROOT / "examples/voice/wrs_bindings.toml"
    llm_server.gate.clear()
    async with LocalStack(backend="wrs", bindings=config, live_model=True) as stack:
        system = stack.system
        captured = await system.snapshot(node="wrs")
        request_id = await entry["submit_text"](system, "机器人，回原位", captured)
        assert request_id is not None
        await eventually(llm_server.entered.is_set, bool)
        await eventually(system.status,
                         lambda s: s["planning"] == "WAITING" and s["planner_calls"] == 1)
        # An unresolved model response/observer must not block the explicit stop path.
        await entry["submit_text"](system, "停止", captured, observing=True)
        assert (await system.planning(request_id).wait()).state == "STALE"
        llm_server.gate.set()
        state = await system.status()
        assert state["task_id"] is None and state["action_history"] == []
        robot = await system.snapshot(node="wrs")
        assert robot.stop_confirmed and robot.admission == "HELD"
        assert robot.control_epoch != captured.control_epoch
        # Reusing the pre-stop capture cannot start a new goal after the stop.
        assert await entry["submit_text"](system, "机器人，移动到 B", captured) is None
        state = await system.status()
        assert state["planning_request_id"] is None and state["planner_calls"] == 1
        assert (await system.planning(request_id).wait()).state == "STALE"
