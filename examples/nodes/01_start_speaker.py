"""终端二：启动提供 greet 技能的独立节点，仅打印文字，不播放声音。"""

import asyncio
from pathlib import Path

from examples._session import use_local_token
from examples.nodes.greet_skill import GREET
from wrs_agent.executor import ActionExecutor
from wrs_agent.nodes import Node
from wrs_agent.nodes.serve import serve_node
from wrs_agent.nodes.tts.backend import SpeechState

DIRECTORY = Path(__file__).resolve().parent
JOURNAL = DIRECTORY.parents[1] / ".local/state/example-speaker.sqlite3"


def create_speaker(journal):
    return ActionExecutor(
        journal,
        state=SpeechState(),
        backend="console_greeting",
        skills=[GREET],
        features_extra={
            "robot_controls": False,
            "controller_flush": False,
            "verification": "console_text_complete",
            "stop_scope": "console_character_boundary",
        },
    )


class SpeakerNode(Node):
    async def setup(self):
        self.actions(create_speaker(self.journal))


if __name__ == "__main__":
    use_local_token("nodes", create=True)
    try:
        asyncio.run(
            serve_node(
                SpeakerNode,
                node_id="speaker",
                endpoint="tcp/127.0.0.1:7448",
                env_id="node-demo",
                bindings=DIRECTORY / "bindings.toml",
                journal=JOURNAL,
            )
        )
    except KeyboardInterrupt:
        print("Speaker 已关闭。")
