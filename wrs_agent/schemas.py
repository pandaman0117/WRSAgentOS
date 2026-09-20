"""Strict, bounded JSON contracts. No device or provider objects cross this boundary."""

import json
from graphlib import TopologicalSorter
from typing import Annotated, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_BYTES = 65536
Name = Annotated[str, Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_.-]+$")]
Counter = Annotated[int, Field(ge=0, le=2**53)]
SkillVersion = Annotated[int, Field(ge=1, le=2**31 - 1)]
Scalar = str | int | float | bool | None
State = Literal[
    "ACCEPTED",
    "RUNNING",
    "VERIFYING",
    "SUCCEEDED",
    "FAILED",
    "CANCELLING",
    "CANCELLED",
    "UNKNOWN",
]
TERMINAL = {"SUCCEEDED", "FAILED", "CANCELLED", "UNKNOWN"}


def new_id() -> str:
    return uuid4().hex


class Boundary(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True, allow_inf_nan=False)


class ErrorInfo(Boundary):
    """Stable machine code plus safe context; never a serialized exception/input dump."""

    code: Name
    message: str = Field(default="", max_length=240)
    stage: Literal["discovery", "preflight", "submit", "observe", "control", "planning"] | None = (
        None
    )
    node_id: Name | None = None
    task_id: Name | None = None
    action_id: Name | None = None


class Envelope(Boundary):
    schema_version: Literal[3] = 3
    message_id: Name = Field(default_factory=new_id)
    trace_id: Name = Field(default_factory=new_id)
    source: Name
    category: Literal["control", "interactive", "background"] = "interactive"
    session: Name
    env_id: Name
    auth: Annotated[str, Field(min_length=16, max_length=128, repr=False)]
    payload: dict


def encode(value: dict | Boundary) -> bytes:
    if isinstance(value, Boundary):
        value = value.model_dump(mode="json")
    result = json.dumps(value, allow_nan=False, separators=(",", ":")).encode()
    if len(result) > MAX_BYTES:
        raise ValueError("payload_too_large")
    return result


def decode(data: bytes) -> dict:
    if len(data) > MAX_BYTES:
        raise ValueError("payload_too_large")
    result = json.loads(
        data, parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite"))
    )
    if not isinstance(result, dict):
        raise ValueError("object_required")
    return result


class ActionRequest(Boundary):
    action_id: Name
    task_id: Name
    task_revision: Counter
    boot_id: Name
    control_epoch: Counter
    lease_id: Name
    skill: Name
    version: SkillVersion = 1
    args: Annotated[dict[Name, Scalar], Field(max_length=8)] = Field(default_factory=dict)
    state_version: Counter


class ActionStatus(Boundary):
    action_id: Name
    state: State
    sequence: Counter = 0
    progress: float = Field(default=0.0, ge=0, le=1)
    reason: Annotated[str, Field(max_length=240)] = ""
    verification: Literal["PENDING", "PASS", "FAIL", "INCONCLUSIVE"] = "PENDING"
    error: ErrorInfo | None = None


class ActionReceipt(Boundary):
    accepted: bool
    reason: str = ""
    status: ActionStatus | None = None
    error: ErrorInfo | None = None


class ControlRequest(Boundary):
    interrupt_id: Name
    boot_id: Name
    control_epoch: Counter
    action_id: Name | None = None
    state_version: Counter | None = None


class ControlReceipt(Boundary):
    accepted: bool
    reason: str = ""
    control_epoch: Counter
    phase: Literal["REJECTED", "STOPPING", "STOPPED", "UNKNOWN", "RESUMED"]
    error: ErrorInfo | None = None


class KinematicState(Boundary):
    joints: Annotated[list[float], Field(min_length=6, max_length=6)]
    joint_unit: Literal["rad"] = "rad"
    tip_position: Annotated[list[float], Field(min_length=3, max_length=3)]
    position_unit: Literal["m"] = "m"
    frame_id: Literal["world"] = "world"
    source: Literal["wrs_fk"] = "wrs_fk"
    observed_at_ns: int = Field(gt=0)
    valid: bool = True


class RobotData(Boundary):
    kind: Literal["robot"] = "robot"
    held_object: Name | None = None
    objects: dict[Name, Name] = Field(default_factory=dict, max_length=128)
    pose: Name | None = None
    kinematics: KinematicState | None = None
    facts: dict[Name, Scalar] = Field(default_factory=dict, max_length=32)


class SpeechData(Boundary):
    kind: Literal["speech"] = "speech"
    completed: Counter = 0
    last_text: str = Field(default="", max_length=512)


class NodeSnapshot(Boundary):
    """One execution node at capture time; never an atomic whole-system view or grant."""

    node_id: Name
    boot_id: Name
    captured_at_ns: int = Field(gt=0)  # Source wall clock; not a cross-host lease clock.
    control_epoch: Counter
    state_version: Counter  # Business-state revision, independent of control authority.
    admission: Literal["OPEN", "HELD", "UNKNOWN"]
    active_action: Name | None
    stop_confirmed: bool
    data: Annotated[RobotData | SpeechData, Field(discriminator="kind")]


