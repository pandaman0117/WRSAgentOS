"""向另一个进程中的机器人查询一次状态。"""

import asyncio
from pathlib import Path

from wrs_agent.processes import LocalStack

BINDINGS = Path(__file__).resolve().parents[2] / "configs/robot.toml"


async def main():
    async with LocalStack(backend="wrs", bindings=BINDINGS) as stack:
        robot = stack.system.clients["wrs"]
        state = await robot.snapshot()
        print("节点：", state.node_id)
        print("当前位置：", state.data.robot.pose)


if __name__ == "__main__":
    asyncio.run(main())
