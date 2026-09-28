"""先启动 Agent，再加入未写入部署配置的节点；只打印问候，不连接设备。"""

import asyncio
import os
import secrets
from pathlib import Path

from examples.nodes.greet_skill import GREET
from wrs_agent import System, step
from wrs_agent.executor import ActionExecutor
from wrs_agent.nodes import Node
from wrs_agent.nodes.serve import serve_node
from wrs_agent.nodes.tts.backend import SpeechState

JOURNAL = Path(__file__).resolve().parents[2] / ".local/state/late-greeting.db"


class GreetingNode(Node):
    action_service = True

    async def setup(self):
        self.actions(ActionExecutor(
            self.journal, state=SpeechState(), backend="console",
            skills=[GREET],
            features_extra={"robot_controls": False, "controller_flush": False},
        ))


async def main():
    if not os.environ.get("WRS_AGENT_TOKEN"):
        os.environ["WRS_AGENT_TOKEN"] = secrets.token_urlsafe(32)
    async with System.launch() as system:
        print("Agent 已启动，当前节点：", ", ".join(await system.nodes()))
        worker = asyncio.create_task(serve_node(
            GreetingNode, node_id="late-greeting", endpoint=system.endpoint,
            site=system.site, env_id=system.env_id, journal=JOURNAL,
        ))
        try:
            await system.registry.wait_for("late-greeting")
            action = await system.action("greet", name="新节点")
            print("直接调用：", (await action.wait()).state)
            task = await system.start(step("greet", name="任务"))
            print("Agent 调度：", (await task.wait()).state)
        finally:
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)


if __name__ == "__main__":
    asyncio.run(main())
