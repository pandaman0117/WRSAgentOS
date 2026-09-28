"""Robot node: the Environment remains the only robot action owner."""

from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from wrs_agent.nodes.node import Node
from wrs_agent.nodes.options import Duration
from wrs_agent.schemas import Boundary


class WrsOptions(Boundary):
    backend: Literal["mock", "wrs"] = "mock"
    duration: Duration = 0.4
    scene: Path | None = Field(default=None, strict=False)
    fault: (
        Literal[
            "grasp",
            "grasp_once",
            "localization",
            "localization_once",
            "unknown",
            "inconclusive",
            "stop_unknown",
        ]
        | None
    ) = None

    @model_validator(mode="after")
    def validate_scene(self):
        if self.scene is not None:
            if self.backend != "wrs":
                raise ValueError("scene_requires_wrs_backend")
            from wrs_agent.scene import load_scene

            load_scene(self.scene)
        return self


class WrsNode(Node):
    node_type = "wrs"
    action_service = True
    launch_options = {
        "backend": "backend",
        "duration": "duration",
        "scene": "scene",
        "fault": "fault",
    }
    options_type = WrsOptions

    async def setup(self):
        options = self.options
        if options.backend == "wrs":
            from wrs_agent.env.wrs import make_wrs_environment

            executor = await make_wrs_environment(
                self.journal,
                duration=options.duration,
                scene=options.scene,
            )
        else:
            from wrs_agent.env.mock import make_mock_environment

            executor = make_mock_environment(
                self.journal,
                duration=options.duration,
                fault=options.fault,
            )
        self.actions(executor)
