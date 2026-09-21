import asyncio
import json

import pytest

from wrs_agent.processes import NO_WINDOW, ROOT, python_command

pytestmark = pytest.mark.wrs


async def test_real_wrs_scene_and_viewer_object_lifecycle():
    process = await asyncio.create_subprocess_exec(
        *python_command(ROOT / "tests/fixtures/wrs_scene_probe.py"),
        cwd=ROOT, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        creationflags=NO_WINDOW,
    )
    try:
        output, error = await asyncio.wait_for(process.communicate(), 30)
        assert process.returncode == 0, (output + error).decode("utf-8")
        assert json.loads(output.decode("utf-8").splitlines()[-1]) == {
            "wrs_scene": "PASS", "viewer_sync": "PASS", "hardware": False,
        }
    finally:
        if process.returncode is None:
            process.terminate()
            await process.wait()
