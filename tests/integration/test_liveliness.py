"""Native presence and instance ownership across real Zenoh node processes."""

import asyncio

import pytest
from conftest import eventually, submit_request

from wrs_agent import System, step
from wrs_agent.schemas import ActionRequest, new_id
from wrs_agent.transport import Transport

pytestmark = pytest.mark.zenoh


async def test_native_leave_restart_invalidates_capabilities_and_old_authority(monkeypatch):
    async with System.launch(duration=0.05) as system:
        nodes = await system.nodes()
        stack, view = system._local_stack, system.registry
        client = system.clients["tts"]
        original = client.capabilities
        calls = 0

        async def counted():
            nonlocal calls
            calls += 1
            return await original()

        monkeypatch.setattr(client, "capabilities", counted)
        await view.capabilities("tts", client)
        await view.refresh(["tts"])
        await view.capabilities("tts", client)
        assert calls == 1
        old = await client.context()
        stale = ActionRequest(
            action_id=new_id(),
            task_id=new_id(),
            task_revision=0,
            boot_id=old.boot_id,
            control_epoch=old.control_epoch,
            lease_id=old.lease_id,
            state_version=old.state_version,
            skill="speak",
            args={"text": "old request"},
        )
        worker = stack.processes[2]
        await client.transport.request("request/tts/shutdown", {}, control=True)
        await asyncio.to_thread(worker.wait, timeout=3)
        await eventually(view.snapshot, lambda items: items["tts"]["health"] == "offline")
        assert "tts" not in view._caps
        stack.processes.remove(worker)
        stack._spawn("tts-restarted", stack.node_command("tts"))
        await stack._wait_ready(client.transport, "request/capabilities")
        fresh = await eventually(system.nodes, lambda items: items["tts"]["ready"])
        assert fresh["tts"]["boot_id"] != nodes["tts"]["boot_id"]
        await view.capabilities("tts", client)
        assert calls == 2
        receipt = await submit_request(client, stale)
        assert not receipt.accepted and receipt.reason == "stale_boot"
        spoken = await system.action("speak", text="new instance")
        assert (await spoken.wait()).state == "SUCCEEDED"
        assert (await client.transport.request("request/health", {}))["executions"] == 1


async def test_native_duplicate_instance_fails_closed_and_unknown_node_is_not_bound():
    async with System.launch(duration=0.05) as system:
        stack = system._local_stack
        before = await system.nodes()
        bus = system.clients["wrs"].transport
        duplicate = Transport(stack.endpoint, stack.site, bus.env_id, stack.token, "presence-test")
        tokens = []
        try:
            tokens.append(
                duplicate.session.liveliness().declare_token(bus.key("presence/ghost/boot"))
            )
            tokens.append(
                duplicate.session.liveliness().declare_token(bus.key("presence/wrs/other-instance"))
            )
            ambiguous = await eventually(
                system.registry.snapshot, lambda nodes: nodes["wrs"]["health"] == "unknown"
            )
            assert "ghost" not in ambiguous and not ambiguous["wrs"]["ready"]
            with pytest.raises(ValueError, match="node_ambiguous"):
                await system.action("move_named_pose", pose="B")
            assert (await bus.request("request/health", {}))["executions"] == 0
            tokens.pop().undeclare()
            recovered = await eventually(system.nodes, lambda nodes: nodes["wrs"]["ready"])
            assert recovered["wrs"]["boot_id"] == before["wrs"]["boot_id"]
        finally:
            for token in tokens:
                token.undeclare()
            await duplicate.close()


async def test_held_presence_is_not_permission_and_offline_tts_is_not_queried(monkeypatch):
    async with System.launch(duration=0.08) as system:
        before = await system.nodes()
        await system.replay("stop")
        held = await system.nodes()
        assert held["wrs"]["boot_id"] == before["wrs"]["boot_id"]
        assert held["wrs"]["health"] == "held" and not held["wrs"]["ready"]
        with pytest.raises(ValueError, match="node_not_ready"):
            await system.action("move_named_pose", pose="B")
        assert (await system.allow_actions()).accepted
        worker = system._local_stack.processes[2]
        worker.terminate()
        await asyncio.to_thread(worker.wait, timeout=3)
        await eventually(
            system.registry.snapshot, lambda nodes: nodes["tts"]["health"] == "offline"
        )

        async def unrelated(*args, **kwargs):
            raise AssertionError("robot action must not query unrelated TTS")

        with monkeypatch.context() as patch:
            patch.setattr(system.clients["tts"].transport, "request", unrelated)
            moved = await system.action("move_named_pose", pose="B")
            assert (await moved.wait()).state == "SUCCEEDED"
            task = await system.start(step("move_named_pose", pose="C"))
            assert (await task.wait()).state == "SUCCEEDED"
            assert (await system.snapshot()).data.robot.pose == "C"
