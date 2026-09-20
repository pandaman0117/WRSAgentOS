"""真实 GLM 规划，独立 Mock 节点执行；显式开启后可能产生模型费用。"""

import asyncio

from wrs_agent.processes import LocalStack

ALLOW_LIVE_MODEL = False  # 确认服务权限和费用后，手动改为 True。
GOAL = "put A in B"


async def main():
    if not ALLOW_LIVE_MODEL:
        raise SystemExit("真实模型调用未开启；请先配置凭据，再明确修改 ALLOW_LIVE_MODEL。")

    async with LocalStack(model_provider="glm", live_model=True) as stack:
        planning = await stack.system.goal(GOAL)
        proposed = await planning.wait(timeout=30)
        print("规划结果：", proposed.state)
        if proposed.task is not None:
            result = await proposed.task.wait()
            print("任务结果：", result.state)
        else:
            print("说明：", proposed.reason)


if __name__ == "__main__":
    asyncio.run(main())
