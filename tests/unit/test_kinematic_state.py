import pytest
from pydantic import ValidationError

from wrs_agent.schemas import KinematicState


def state_data():
    return {
        "qs": [0.0] * 6,
        "tcp_name": "flange",
        "tcp_pos": [0.1, 0.2, 0.3],
        "tcp_rotmat": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
        "observed_at_ns": 1,
    }


def test_tcp_state_roundtrips_with_coordinate_and_unit_metadata():
    state = KinematicState.model_validate(state_data())
    assert KinematicState.model_validate_json(state.model_dump_json()) == state
    assert state.frame_id == "world"
    assert state.position_unit == "m" and state.joint_unit == "rad"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("qs", [0.0] * 5),
        ("tcp_name", ""),
        ("tcp_pos", [0.0, float("nan"), 0.0]),
        ("tcp_rotmat", [[1.0, 0.0, 0.0]] * 2),
        ("tcp_rotmat", [[1.0, 0.0]] * 3),
        ("tcp_rotmat", [[float("inf"), 0.0, 0.0]] * 3),
        ("frame_id", "camera_optical"),
    ],
)
def test_tcp_state_rejects_incomplete_nonfinite_or_wrong_frame_values(field, value):
    with pytest.raises(ValidationError):
        KinematicState.model_validate({**state_data(), field: value})


def test_old_link_tip_fields_are_not_silently_treated_as_tcp():
    old = state_data()
    old["joints"] = old.pop("qs")
    old["tip_position"] = old.pop("tcp_pos")
    with pytest.raises(ValidationError):
        KinematicState.model_validate(old)
