"""Explicit skill contracts and bundled guidance; no automatic code loading."""

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from functools import lru_cache
from hashlib import sha256
from importlib.resources import files
from typing import Literal

from pydantic import Field, ValidationError, model_validator

from wrs_agent.errors import AgentError
from wrs_agent.schemas import (
    Boundary,
    Empty,
    Name,
    ObjectData,
    RobotData,
    SceneData,
    SkillVersion,
    SpeechData,
)


class MoveArgs(Boundary):
    pose: Literal["home", "B", "C"]


class RelativeMoveArgs(Boundary):
    dx: float = Field(default=0.0, ge=-0.05, le=0.05, description="World X displacement in meters")
    dy: float = Field(default=0.0, ge=-0.05, le=0.05, description="World Y displacement in meters")
    dz: float = Field(default=0.0, ge=-0.05, le=0.05, description="World Z displacement in meters")

    @model_validator(mode="after")
    def bounded_displacement(self):
        distance_squared = self.dx**2 + self.dy**2 + self.dz**2
        if not 0 < distance_squared <= 0.05**2 + 1e-12:
            raise ValueError("displacement_must_be_nonzero_and_at_most_5cm")
        return self


class PickArgs(Boundary):
    object: Name


class PlaceArgs(PickArgs):
    target: Literal["B", "C"]


class SpeakArgs(Boundary):
    text: str = Field(min_length=1, max_length=512)


class SkillSpec(Boundary):
    name: Name
    version: SkillVersion = 1
    description: str
    instructions: str = Field(default="", max_length=8192)
    aliases: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    parameters: dict
    required_capabilities: list[str]
    resources: list[str]
    preconditions: list[str]
    verification: str
    interrupt_mode: str = "controlled_stop"
    timeout: float = Field(default=10.0, gt=0)
    recovery: list[str] = Field(default_factory=list)


@dataclass
class VirtualWorld:
    objects: dict[str, str]
    held: str | None = None
    pose: str = "home"
    version: int = 0
    calibration: str = "mock-v1"

    def snapshot(self):
        return SceneData(
            robot=RobotData(held_object=self.held, pose=self.pose),
            objects={
                name: ObjectData(location=location, source="mock")
                for name, location in self.objects.items()
            },
            facts={"calibration": self.calibration},
        )


@dataclass
class SpeechState:
    version: int = 0
    completed: int = 0
    last_text: str = ""

    def snapshot(self):
        return SpeechData(completed=self.completed, last_text=self.last_text)


def observe(world, args, stop, progress):
    return True


def move_named_pose(world, args, stop, progress):
    world.pose = args.pose
    return world.pose == args.pose


def move_relative(world, args, stop, progress):
    # This contract requires an actual kinematic backend; Mock does not advertise it.
    raise ValueError("kinematic_backend_required")


def pick(world, args, stop, progress):
    if world.held is not None or args.object not in world.objects:
        raise ValueError("pick_precondition")
    world.held = args.object
    world.objects[args.object] = "gripper"
    return world.held == args.object


def place(world, args, stop, progress):
    if world.held != args.object or args.target not in {"B", "C"}:
        raise ValueError("place_precondition")
    world.objects[args.object] = args.target
    world.held = None
    return world.objects[args.object] == args.target and world.held is None


def verify(world, args, stop, progress):
    return world.objects.get(args.object) == args.target and world.held is None


def speak(state, args, stop, progress):
    # Virtual completion of the full utterance, never a claim about audible output.
    state.last_text = args.text
    state.completed += 1
    return state.last_text == args.text


@dataclass(frozen=True)
class Skill:
    """An explicit contract, argument validator and locally reviewed handler."""

    spec: SkillSpec
    arguments: type[Boundary]
    handler: Callable[..., bool | Awaitable[bool]]


# Only bundled guides are read. Markdown never registers executable code.
_GUIDES = {
    name: files(__package__).joinpath(name, "SKILL.md").read_text(encoding="utf-8")
    for name in ("robot", "speech")
}


