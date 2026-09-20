"""GLM 示例响应 → Runtime → 独立 Mock 节点；不联网。"""

import asyncio
from pathlib import Path

import httpx

from wrs_agent.bindings import load_bindings
from wrs_agent.planner import ModelPlanner
from wrs_agent.planner.providers.glm import GLMClient, GLMConfig
from wrs_agent.processes import LocalStack
from wrs_agent.runtime import Runtime
from wrs_agent.schemas import GoalRequest, new_id

ROOT = Path(__file__).resolve().parents[2]
BINDINGS = ROOT / "configs/actions.toml"
REPLY = (ROOT / "examples/fixtures/glm_tool_call.json").read_bytes()


async def main():
    http = httpx.MockTransport(lambda request: httpx.Response(200, content=REPLY))
    model = GLMClient(GLMConfig(model="offline-fixture"), transport=http)
    try:
        # 这里只启动动作节点，当前脚本显式创建 Runtime 和 Planner。
        async with LocalStack(bindings=BINDINGS) as stack:
            runtime = Runtime(
                stack.system.clients,
                load_bindings(BINDINGS)[1],
                ModelPlanner(model),
                registry=stack.system.registry,
            )
            try:
                request = GoalRequest(request_id=new_id(), goal="put A in B")
                await runtime.goal(request)
                await runtime.planning
                planned = runtime.goal_status(request.request_id)
                print("规划结果：", planned["state"])
                if planned["task_id"]:
                    task = runtime.task_status(planned["task_id"])
                    print("任务结果：", task["state"])
                    print("A 的位置：", (await stack.system.snapshot()).data.objects["A"])
            finally:
                await runtime.close()
    finally:
        await model.aclose()


if __name__ == "__main__":
    asyncio.run(main())
