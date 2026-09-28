"""Run the teaching scripts against actual independent Zenoh nodes."""

import asyncio
import contextlib
import runpy
import secrets
import shutil
import socket
import subprocess

import pytest
from conftest import eventually

from wrs_agent import System
from wrs_agent.processes import NO_WINDOW, ROOT, python_command
from wrs_agent.transport import Transport

pytestmark = pytest.mark.zenoh


async def run_client(path, cwd):
    result = await asyncio.to_thread(
        subprocess.run,
        python_command(ROOT / path),
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=20,
        creationflags=NO_WINDOW,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


def port_open(port):
    with socket.socket() as probe:
        probe.settimeout(0.1)
        return probe.connect_ex(("127.0.0.1", port)) == 0


async def wait_ready(bus, service):
    async with asyncio.timeout(10):
        while True:
            try:
                return await bus.request(service, {}, timeout=0.3)
            except TimeoutError:
                await asyncio.sleep(0.05)


async def stop_service(task):
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


async def test_persistent_mock_service_and_separate_client(monkeypatch, tmp_path):
    monkeypatch.setenv("WRS_AGENT_TOKEN", secrets.token_urlsafe(32))
    assert not port_open(7447), "Example port already in use; leave that service untouched"
    entry = runpy.run_path(str(ROOT / "tests/fixtures/connect/01_start_system.py"))
    server = asyncio.create_task(entry["main"]())
    try:
        await eventually(lambda: port_open(7447), bool, timeout=10)
        async with System.connect(
            "tcp/127.0.0.1:7447", env_id="connect-demo", bindings="configs/tts.toml"
        ) as observer:
            await observer.registry.wait_for("tts")
            boot = (await observer.snapshot("tts")).boot_id
            output = await run_client("tests/fixtures/connect/02_client.py", tmp_path)
            assert "SUCCEEDED" in output
            snapshot = await observer.snapshot("tts")
            assert snapshot.boot_id == boot and snapshot.data.completed == 1
            assert not server.done()  # Disconnecting the client does not stop the service.
    finally:
        await stop_service(server)
    assert not port_open(7447)


async def test_custom_node_and_skill_run_from_another_working_directory(monkeypatch, tmp_path):
    token = secrets.token_urlsafe(32)
    monkeypatch.setenv("WRS_AGENT_TOKEN", token)
    # Keep the user's demo on 7448 untouched; run copies on a separate loopback port.
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    env_id = "node-demo-" + secrets.token_hex(6)
    directory = tmp_path / "examples/nodes"
    shutil.copytree(
        ROOT / "examples/nodes", directory, ignore=shutil.ignore_patterns("__pycache__")
    )
    for path in [*directory.glob("*.py"), directory / "router.json5"]:
        text = path.read_text(encoding="utf-8")
        text = text.replace("tcp/127.0.0.1:7448", f"tcp/127.0.0.1:{port}")
        path.write_text(text.replace("node-demo", env_id), encoding="utf-8")
    entry = runpy.run_path(str(directory / "00_start_router.py"))
    router = asyncio.create_task(entry["main"]())
    children, logs, buses = [], [], []
    try:
        await eventually(lambda: port_open(port), bool, timeout=10)
        for filename in ("01_start_speaker.py", "02_start_agent.py"):
            log = (tmp_path / (filename + ".log")).open("w", encoding="utf-8")
            logs.append(log)
            children.append(
                await asyncio.create_subprocess_exec(
                    *python_command(directory / filename),
                    cwd=tmp_path,
                    stdout=log,
                    stderr=log,
                    creationflags=NO_WINDOW,
                )
            )
        speaker = Transport(f"tcp/127.0.0.1:{port}", "local", env_id + "-speaker", token, "test")
        buses.append(speaker)
        agent = Transport(f"tcp/127.0.0.1:{port}", "local", env_id, token, "test")
        buses.append(agent)
        features = await wait_ready(speaker, "request/features")
        assert "greet" in str(features)
        await wait_ready(agent, "request/task/status")
        for filename, state in (
            ("03_call_skill.py", "SUCCEEDED"),
            ("04_task.py", "SUCCEEDED"),
            ("05_cancel.py", "CANCELLED"),
            ("03_call_skill.py", "SUCCEEDED"),
        ):
            output = await run_client(directory / filename, tmp_path)
            assert state in output
            assert all(child.returncode is None for child in children)
        await agent.request("request/node/agent/shutdown", {}, control=True)
        await speaker.request("request/node/speaker/shutdown", {}, control=True)
        for child in children:
            assert await asyncio.wait_for(child.wait(), timeout=5) == 0
    finally:
        for bus in buses:
            await bus.close()
        for child in children:
            if child.returncode is None:
                child.terminate()
            await asyncio.wait_for(child.wait(), timeout=5)
        for log in logs:
            log.close()
        await stop_service(router)
    assert not port_open(port)
