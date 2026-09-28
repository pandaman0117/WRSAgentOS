"""Public client methods discover late peers and keep controls on bound services."""

import asyncio

import pytest
from conftest import control, eventually
from test_dynamic_nodes import CounterNode, GateNode
from test_dynamic_nodes import network as network
from test_dynamic_nodes import start_node as start_node

from wrs_agent import AgentError, System, step
from wrs_agent.env.mock import make_mock_environment
from wrs_agent.nodes.agent import AgentNode
from wrs_agent.nodes.asr import AsrNode
from wrs_agent.nodes.tts import TtsNode
from wrs_agent.nodes.voice import VoiceNode
from wrs_agent.nodes.wrs import WrsNode
from wrs_agent.registry import register_node
from wrs_agent.transport import Transport

pytestmark = pytest.mark.zenoh


async def test_client_before_agent_recovers_the_same_peer_after_address_change(network, start_node):
    async with System.connect(**network) as system:
        assert not system.roles
        worker, _ = start_node(CounterNode, "counter")
        original, serving = start_node(AgentNode, "coordinator")
        await eventually(lambda: worker._info and original._info, bool)
        assert (await system.status())["state"] == "IDLE"
        previous = await system.start(step("count"))
        assert (await previous.wait()).state == "SUCCEEDED"
        await system.agent.request("request/node/coordinator/shutdown", {}, control=True)
        await asyncio.wait_for(serving, 3)
        await eventually(
            system.registry.snapshot,
            lambda rows: rows["coordinator"]["health"] == "offline",
        )
        replacement, _ = start_node(AgentNode, "coordinator", suffix="-new-address")
        await eventually(lambda: replacement._info, bool)
        assert (await system.status())["state"] == "IDLE"
        assert system.roles["agent"] == "coordinator"
        with pytest.raises(AgentError, match="task_not_found"):
            await previous.status()
        current = await system.start(step("count"))
        assert current.id != previous.id
        assert (await current.wait()).state == "SUCCEEDED"
        assert worker.executor.executions == 2


async def test_late_voice_asr_robot_work_without_a_manual_directory_refresh(
    network, start_node, monkeypatch,
):
    async with System.connect(**network) as system:
        assert not system.roles
        robots = [
            start_node(WrsNode, "robot", options={"duration": 0.01})[0],
            start_node(TtsNode, "speaker", options={"duration": 0.01})[0],
            start_node(AgentNode, "coordinator")[0],
            start_node(VoiceNode, "voice-input")[0],
            start_node(AsrNode, "capture", options={"script": ["hello"]})[0],
        ]
        await eventually(lambda: all(node._info for node in robots), bool)
        assert (await system.send_text("嗯")).disposition == "ignore"
        assert (await system.snapshot()).node_id == "robot"
        await system.listen_begin("press")
        await system.listen_end("press")
        transcript = await eventually(
            lambda: system.listen_result("press"), lambda result: not result.capturing,
        )
        assert transcript.text == "hello"

        async def discovery_must_not_block_stop(*args, **kwargs):
            pytest.fail("A bound stop must not await node discovery")

        with monkeypatch.context() as changes:
            changes.setattr(system.registry, "refresh", discovery_must_not_block_stop)
            stopped = await system.send_text("停止")
            assert stopped.accepted
        assert (await system.snapshot()).admission == "HELD"
        assert (await system.allow_actions()).accepted
        assert (await system.snapshot()).admission == "OPEN"


