"""Launch ownership and independent clients over real cross-process Zenoh."""

import asyncio
import secrets
import subprocess

import pytest
from conftest import eventually

from wrs_agent import System, launch
from wrs_agent.processes import NO_WINDOW, ROOT, LocalStack, python_command

pytestmark = pytest.mark.zenoh


def test_tts_only_launch_and_another_program_connects(monkeypatch):
    monkeypatch.setenv("WRS_AGENT_TOKEN", secrets.token_urlsafe(32))
    with launch(bindings="configs/tts.toml", duration=0.1) as system:
        processes = system._system._local_stack.processes
        assert len(processes) == 2  # Router and TTS; no Agent, robot, or Voice required.
        assert set(system.nodes()) == {"tts"}
        assert [skill.name for skill in system.skills()] == ["speak"]
        boot = system.snapshot("tts").boot_id
        with pytest.raises(ValueError, match="node_role_not_configured"):
            system.status()
        with pytest.raises(ValueError, match="robot_allow_actions_unsupported"):
            system.allow_actions("tts")
        result = subprocess.run(
            python_command(
                "examples/tasks/04_connect.py",
                "--endpoint",
                system.endpoint,
                "--env-id",
                system.env_id,
            ),
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=15,
            creationflags=NO_WINDOW,
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "SUCCEEDED"
        assert all(p.poll() is None for p in processes)
        assert system.snapshot("tts").boot_id == boot
        assert system.snapshot("tts").data.completed == 1
        assert system.action("speak", text="still here").wait().state == "SUCCEEDED"
    assert all(p.poll() is not None for p in processes)


@pytest.mark.parametrize("raise_in_client", [False, True])
async def test_disconnect_keeps_accepted_action_running_and_can_reconcile(
    monkeypatch, raise_in_client
):
    monkeypatch.setenv("WRS_AGENT_TOKEN", secrets.token_urlsafe(32))
    async with LocalStack(bindings="configs/tts.toml", duration=0.5) as stack:
        owner = stack.system.clients["tts"]
        before = await owner.snapshot()
        try:
            async with System.connect(
                stack.endpoint, env_id=stack.env_id, bindings="configs/tts.toml"
            ) as client:
                assert client._local_stack is None
                action = await client.action("speak", text="survives disconnect")
                assert (await action.status()).state in {"ACCEPTED", "RUNNING"}
                if raise_in_client:
                    raise LookupError("user script failed")
        except LookupError:
            assert raise_in_client
        # No terminal subscription was kept; query the original ID, never resubmit.
        async with System.connect(
            stack.endpoint, env_id=stack.env_id, bindings="configs/tts.toml"
        ) as reconnected:
            node = reconnected.clients["tts"]
            done = await eventually(
                lambda: node.status(action.id), lambda s: s.state == "SUCCEEDED"
            )
            assert done.action_id == action.id
            after = await reconnected.snapshot("tts")
            assert after.boot_id == before.boot_id and after.control_epoch == before.control_epoch
            assert after.data.completed == 1
            assert (await node.transport.request("request/health", {}))["executions"] == 1
        assert all(p.poll() is None for p in stack.processes)


async def test_configured_node_can_join_after_connect_without_rebuilding_client(monkeypatch):
    monkeypatch.setenv("WRS_AGENT_TOKEN", secrets.token_urlsafe(32))
    async with LocalStack(bindings="configs/robot.toml", duration=0.1) as stack:
        async with System.connect(
            stack.endpoint, env_id=stack.env_id, bindings="tests/fixtures/actions.toml"
        ) as client:
            initial = await client.nodes()
            assert initial["wrs"]["ready"] and initial["tts"]["health"] == "offline"
            with pytest.raises(ValueError, match="node_unavailable"):
                await client.action("speak", text="offline")
            tts = client.clients["tts"]
            worker = stack._spawn(
                "late-tts",
                python_command(
                    "-m",
                    "wrs_agent",
                    "tts",
                    "--endpoint",
                    stack.endpoint,
                    "--env-id",
                    stack.env_id,
                    "--bindings",
                    "configs/tts.toml",
                    "--journal",
                    stack.directory / "late-tts.sqlite3",
                    "--duration",
                    "0.1",
                ),
            )
            try:
                await stack._wait_ready(tts.transport, "request/capabilities")
                await eventually(client.nodes, lambda items: items["tts"]["ready"])
                assert client.clients["tts"] is tts
                assert [s.name for s in await client.skills("播报")] == ["speak"]
                action = await client.action("speak", text="joined later")
                assert (await action.wait()).state == "SUCCEEDED"
                assert (await client.snapshot()).data.pose == "home"
            finally:
                await tts.transport.request("request/tts/shutdown", {}, control=True)
                await asyncio.to_thread(worker.wait, timeout=3)
