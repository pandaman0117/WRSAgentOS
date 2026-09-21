"""底层动作调用：获取 context，再由客户端构造并提交请求。"""

import asyncio
from pathlib import Path

from wrs_agent.processes import LocalStack

BINDINGS = Path(__file__).resolve().parents[2] / "configs/robot.toml"


async def main():
    async with LocalStack(backend="wrs", bindings=BINDINGS) as stack:
        robot = stack.system.clients["wrs"]
        context = await robot.context()
        motion = await robot.submit(
            "move_named_pose", {"pose": "B"}, context=context, task_id="example-submit"
        )
        print("动作编号：", motion.id)
        print("动作结果：", (await motion.wait()).state)


if __name__ == "__main__":
    asyncio.run(main())