class ActionContext(NodeSnapshot):
    """Current node state plus a short-lived, receiver-issued execution token."""

    lease_id: Name


class CapabilitySnapshot(Boundary):
    backend: Name = "mock"
    resources: list[Name] = Field(default_factory=list)
    skills: dict[Name, SkillVersion] = Field(max_length=64)
    robot_controls: bool = True
    hardware: Literal[False] = False
    controlled_stop: bool = True
    controller_flush: bool = True
    verification: Name = "virtual_state"
    stop_scope: Name = "virtual_state"
    unsupported: dict[Name, str] = Field(default_factory=dict)


class NodeInfo(Boundary):
    node_id: Name
    node_type: Literal["agent", "wrs", "tts", "voice", "vision"]
    boot_id: Name | None = None
    capabilities: list[Name] = Field(default_factory=list, max_length=64)
    skills: dict[Name, SkillVersion] = Field(default_factory=dict, max_length=64)
    resources: list[Name] = Field(default_factory=list, max_length=32)
    ready: bool = False
    health: Literal["ready", "held", "unknown", "offline", "stale", "unsupported"] = "offline"
    error: ErrorInfo | None = None


class Step(Boundary):
    step_id: Name
    skill: Name
    version: SkillVersion = 1
    args: Annotated[dict[Name, Scalar], Field(max_length=8)] = Field(default_factory=dict)
    category: Literal["interactive", "background"] = "interactive"
    depends_on: Annotated[list[Name], Field(max_length=12)] = Field(default_factory=list)


class Plan(Boundary):
    steps: Annotated[list[Step], Field(min_length=1, max_length=12)]

    @model_validator(mode="after")
    def valid_dag(self):
        ids = {s.step_id for s in self.steps}
        if len(ids) != len(self.steps):
            raise ValueError("duplicate_step")
        if any(d not in ids for s in self.steps for d in s.depends_on):
            raise ValueError("missing_dependency")
        tuple(TopologicalSorter({s.step_id: s.depends_on for s in self.steps}).static_order())
        return self


class TaskRequest(Boundary):
    request_id: Name
    plan: Plan


class TaskControl(Boundary):
    request_id: Name
    task_id: Name
    replacement: Plan | None = None


class IdRequest(Boundary):
    action_id: Name


class Empty(Boundary):
    pass


class GoalRequest(Boundary):
    request_id: Name
    goal: str = Field(min_length=1, max_length=1024)


class Interaction(Boundary):
    event_id: Name
    kind: Literal["vad", "ack", "query", "append", "revise", "stop", "barge_in"]
    confidence: float = Field(default=1.0, ge=0, le=1)
    quoted: bool = False
    negated: bool = False
    plan: Plan | None = None


class TaskQuery(Boundary):
    task_id: Name


class GoalQuery(Boundary):
    request_id: Name


class TaskStatus(Boundary):
    task_id: Name
    supersedes: Name | None = None
    state: Literal[
        "QUEUED", "RUNNING", "RESUMING", "HELD", "SUCCEEDED", "FAILED", "CANCELLED", "UNKNOWN"
    ]
    reason: str = ""
    steps: dict[str, str] = Field(default_factory=dict)
    active_actions: dict[str, str] = Field(default_factory=dict)
    error: ErrorInfo | None = None


class TaskHoldReceipt(Boundary):
    task_id: Name
    revision: Literal[0] = 0
    state: Literal["HELD", "UNKNOWN"]
    accepted: bool
    phase: Literal["STOPPING", "STOPPED", "UNKNOWN"]
    error: ErrorInfo | None = None


class GoalStatus(Boundary):
    request_id: Name
    state: Literal[
        "WAITING", "DONE", "ANSWER", "CLARIFY", "FAILED", "STALE", "REQUIRES_CONFIRMATION"
    ]
    reason: str = ""
    task_id: Name | None = None
    error: ErrorInfo | None = None


class InterruptRequest(Boundary):
    """An explicit operator stop binds the current task/planning once, at the receiver."""

    request_id: Name


class TextInput(Boundary):
    """Recognized text from a trusted local ASR/UI adapter; never raw audio."""

    input_id: Name = Field(default_factory=new_id)
    text: str = Field(min_length=1, max_length=1024)
    is_final: bool = True
    confidence: float = Field(default=1.0, ge=0, le=1)


class TextReceipt(Boundary):
    input_id: Name
    disposition: Literal["ignore", "clarify", "query", "goal", "stop", "cancel_tts"]
    accepted: bool = False
    reason: str = ""
    phase: Literal["STOPPING", "STOPPED", "UNKNOWN"] | None = None
    request_id: Name | None = None
    task_id: Name | None = None
    overview: dict | None = None
    error: ErrorInfo | None = None