async def test_allow_actions_rejects_an_ambiguous_action_address(network, start_node, tmp_path):
    owner, _ = start_node(WrsNode, "robot", options={"duration": 0.01})
    async with System.connect(**network) as system:
        await system.registry.wait_for("robot")
        assert (await system.snapshot()).node_id == "robot"
        await owner.executor.control("hold", control(owner.executor))
        remote = Transport(
            network["endpoint"], network["site"], owner.target,
            "dynamic-node-test-session-token", "remote-robot",
        )
        other = make_mock_environment(tmp_path / "other-robot.sqlite3")
        try:
            register_node(remote, "other", "wrs", other, env_id=network["env_id"])
            await eventually(
                system.nodes,
                lambda rows: (rows["robot"].get("error") or {}).get("code")
                == "node_endpoint_ambiguous",
            )
            with pytest.raises(AgentError, match="node_endpoint_ambiguous"):
                await system.allow_actions()
            assert owner.executor.admission == "HELD"
        finally:
            await remote.close()
            await other.close()


@pytest.mark.parametrize("directory_state", ["timeout", "evicted"])
async def test_task_cancel_ignores_a_failed_ordinary_agent_description_query(
    network, start_node, monkeypatch, directory_state,
):
    coordinator, _ = start_node(AgentNode, "coordinator")
    gate, _ = start_node(GateNode, "gate")
    async with System.connect(**network) as system:
        await eventually(lambda: coordinator._info and gate._info, bool)
        task = await system.start(step("gate"))
        await asyncio.wait_for(gate.entered.wait(), 3)
        agent_bus = system.agent
        request = agent_bus.request

        async def fail_description(suffix, payload, **kwargs):
            if suffix == "request/node/coordinator":
                raise TimeoutError("ordinary descriptor timed out")
            return await request(suffix, payload, **kwargs)

        async def no_discovery_during_cancel(*args, **kwargs):
            pytest.fail("Bound task cancellation must not query the node directory")

        with monkeypatch.context() as changes:
            changes.setattr(agent_bus, "request", fail_description)
            rows = await system.registry.refresh(["coordinator"])
            assert rows["coordinator"]["error"]["code"] == "request_timeout"
            if directory_state == "evicted":
                # Registry's recycling path removes these records, not the retained connection.
                for records in (
                    system.registry.entries, system.registry._known, system.registry.buses,
                ):
                    records.pop("coordinator", None)
            changes.setattr(system.registry, "refresh", no_discovery_during_cancel)
            receipt = await task.cancel()
            assert receipt.accepted
            await eventually(
                gate.executor.snapshot,
                lambda state: state.stop_confirmed and state.active_action is None,
            )
        assert (await task.wait()).state == "CANCELLED"


async def test_voice_and_asr_wait_for_a_slow_dependency_beyond_ten_seconds(network, start_node):
    start_node(WrsNode, "robot", options={"duration": 0.01})
    start_node(AgentNode, "coordinator")
    voice, voice_serving = start_node(VoiceNode, "voice-input")
    capture, capture_serving = start_node(AsrNode, "capture", options={"script": ["hello"]})
    await eventually(lambda: voice.registry is not None and capture.registry is not None, bool)
    # Simulate slow model initialization using only offline nodes and a real router.
    await asyncio.sleep(10.2)
    assert not voice_serving.done(), "Voice exited while its TTS dependency was initializing"
    assert not capture_serving.done(), "ASR exited while its Voice dependency was initializing"
    assert voice._info is None and capture._info is None
    start_node(TtsNode, "speaker", options={"duration": 0.01})
    def ready():
        for worker in (voice_serving, capture_serving):
            if worker.done():
                worker.result()  # Surface startup errors instead of a poll timeout.
        return voice._info is not None and capture._info is not None

    try:
        await eventually(ready, bool)
    except TimeoutError as exc:
        raise AssertionError({
            "voice": voice.registry.snapshot(), "asr": capture.registry.snapshot(),
        }) from exc
    async with System.connect(**network) as system:
        assert (await system.send_text("嗯")).disposition == "ignore"
        assert (await system.listen_begin("after-initialization")).capturing
        await system.listen_end("after-initialization")
        result = await eventually(
            lambda: system.listen_result("after-initialization"),
            lambda result: not result.capturing,
        )
        assert result.text == "hello"
