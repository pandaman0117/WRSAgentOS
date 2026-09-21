"""Load a bounded, explicit initial scene; this is configuration, not a sensor stream."""

import tomllib
from pathlib import Path
from typing import Literal

from pydantic import Field

from wrs_agent.schemas import MAX_BYTES, Boundary, Name, ObjectData, encode


class SceneConfig(Boundary):
    frame_id: Literal["world"] = "world"
    objects: dict[Name, ObjectData] = Field(default_factory=dict, max_length=32)


def load_scene(path):
    with Path(path).open("rb") as source:
        contents = source.read(MAX_BYTES + 1)
    if len(contents) > MAX_BYTES:
        raise ValueError("scene_config_too_large")
    config = SceneConfig.model_validate(tomllib.loads(contents.decode("utf-8")))
    for obj in config.objects.values():
        if obj.source != "configuration" or obj.observed_at_ns is not None:
            raise ValueError("scene_file_is_configuration_not_sensor_observation")
    # Leave room in the existing 64 KiB response for the robot and node envelope.
    if len(encode(config)) > MAX_BYTES // 2:
        raise ValueError("scene_snapshot_too_large")
    return config.objects
