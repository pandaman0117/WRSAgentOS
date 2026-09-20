import asyncio
import subprocess

import pytest

from wrs_agent.processes import NO_WINDOW, ROOT, python_command

pytestmark = pytest.mark.zenoh


async def test_custom_node_and_skill_run_from_another_working_directory(tmp_path):
    result = await asyncio.to_thread(
        subprocess.run,
        python_command(ROOT / "examples/developer/05_custom_skill.py"),
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        creationflags=NO_WINDOW,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS: custom node" in result.stdout
