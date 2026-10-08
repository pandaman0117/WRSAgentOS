import asyncio
import json
from pathlib import Path

import pytest

from wrs_agent.executor import SkillFailure
from wrs_agent.nodes.vision.skills import DETECT, detect
from wrs_agent.nodes.vision.state import VisionState
from wrs_agent.nodes.vision.worker import ModelWorker
from wrs_agent.schemas import NodeSnapshot, VisionData


def test_vision_snapshot_roundtrip():
    data = VisionData(task="detect", summary="1 detect: cup", items=())
    snapshot = NodeSnapshot(
        node_id="yolo",
        boot_id="boot",
        captured_at_ns=1,
        control_epoch=0,
        state_version=0,
        admission="OPEN",
        active_action=None,
        stop_confirmed=True,
        data=data,
    )
    restored = NodeSnapshot.model_validate_json(snapshot.model_dump_json())
    assert isinstance(restored.data, VisionData)
    assert restored.data.task == "detect"


def test_detect_rejects_a_missing_image(tmp_path):
    state = VisionState(worker=None, result_dir=tmp_path)

    async def call():
        await detect(
            state,
            DETECT.arguments(image="missing.png"),
            asyncio.Event(),
            lambda _value: None,
        )

    with pytest.raises(SkillFailure, match="input_missing"):
        asyncio.run(call())


def test_worker_records_a_detection(tmp_path):
    script = tmp_path / "fake_worker.py"
    script.write_text(
        "import json, sys\n"
        "sys.stdout.write(json.dumps({'ready': True}) + '\\n')\n"
        "sys.stdout.flush()\n"
        "for line in sys.stdin:\n"
        "    sys.stdout.write(json.dumps({'ok': True, 'count': 1, 'items': ["
        "{'label': 'cup', 'score': 0.9, 'xyxy': [1, 2, 30, 40]}]})\n"
        " + '\\n')\n"
        "    sys.stdout.flush()\n",
        encoding="utf-8",
    )
    image = tmp_path / "frame.png"
    image.write_bytes(b"\x89PNG\r\n")
    worker = ModelWorker(script.name, "yolo")
    worker.script = script
    worker.start()
    try:
        state = VisionState(worker, tmp_path / "results")
        state.result_dir.mkdir()

        async def call():
            options = DETECT.arguments(image=str(image))
            return await detect(state, options, asyncio.Event(), lambda _value: None)

        assert asyncio.run(call()) is True
    finally:
        worker.close()
    assert state.completed == 1
    assert state.items[0].label == "cup"
    saved = json.loads(Path(state.result_path).read_text(encoding="utf-8"))
    assert saved["count"] == 1
