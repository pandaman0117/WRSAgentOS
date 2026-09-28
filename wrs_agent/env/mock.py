"""Offline robot simulation and fault injection behind the shared action lifecycle."""

import asyncio
from dataclasses import dataclass, field

from wrs_agent.executor import ActionExecutor, ExecutionUnknown, SkillFailure
from wrs_agent.schemas import ObjectData, RobotData, SceneData
from wrs_agent.skills.robot import SKILLS


@dataclass
class VirtualWorld:
    objects: dict[str, str]
    held: str | None = None
    pose: str = "home"
    version: int = 0
    calibration: str = "mock-v1"
    started: asyncio.Event = field(default_factory=asyncio.Event, repr=False)

    def snapshot(self):
        return SceneData(
            robot=RobotData(held_object=self.held, pose=self.pose),
            objects={
                name: ObjectData(location=location, source="mock")
                for name, location in self.objects.items()
            },
            facts={"calibration": self.calibration},
        )


def observe(world, args, stop, progress):
    return True


def move_named_pose(world, args, stop, progress):
    world.pose = args.pose
    return world.pose == args.pose


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


def make_mock_environment(journal_path, *, duration=0.4, fault=None):
    remaining = 1 if fault in {"grasp_once", "localization_once"} else None

    def simulate(handler):
        async def advance(world, args, stop, progress):
            nonlocal remaining
            world.started.set()
            if duration > 0:
                try:
                    await asyncio.wait_for(stop.wait(), timeout=duration)
                except TimeoutError:
                    pass
            if stop.is_set():
                if fault == "stop_unknown":
                    raise ExecutionUnknown("mock_stop_unconfirmed", reason="stop_unconfirmed")
                return False
            if fault in {"unknown", "inconclusive"}:
                raise ExecutionUnknown(
                    "mock_observation_unconfirmed", reason="observation_inconclusive"
                )
            if handler is pick and remaining != 0:
                if fault in {"localization", "localization_once", "grasp", "grasp_once"}:
                    if remaining is not None:
                        remaining -= 1
                    reason = (
                        "localization_failed"
                        if fault.startswith("localization")
                        else "grasp_failed"
                    )
                    raise SkillFailure(reason)
            return handler(world, args, stop, progress)

        return advance

    skills = [
        SKILLS[handler.__name__].bind(simulate(handler))
        for handler in (observe, move_named_pose, pick, place, verify)
    ]
    return ActionExecutor(
        journal_path,
        state=VirtualWorld({"A": "table", "D": "table"}),
        skills=skills,
        backend="mock",
    )
