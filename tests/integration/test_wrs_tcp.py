"""Exercise named TCP motion with an actual nonzero WRS tool transform."""

import asyncio
import json

import pytest

from wrs_agent.processes import NO_WINDOW, ROOT, python_command

pytestmark = pytest.mark.wrs


async def test_actual_wrs_tcp_offset_motion_and_verification():
    process = await asyncio.create_subprocess_exec(
        *python_command(ROOT / "tests/fixtures/wrs_tcp_probe.py"),
        cwd=ROOT,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        creationflags=NO_WINDOW,
    )
    try:
        output, error = await asyncio.wait_for(process.communicate(), 30)
        assert process.returncode == 0, (output + error).decode("utf-8")
        result = json.loads(output.decode("utf-8").splitlines()[-1])
        assert result == {
            "offset_tcp_motion": "PASS",
            "changed_tcp_rejected": "PASS",
            "hardware": False,
        }
    finally:
        if process.returncode is None:
            process.terminate()
            await process.wait()
