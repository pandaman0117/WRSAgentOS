"""Run shipped service/client examples with no manually configured credential."""

import asyncio
import os
import secrets
import socket
import subprocess

import pytest

from wrs_agent import System
from wrs_agent.errors import AgentError
from wrs_agent.processes import NO_WINDOW, ROOT, python_command

pytestmark = pytest.mark.zenoh


@pytest.mark.parametrize(
    "group,service_name,client_name,original_port,original_env,node",
    [
        ("connect", "01_start_system.py", "02_client.py", "7447", "connect-demo", "tts"),
        pytest.param(
            "wrs", "05_start_node.py", "06_control_arm.py", "7449", "wrs-demo", "wrs",
            marks=pytest.mark.wrs,
        ),
    ],
)
async def test_service_and_client_generate_and_share_token_without_environment(
    tmp_path, group, service_name, client_name, original_port, original_env, node
):
    from conftest import eventually

    from examples import _session

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    env_id = "auto-token-" + secrets.token_hex(6)
    copies = tmp_path / "examples"
    copies.mkdir()
    bindings = ROOT / ("configs/tts.toml" if group == "connect" else "examples/wrs/bindings.toml")
    for filename in (service_name, client_name):
        source = (ROOT / "examples" / group / filename).read_text(encoding="utf-8")
        source = source.replace(original_port, str(port)).replace(original_env, env_id)
        source = source.replace(
            'Path(__file__).resolve().parents[2] / "configs/tts.toml"',
            repr(str(ROOT / "configs/tts.toml")),
        )
        source = source.replace('Path(__file__).with_name("bindings.toml")', repr(str(bindings)))
        source = source.replace(
            'Path(__file__).with_name("scene.toml")', repr(str(ROOT / "examples/wrs/scene.toml"))
        )
        (copies / filename).write_text(source, encoding="utf-8")

    token_dir = tmp_path / "credentials"
    runner = tmp_path / "run_example.py"
    runner.write_text(
        "import runpy, sys\nfrom pathlib import Path\n"
        "from examples import _session\n"
        f"_session._TOKEN_DIR = Path({str(token_dir)!r})\n"
        f"if Path(sys.argv[1]).name == {service_name!r}:\n"
        "    import asyncio, contextlib\n"
        "    original_run = asyncio.run\n"
        "    async def serve(coroutine):\n"
        "        task = asyncio.create_task(coroutine)\n"
        "        try:\n"
        "            while not Path('stop').exists():\n"
        "                if task.done():\n"
        "                    await task\n"
        "                    return\n"
        "                await asyncio.sleep(0.03)\n"
        "        finally:\n"
        "            task.cancel()\n"
        "            with contextlib.suppress(asyncio.CancelledError):\n"
        "                await task\n"
        "    asyncio.run = lambda coroutine, **kwargs: original_run(serve(coroutine), **kwargs)\n"
        "    runpy.run_path(sys.argv[1], run_name='__main__')\n"
        "else:\n"
        "    runpy.run_path(sys.argv[1], run_name='__main__')\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env.pop("WRS_AGENT_TOKEN", None)
    endpoint = f"tcp/127.0.0.1:{port}"

    async def ready():
        assert service.poll() is None, (tmp_path / "service.log").read_text(encoding="utf-8")
        if not (token_dir / f"{group}.token").exists():
            return False
        with socket.socket() as probe:
            probe.settimeout(0.1)
            if probe.connect_ex(("127.0.0.1", port)) != 0:
                return False
        token = (token_dir / f"{group}.token").read_text()
        async with System.connect(
            endpoint, env_id=env_id, bindings=bindings, _token=token
        ) as connection:
            try:
                await connection.clients[node].transport.request("request/health", {}, timeout=0.2)
                if group == "wrs":
                    await connection.agent.request("request/task/status", {}, timeout=0.2)
                return True
            except TimeoutError:
                return False

    with (tmp_path / "service.log").open("w", encoding="utf-8") as log:
        service = await asyncio.to_thread(
            subprocess.Popen,
            python_command(runner, copies / service_name),
            env=env, cwd=tmp_path, stdout=log, stderr=log, creationflags=NO_WINDOW,
        )
        token = None
        try:
            await eventually(ready, bool, timeout=15)
            token = (token_dir / f"{group}.token").read_text()
            assert _session._valid(token)
            # This subprocess receives no token; it must read the shared private configuration.
            result = await asyncio.to_thread(
                subprocess.run,
                python_command(runner, copies / client_name),
                env=env, cwd=tmp_path, capture_output=True,
                text=True, encoding="utf-8", timeout=15, creationflags=NO_WINDOW,
            )
            assert result.returncode == 0, result.stderr
            assert "SUCCEEDED" in result.stdout
            assert token not in result.stdout + result.stderr
            assert service.poll() is None
            async with System.connect(
                endpoint, env_id=env_id, bindings=bindings,
                _token="different-unauthorized-token",
            ) as untrusted:
                with pytest.raises(AgentError, match="unauthorized"):
                    await untrusted.snapshot(node)
            async with System.connect(
                endpoint, env_id=env_id, bindings=bindings, _token=token
            ) as observer:
                snapshot = await observer.snapshot(node)
                if group == "connect":
                    assert snapshot.data.completed == 1
                else:
                    assert snapshot.data.robot.kinematics.valid
        finally:
            # Cancelling the coroutine lets System.launch clean up all owned child processes.
            if service.poll() is None:
                (tmp_path / "stop").touch()
                try:
                    await asyncio.to_thread(service.wait, timeout=10)
                except subprocess.TimeoutExpired:
                    service.terminate()
                    await asyncio.to_thread(service.wait, timeout=5)
    output = (tmp_path / "service.log").read_text(encoding="utf-8")
    assert token is not None and token not in output