def _skill(
    name,
    arguments,
    handler,
    description,
    aliases,
    tags,
    *,
    preconditions=(),
    recovery=(),
    resources=("arm",),
    guide="robot",
    verification="virtual_world_postcondition",
):
    return Skill(
        SkillSpec(
            name=name,
            description=description,
            aliases=aliases,
            tags=tags,
            instructions=_GUIDES[guide],
            parameters=arguments.model_json_schema(),
            required_capabilities=[name],
            resources=list(resources),
            preconditions=list(preconditions),
            recovery=list(recovery),
            verification=verification,
        ),
        arguments,
        handler,
    )


SKILLS = {
    entry.spec.name: entry
    for entry in (
        _skill(
            "observe",
            Empty,
            observe,
            "Read current object and robot evidence",
            ["观察", "检测", "observe"],
            ["perception"],
        ),
        _skill(
            "move_named_pose",
            MoveArgs,
            move_named_pose,
            "Move to a validated named joint pose",
            ["移动", "回家", "move", "home"],
            ["motion"],
            preconditions=("known_pose",),
        ),
        _skill(
            "move_relative",
            RelativeMoveArgs,
            move_relative,
            "Offset the flange in world XYZ meters (up +Z, left +Y), at most 5 cm; "
            "preserve endpoint orientation, joint-interpolated path without collision checking",
            ["上", "下", "左", "右", "relative", "offset"],
            ["motion"],
            preconditions=("reachable_target",),
            verification="wrs_fk",
        ),
        _skill(
            "pick",
            PickArgs,
            pick,
            "Acquire an observed object and verify holding",
            ["抓取", "拿起", "pick"],
            ["manipulation"],
            preconditions=("empty_gripper", "object_visible"),
            recovery=("observe_once",),
        ),
        _skill(
            "place",
            PlaceArgs,
            place,
            "Place the held object at a known target",
            ["放", "放置", "put", "place"],
            ["manipulation"],
            preconditions=("object_held", "known_target"),
        ),
        _skill(
            "verify",
            PlaceArgs,
            verify,
            "Confirm object placement and empty gripper",
            ["检查", "验证", "verify"],
            ["verification"],
        ),
        _skill(
            "speak",
            SpeakArgs,
            speak,
            "Speak an utterance on the independent TTS node",
            ["说", "播报", "speak", "say"],
            ["audio"],
            resources=("speaker",),
            guide="speech",
            verification="virtual_utterance_complete",
        ),
    )
}


def validate_skill(name, version, args, *, registry=None):
    entry = (SKILLS if registry is None else registry).get(name)
    if entry is None:
        raise AgentError("unknown_skill")
    if version != entry.spec.version:
        raise AgentError("skill_version_mismatch")
    try:
        return entry.arguments.model_validate(args)
    except ValidationError:
        raise AgentError("invalid_arguments") from None


def require_contract(name, version, offered, *, node_id=None, stage=None):
    """Check a provider's version declaration, without copying its argument schema."""
    if name not in offered:
        raise AgentError("skill_not_on_node", node_id=node_id, stage=stage)
    if offered[name] != version:
        raise AgentError("skill_version_mismatch", node_id=node_id, stage=stage)


def registry_signature():
    payload = {name: entry.spec.model_dump() for name, entry in sorted(SKILLS.items())}
    return sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


@lru_cache(maxsize=128)
def _rank_candidates(query, signature, available):
    # Cache names only. Permission and current capabilities are checked by every caller.
    scores = {}
    transfer = any(word in query for word in ("放", "put ", "place "))
    for name in available:
        spec = SKILLS[name].spec
        score = sum(word.casefold() in query for word in [name, *spec.aliases, *spec.tags])
        if transfer and name in {"observe", "pick", "place", "verify"}:
            score += 1
        scores[name] = score
    ranked = sorted(available, key=lambda name: (-scores[name], name))
    return tuple(name for name in ranked if scores[name]) or tuple(ranked)


def lookup_skills(query, capabilities, bindings, *, limit=8):
    if not 1 <= limit <= 16:
        raise ValueError("invalid_skill_limit")
    available = tuple(
        name
        for name, entry in sorted(SKILLS.items())
        if (cap := capabilities.get(bindings.get(name))) is not None
        and cap.skills.get(name) == entry.spec.version
        and set(entry.spec.required_capabilities).issubset(cap.skills)
    )
    names = _rank_candidates(query.casefold().strip(), registry_signature(), available)
    # Return copies: callers cannot mutate the live registry through metadata lists.
    return [SKILLS[name].spec.model_copy(deep=True) for name in names[:limit]]
