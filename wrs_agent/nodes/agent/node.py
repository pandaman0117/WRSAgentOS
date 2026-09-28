"""Agent node: own the model and Runtime, bind their existing RPC contract."""

from wrs_agent.nodes.agent.rpc import register_runtime
from wrs_agent.nodes.node import Node
from wrs_agent.planner import ModelPlanner
from wrs_agent.runtime import Runtime
from wrs_agent.schemas import Boundary


class AgentOptions(Boundary):
    live_model: bool = False


class AgentNode(Node):
    node_type = "agent"
    launch_options = {"live_model": "live_model"}
    options_type = AgentOptions
    features = ("task.coordinate",)

    async def setup(self):
        planner = None
        if self.options.live_model:
            from wrs_agent.planner.providers.llm import LLMClient, LLMConfig

            model = LLMClient(LLMConfig.from_env(), live_model=True)
            self.on_close(model.aclose)
            planner = ModelPlanner(model)

        registry = self.discover()
        registry.local[self.node_id] = self.info
        runtime = Runtime(
            registry.clients,
            self.skill_bindings,
            planner=planner,
            registry=registry,
        )
        self.on_close(runtime.close)
        register_runtime(self.transport, runtime)
