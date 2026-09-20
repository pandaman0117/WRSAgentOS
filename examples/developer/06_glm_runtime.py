"""GLM adapter -> Runtime -> independent Mock nodes; offline unless --live-model."""

import argparse
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
CONFIG = ROOT / "configs/actions.toml"
FIXTURE = ROOT / "examples/fixtures/glm_tool_call.json"


async def run(args):
    config = GLMConfig.from_env() if args.live_model else GLMConfig(model="offline-fixture")
    model = GLMClient(
        config,
        live_model=args.live_model,
        transport=None
        if args.live_model
        else httpx.MockTransport(lambda request: httpx.Response(200, content=FIXTURE.read_bytes())),
    )
    try:
        async with LocalStack(bindings=CONFIG, duration=0.03) as stack:
            runtime = Runtime(
                stack.system.clients,
                load_bindings(CONFIG)[1],
                ModelPlanner(model),
                registry=stack.system.registry,
            )
            try:
                request = GoalRequest(request_id=new_id(), goal=args.goal)
                await runtime.goal(request)
                # For an embedded Runtime, this future includes execution of its accepted plan.
                await runtime.planning
                result = runtime.goal_status(request.request_id)
                print(
                    "profile:",
                    "GLM live + Mock nodes" if args.live_model else "GLM HTTP fixture + Mock nodes",
                )
                print("planning:", result)
                if result["task_id"]:
                    task = runtime.task_status(result["task_id"])
                    print("task:", task)
                    assert task["state"] == "SUCCEEDED", task
                elif result["state"] in {"FAILED", "STALE"} or not args.live_model:
                    raise RuntimeError(result)
                if not args.live_model:
                    assert (await stack.system.snapshot()).data.objects["A"] == "B"
                    assert runtime.planner_calls == 1
                print("No hardware or audio backend is started.")
            finally:
                await runtime.close()
    finally:
        await model.aclose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live-model", action="store_true")
    parser.add_argument("--goal", default="put A in B")
    asyncio.run(run(parser.parse_args()))
