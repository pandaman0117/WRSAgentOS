"""调用真实 GLM，只查看计划。显式开启后可能产生模型费用。"""

import asyncio

from wrs_agent.planner import ModelPlanner, PlanRequest
from wrs_agent.planner.providers.glm import GLMClient, GLMConfig
from wrs_agent.skills import SKILLS

ALLOW_LIVE_MODEL = False  # 确认服务权限和费用后，手动改为 True。
GOAL = "put A in B"


async def main():
    if not ALLOW_LIVE_MODEL:
        raise SystemExit("真实模型调用未开启；请先配置凭据，再明确修改 ALLOW_LIVE_MODEL。")

    # GLM_API_KEY、GLM_MODEL、GLM_BASE_URL 只从进程环境读取。
    model = GLMClient(GLMConfig.from_env(), live_model=True)
    try:
        decision = await ModelPlanner(model).plan(
            PlanRequest(
                user_goal=GOAL,
                world={"objects": {"A": "table"}, "held_object": None, "targets": ["B", "C"]},
                skills=[skill.spec.model_dump() for skill in SKILLS.values()],
            )
        )
        print("规划决定：", decision.kind)
        print("计划：", decision.plan)
        print("说明：", decision.text)
    finally:
        await model.aclose()


if __name__ == "__main__":
    asyncio.run(main())
