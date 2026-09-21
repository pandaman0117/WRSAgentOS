"""订阅机器人动作事件；最终结果仍通过动作句柄查询。"""

import asyncio
from pathlib import Path

from wrs_agent.processes import LocalStack
from wrs_agent.transport import decode

BINDINGS = Path(__file__).resolve().parents[2] / "configs/robot.toml"


async def main():
    async with LocalStack(backend="wrs", bindings=BINDINGS, duration=0.5) as stack:
        robot = stack.system.clients["wrs"]
        events = robot.transport.subscribe("events/action", capacity=8)
        motion = await stack.system.action("move_named_pose", pose="B")

        async with asyncio.timeout(3):
            while True:
                sample = events.try_recv()
                if sample is not None:
                    event = decode(sample.payload.to_bytes())
                    print("收到事件：", event["action_id"], event["state"])
                    break
                await asyncio.sleep(0.01)

        print("动作结果：", (await motion.wait()).state)


if __name__ == "__main__":
    asyncio.run(main())
