import json
from pathlib import Path

import httpx
import pytest

from wrs_agent.bindings import load_bindings
from wrs_agent.planner import ModelPlanner
from wrs_agent.planner.providers.llm import LLMClient, LLMConfig
from wrs_agent.processes import LocalStack
from wrs_agent.runtime import Runtime
from wrs_agent.schemas import GoalRequest, new_id

pytestmark = pytest.mark.zenoh
FIXTURE = Path(__file__).parents[1] / "fixtures/models/openai_chat_tool_call.json"
CONFIG = LLMConfig(model="fixture", base_url="https://model.invalid/v1")


@pytest.mark.parametrize("fault", [None, "grasp"])
async def test_verified_cache_hits_have_new_ids_and_failures_are_not_cached(fault):
    calls = []

    def reply(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200, content=FIXTURE.read_bytes())

    async with LocalStack(
        bindings="tests/fixtures/actions.toml", duration=0.03, fault=fault
    ) as stack:
        model = LLMClient(CONFIG, transport=httpx.MockTransport(reply))
        nodes = {
            "wrs": stack.system.clients["wrs"],
            "tts": stack.system.clients["tts"],
        }
        runtime = Runtime(nodes, load_bindings()[1], ModelPlanner(model))
        try:
            for _ in range(3):
                await runtime.goal(GoalRequest(request_id=new_id(), goal="put A in B"))
                await runtime.planning.worker
            if fault is None:
                assert runtime.execution.state == "SUCCEEDED"
                assert runtime.cache.last_hit and runtime.cache.hits == 1
                assert runtime.planner_calls == len(calls) == 2
                planning = runtime.snapshot()["last_planning"]
                assert planning["model_s"] is None and "output_tokens" not in planning
                history = runtime.snapshot()["action_history"]
                assert len(history) == len({a["action_id"] for a in history}) == 12
                assert (await stack.system.clients["wrs"].transport.request("request/health", {}))[
                    "executions"
                ] == 12
            else:
                assert runtime.execution.state == "FAILED"
                assert len(calls) == 3 and not runtime.cache.entries
                assert runtime.cache.hits == 0
        finally:
            await runtime.close()
            await model.aclose()
