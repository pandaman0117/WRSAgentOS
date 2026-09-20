"""终端三：启动认识 greet 合同的 Agent，调度交给既有 Runtime。"""

import asyncio
from pathlib import Path

from examples.nodes.greet_skill import register_greet
from wrs_agent.nodes.serve import serve_node

BINDINGS = Path(__file__).with_name("bindings.toml")

if __name__ == "__main__":
    register_greet()
    try:
        asyncio.run(
            serve_node(
                "agent",
                endpoint="tcp/127.0.0.1:7448",
                env_id="node-demo",
                bindings=BINDINGS,
            )
        )
    except KeyboardInterrupt:
        print("Agent 已关闭。")
