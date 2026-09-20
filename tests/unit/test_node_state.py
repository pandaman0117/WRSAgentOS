import pytest
from pydantic import ValidationError

from wrs_agent.nodes.tts import make_mock_tts
from wrs_agent.schemas import NodeSnapshot, RobotData, SpeechData


async def test_typed_snapshots_are_independent_observations(make_env, tmp_path):
    robot = make_env()
    tts = make_mock_tts(tmp_path / "tts.sqlite3")
    try:
        first = robot.snapshot()
        second = robot.snapshot()
        assert isinstance(first.data, RobotData)
        assert first.node_id == "wrs" and first.boot_id == robot.boot_id
        assert first.captured_at_ns <= second.captured_at_ns
        assert first.state_version == second.state_version
        first.data.objects["A"] = "caller-only"
        assert robot.snapshot().data.objects["A"] == "table"
        for _ in range(100):
            speech = tts.snapshot()
            assert isinstance(speech.data, SpeechData)
            assert speech.node_id == "tts"
            assert set(speech.data.model_dump()) == {"kind", "completed", "last_text"}
            assert "lease_id" not in speech.model_dump()
        assert not robot.leases and not tts.leases
        assert NodeSnapshot.model_validate_json(speech.model_dump_json()) == speech
    finally:
        await robot.close()
        await tts.close()


@pytest.mark.parametrize(
    "change",
    [
        {"data": {"kind": "speech", "pose": "B"}},
        {"data": {"kind": "robot", "last_text": "wrong node"}},
        {"data": {"kind": "unregistered"}},
        {"data": {"kind": "speech", "completed": "1"}},
        {"captured_at_ns": 0},
        {"node_id": ""},
    ],
)
async def test_snapshot_rejects_wrong_business_fields_and_source(make_env, change):
    env = make_env()
    try:
        payload = {**env.snapshot().model_dump(), **change}
        with pytest.raises(ValidationError):
            NodeSnapshot.model_validate(payload)
    finally:
        await env.close()
