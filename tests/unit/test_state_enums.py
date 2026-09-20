"""Keep Python enum results compatible with the existing strict wire/journal contracts."""

import json
import sqlite3

import pytest
from pydantic import ValidationError

from wrs_agent import ActionState, GoalState, TaskState
from wrs_agent.schemas import (
    ActionReceipt,
    ActionStatus,
    GoalStatus,
    TaskCancelReceipt,
    TaskStatus,
    decode,
    encode,
)
from wrs_agent.store import Journal

CONTRACTS = [
    (
        ActionStatus,
        {"action_id": "action"},
        ActionState,
        [
            "ACCEPTED",
            "RUNNING",
            "VERIFYING",
            "SUCCEEDED",
            "FAILED",
            "CANCELLING",
            "CANCELLED",
            "UNKNOWN",
        ],
    ),
    (
        TaskStatus,
        {"task_id": "task"},
        TaskState,
        ["QUEUED", "RUNNING", "CANCELLING", "SUCCEEDED", "FAILED", "CANCELLED", "UNKNOWN"],
    ),
    (
        GoalStatus,
        {"request_id": "goal"},
        GoalState,
        ["WAITING", "DONE", "ANSWER", "CLARIFY", "FAILED", "STALE", "REQUIRES_CONFIRMATION"],
    ),
    (
        TaskCancelReceipt,
        {"task_id": "task", "accepted": True, "phase": "STOPPING"},
        TaskState,
        ["CANCELLING", "SUCCEEDED", "FAILED", "CANCELLED", "UNKNOWN"],
    ),
]


@pytest.mark.parametrize(
    "model, fields, enum, value",
    [(model, fields, enum, value) for model, fields, enum, values in CONTRACTS for value in values],
)
def test_legacy_strings_parse_to_enums_and_serialize_to_original_values(model, fields, enum, value):
    raw = {**fields, "state": value}
    expected = enum(value)
    result = model.model_validate(raw)
    assert result.state is expected
    assert model.model_validate_json(json.dumps(raw)).state is expected
    assert model(**fields, state=expected).state is expected
    assert model.model_validate(result.model_dump()).state is expected
    assert result.state == value and str(result.state) == value and f"{result.state}" == value
    assert isinstance(result.state, str)
    assert {result.state: "same key"}[value] == "same key"
    assert result.model_dump()["state"] is expected
    assert type(result.model_dump(mode="json")["state"]) is str
    assert json.loads(result.model_dump_json())["state"] == value
    assert decode(encode(result))["state"] == value
    # Services also serialize dictionaries containing enum members.
    assert decode(encode(result.model_dump()))["state"] == value


@pytest.mark.parametrize("model, fields, enum, values", CONTRACTS)
@pytest.mark.parametrize("value", ["running", "SUCESS", "IDLE", "", 1, True, None, b"RUNNING", {}])
def test_state_validation_does_not_coerce_or_accept_unknown_values(
    model, fields, enum, values, value
):
    with pytest.raises(ValidationError):
        model.model_validate({**fields, "state": value})


@pytest.mark.parametrize("value", ["QUEUED", "RUNNING", TaskState.QUEUED, TaskState.RUNNING])
def test_cancel_receipt_keeps_its_original_state_subset(value):
    with pytest.raises(ValidationError):
        TaskCancelReceipt(task_id="task", state=value, accepted=True, phase="STOPPING")


@pytest.mark.parametrize(
    "model, fields, value",
    [
        (ActionStatus, {"action_id": "action"}, "DONE"),
        (TaskStatus, {"task_id": "task"}, "VERIFYING"),
        (GoalStatus, {"request_id": "goal"}, "SUCCEEDED"),
    ],
)
def test_distinct_lifecycles_do_not_gain_each_others_values(model, fields, value):
    with pytest.raises(ValidationError):
        model.model_validate({**fields, "state": value})


@pytest.mark.parametrize("model, fields, enum, values", CONTRACTS)
def test_json_schema_keeps_exact_allowed_wire_values(model, fields, enum, values):
    schema = model.model_json_schema()
    state = schema["properties"]["state"]
    if "$ref" in state:
        state = schema["$defs"][state["$ref"].rsplit("/", 1)[-1]]
    assert state["type"] == "string" and state["enum"] == values


def test_nested_action_receipt_retains_enum_and_other_fields_remain_strict():
    raw = {"accepted": True, "status": {"action_id": "action", "state": "ACCEPTED"}}
    assert ActionReceipt.model_validate(raw).status.state is ActionState.ACCEPTED
    assert ActionReceipt.model_validate_json(json.dumps(raw)).status.state is ActionState.ACCEPTED
    with pytest.raises(ValidationError):
        ActionReceipt.model_validate({**raw, "accepted": "true"})
    with pytest.raises(ValidationError):
        ActionStatus(action_id="action", state="RUNNING", progress="0.5")


@pytest.mark.parametrize("legacy_state", ["RUNNING", "SUCCEEDED"])
def test_old_sqlite_records_restore_enum_even_when_recovery_changes_state(tmp_path, legacy_state):
    path = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE actions (id TEXT PRIMARY KEY, request TEXT, status TEXT)")
        db.execute(
            "INSERT INTO actions VALUES (?, ?, ?)",
            (
                "action",
                "{}",
                json.dumps({"action_id": "action", "state": legacy_state}),
            ),
        )
    expected = ActionState.UNKNOWN if legacy_state == "RUNNING" else ActionState.SUCCEEDED
    journal = Journal(path)
    try:
        status = journal.records["action"][1]
        assert status.state is expected
        if legacy_state == "RUNNING":
            assert status.reason == "environment_restarted"
            assert status.verification == "INCONCLUSIVE"
        with sqlite3.connect(path) as db:
            saved = json.loads(db.execute("SELECT status FROM actions").fetchone()[0])
        assert saved["state"] == expected.value and type(saved["state"]) is str
    finally:
        journal.close()
