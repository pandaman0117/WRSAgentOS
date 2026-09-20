"""查询一个不存在的服务，处理超时后继续查询正常服务。"""

import asyncio
from pathlib import Path

from wrs_agent.processes import LocalStack

BINDINGS = Path(__file__).resolve().parents[2] / "configs/robot.toml"


async def main():
    async with LocalStack(bindings=BINDINGS) as stack:
        transport = stack.system.clients["wrs"].transport
        try:
            await transport.request("request/missing", {}, timeout=0.2)
        except TimeoutError:
            print("查询超时，没有取消任何动作。")
        state = await stack.system.snapshot()
        print("仍可查询机器人：", state.data.pose)


if __name__ == "__main__":
    asyncio.run(main())
