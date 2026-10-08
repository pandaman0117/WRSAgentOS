"""Vision skills. Handlers call the resident model process."""

import asyncio
from pathlib import Path

from pydantic import Field

from wrs_agent.executor import SkillFailure
from wrs_agent.schemas import Boundary
from wrs_agent.skills import Skill

_IMAGE = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
_IMAGE_LIMIT = 20 * 1024 * 1024
_CLOUD_LIMIT = 64 * 1024 * 1024


class DetectArgs(Boundary):
    image: str = Field(min_length=1, max_length=240)
    conf: float = Field(default=0.25, gt=0, le=1)


class SegmentArgs(DetectArgs):
    text: str = Field(min_length=1, max_length=160)


class GraspArgs(Boundary):
    cloud: str = Field(min_length=1, max_length=240)
    top: int = Field(default=5, ge=1, le=8)


def _file(path, suffixes, limit):
    if not isinstance(path, str) or len(path) > 240:
        raise SkillFailure("invalid_path")
    candidate = Path(path)
    if candidate.suffix.lower() not in suffixes:
        raise SkillFailure("invalid_path")
    try:
        resolved = candidate.resolve()
        size = resolved.stat().st_size
    except OSError:
        raise SkillFailure("input_missing") from None
    if not resolved.is_file() or size <= 0 or size > limit:
        raise SkillFailure("input_missing")
    return str(resolved)


async def _run(state, task, source, payload, stop, progress):
    if stop.is_set():
        return False
    progress(0.1)
    reply = await asyncio.to_thread(state.worker.request, payload)
    if stop.is_set():
        return False
    state.record(task, source, reply)
    progress(1.0)
    return True


async def detect(state, options: DetectArgs, stop, progress):
    image = _file(options.image, _IMAGE, _IMAGE_LIMIT)
    payload = {"image": image, "conf": options.conf}
    return await _run(state, "detect", image, payload, stop, progress)


async def segment(state, options: SegmentArgs, stop, progress):
    image = _file(options.image, _IMAGE, _IMAGE_LIMIT)
    payload = {"image": image, "text": options.text, "conf": options.conf}
    return await _run(state, "segment", image, payload, stop, progress)


async def infer_grasps(state, options: GraspArgs, stop, progress):
    cloud = _file(options.cloud, {".npy"}, _CLOUD_LIMIT)
    payload = {"cloud": cloud, "top": options.top}
    return await _run(state, "infer_grasps", cloud, payload, stop, progress)


def _skill(name, arguments, handler, description):
    return Skill(
        name=name,
        arguments=arguments,
        handler=handler,
        description=description,
        resources=("vision",),
        verification="vision_result_recorded",
        timeout=120.0,
    )


DETECT = _skill(
    "detect",
    DetectArgs,
    detect,
    "Detect objects in one image with YOLO. Boxes are image pixels, not robot coordinates.",
)
SEGMENT = _skill(
    "segment",
    SegmentArgs,
    segment,
    "Segment comma-separated text prompts in one image with SAM3. "
    "Boxes are image pixels, not robot coordinates.",
)
INFER_GRASPS = _skill(
    "infer_grasps",
    GraspArgs,
    infer_grasps,
    "Propose grasp poses from a camera-frame .npy cloud with GraspNet. "
    "Translation and rotation stay in that cloud frame.",
)
