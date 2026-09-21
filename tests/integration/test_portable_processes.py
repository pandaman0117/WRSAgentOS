"""Exercise actual processes using another Python installation path and router path."""

import os
import shutil
import subprocess
import sys
import venv
from pathlib import Path
from uuid import uuid4

import pytest

from wrs_agent.processes import (
    NO_WINDOW,
    ROOT,
    InstanceLock,
    LocalStack,
    python_command,
    router_path,
)

pytestmark = pytest.mark.zenoh


def test_instance_lock_excludes_other_process_and_releases_on_close(tmp_path):
    name = "portability-" + uuid4().hex
    probe = tmp_path / "lock probe.py"
    probe.write_text(
        "from wrs_agent.processes import InstanceLock\n"
        f"lock = InstanceLock({name!r})\n"
        "lock.close()\nprint('acquired')\n",
        encoding="utf-8",
    )
    lock = InstanceLock(name)
    try:
        blocked = subprocess.run(
            python_command(probe),
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=NO_WINDOW,
        )
        assert blocked.returncode != 0
        assert "node_already_running" in blocked.stderr
    finally:
        lock.close()
    released = subprocess.run(
        python_command(probe),
        capture_output=True,
        text=True,
        timeout=10,
        creationflags=NO_WINDOW,
    )
    assert released.returncode == 0, released.stderr
    assert released.stdout.strip() == "acquired"


def test_launch_from_another_venv_keeps_its_site_packages(tmp_path):
    environment = tmp_path / "other Python 环境"
    venv.EnvBuilder(with_pip=False).create(environment)
    executable = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    # Reuse installed test dependencies without downloading or modifying the parent environment.
    packages = (
        environment / "Lib/site-packages"
        if os.name == "nt"
        else environment
        / f"lib/python{sys.version_info.major}.{sys.version_info.minor}/site-packages"
    )
    imports = [ROOT, *(Path(item).resolve() for item in sys.path if item and Path(item).is_dir())]
    (packages / "test_dependencies.pth").write_text(
        "\n".join(dict.fromkeys(map(str, imports))) + "\n", encoding="utf-8"
    )
    probe = tmp_path / "launch probe.py"
    bindings = ROOT / "configs/tts.toml"
    probe.write_text(
        "import sys\n"
        "from wrs_agent import launch\n"
        "from wrs_agent.processes import python_command\n"
        "assert not sys.flags.no_site\n"
        "assert python_command('-m', 'wrs_agent')[0] == sys.executable\n"
        f"with launch(bindings={str(bindings)!r}, duration=0.05) as system:\n"
        "    result = system.action('speak', text='portable').wait()\n"
        "    assert result.state == 'SUCCEEDED'\n"
        "    processes = system._system._local_stack.processes\n"
        "assert all(process.poll() is not None for process in processes)\n"
        "print('portable_launch SUCCEEDED')\n",
        encoding="utf-8",
    )
    environment_vars = os.environ.copy()
    environment_vars.pop("PYTHONPATH", None)
    environment_vars.pop("WRS_AGENT_TOKEN", None)
    result = subprocess.run(
        [str(executable), "-X", "utf8", str(probe)],
        cwd=tmp_path,
        env=environment_vars,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=40,
        creationflags=NO_WINDOW,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "portable_launch SUCCEEDED"


async def test_launch_uses_explicit_router_path_with_spaces(monkeypatch, tmp_path):
    source = router_path()
    executable = tmp_path / ("custom router" + source.suffix)
    shutil.copy2(source, executable)
    monkeypatch.setenv("WRS_AGENT_ZENOHD", str(executable))
    async with LocalStack(bindings="configs/tts.toml") as stack:
        assert Path(stack.processes[0].args[0]) == executable.resolve()
        action = await stack.system.action("speak", text="configured router")
        assert (await action.wait()).state == "SUCCEEDED"
    assert all(process.poll() is not None for process in stack.processes)
