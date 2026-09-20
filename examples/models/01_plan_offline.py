"""读取一份 GLM 示例响应，生成计划；不联网、不执行动作。"""

import asyncio
from pathlib import Path

import httpx

from wrs_agent.planner import ModelPlanner, PlanRequest
from wrs_agent.planner.providers.glm import GLMClient, GLMConfig
from wrs_agent.skills import SKILLS

REPLY = (Path(__file__).parents[1] / "fixtures/glm_tool_call.json").read_bytes()


async def main():
    # HTTP 夹具只代替服务器回包，其余仍经过真实 GLM 响应解析。
    http = httpx.MockTransport(lambda request: httpx.Response(200, content=REPLY))
    model = GLMClient(GLMConfig(model="offline-fixture"), transport=http)
    try:
        planner = ModelPlanner(model)
        request = PlanRequest(
            user_goal="put A in B",
            world={"objects": {"A": "table"}, "held_object": None, "targets": ["B", "C"]},
            skills=[skill.spec.model_dump() for skill in SKILLS.values()],
        )
        decision = await planner.plan(request)
        print("规划决定：", decision.kind)
        for item in decision.plan.steps:
            print(item.skill, item.args)
    finally:
        await model.aclose()


if __name__ == "__main__":
    asyncio.run(main())
