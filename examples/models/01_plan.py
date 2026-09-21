"""在线调用 GLM，根据 WRS 节点的真实状态和能力生成计划，不执行运动。"""

import asyncio
from pathlib import Path

from wrs_agent.planner import ModelPlanner, PlanRequest
from wrs_agent.planner.providers.glm import GLMClient, GLMConfig, GLMError
from wrs_agent.processes import LocalStack

CONFIG = Path(__file__).resolve().parents[2] / "configs/robot.toml"
GOAL = "将机械臂移动到命名姿态 B。"


async def main():
    # GLM_API_KEY、GLM_MODEL、GLM_BASE_URL 从环境读取；运行本文件会调用在线模型。
    try:
        model = GLMClient(GLMConfig.from_env(), live_model=True)
    except GLMError as exc:
        raise SystemExit(f"GLM 配置错误：{exc.error.message}") from None
    try:
        async with LocalStack(backend="wrs", bindings=CONFIG) as stack:
            snapshot = await stack.system.snapshot()
            skills = await stack.system.skills()
            decision = await ModelPlanner(model).plan(
                PlanRequest(
                    user_goal=GOAL,
                    world=snapshot.data.model_dump(),
                    skills=[skill.model_dump() for skill in skills],
                )
            )
            print("规划决定：", decision.kind)
            print("计划：", decision.plan)
            print("说明：", decision.text)
    except GLMError as exc:
        raise SystemExit(f"GLM 请求失败（{exc.code}）：{exc.error.message}") from None
    finally:
        await model.aclose()


if __name__ == "__main__":
    asyncio.run(main())
