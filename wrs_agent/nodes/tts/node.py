"""Speech node: real and offline backends share one Action lifecycle."""

from typing import Literal

from wrs_agent.nodes.node import Node
from wrs_agent.nodes.options import Duration, Texts
from wrs_agent.schemas import Boundary


class TtsOptions(Boundary):
    backend: Literal["mock", "qwen"] = "mock"
    duration: Duration = 0.4
    prepared_texts: Texts = ()


class TtsNode(Node):
    node_type = "tts"
    action_service = True
    launch_options = {
        "backend": "tts_backend",
        "duration": "duration",
        "prepared_texts": "tts_prepared_texts",
    }
    options_type = TtsOptions

    async def setup(self):
        options = self.options
        if options.backend == "qwen":
            from wrs_agent.nodes.tts.qwen import make_qwen_tts

            executor = await make_qwen_tts(
                self.journal,
                prepared_texts=options.prepared_texts,
            )
        else:
            from wrs_agent.nodes.tts.backend import make_mock_tts

            executor = make_mock_tts(self.journal, duration=options.duration)
        self.actions(executor)
