"""Run one explicitly configured node; shared by Python programs and the CLI."""

import asyncio
import inspect
import os

from wrs_agent.bindings import load_bindings
from wrs_agent.env.mock import make_mock_environment
from wrs_agent.nodes.actions import ActionClient, register_actions
from wrs_agent.nodes.agent import register_runtime
from wrs_agent.nodes.tts import make_mock_tts
from wrs_agent.nodes.voice import register_voice
from wrs_agent.planner import ModelPlanner
from wrs_agent.planner.providers.mock import MockClient
from wrs_agent.processes import InstanceLock
from wrs_agent.registry import NodeRegistry, register_node
from wrs_agent.runtime import Runtime
from wrs_agent.schemas import Empty
from wrs_agent.transport import Transport


async def serve_node(
    role,
    *,
    node_id=None,
    bindings=None,
    endpoint="tcp/127.0.0.1:7447",
    site="local",
    env_id="arm01",
    journal=None,
    duration=0.4,
    backend="mock",
    scene=None,
    model_provider="mock",
    live_model=False,
    deferred_planner=False,
    fault=None,
    action_factory=None,
    tts_backend="mock",
    tts_prepared_texts=(),
):
    """Serve until shutdown; a local action_factory receives only its journal path."""
    if role not in {"wrs", "tts", "agent", "voice"}:
        raise ValueError("unsupported_node_role")
    if action_factory is not None and role not in {"wrs", "tts"}:
        raise ValueError("action_factory_requires_action_node")
    if tts_backend not in {"mock", "qwen"}:
        raise ValueError("unsupported_tts_backend")
    if backend not in {"mock", "wrs"}:
        raise ValueError("unsupported_backend")
    if model_provider not in {"mock", "glm"} or (
        model_provider == "glm" and (not live_model or deferred_planner)
    ):
        raise ValueError("invalid_model_provider_or_missing_live_opt_in")
    if not 0 < duration <= 30:
        raise ValueError("invalid_duration")
    if scene is not None and (role != "wrs" or backend != "wrs" or action_factory is not None):
        raise ValueError("scene_requires_wrs_backend")
    definitions, skill_bindings = load_bindings(bindings)
    node_id = node_id or role
    definition = definitions.get(node_id)
    if not definition or definition["type"] != role or not definition["enabled"]:
        raise ValueError("node_not_configured")
    target = env_id + definition["suffix"]
    scope = "action" if role in {"wrs", "tts"} else role
    lock = InstanceLock(f"{site}-{target}-{scope}")
    journal = journal or f".local/state/{site}-{target}.sqlite3"
    buses = []
    owner = None
    model = None
    close_voice = None
    done = asyncio.Event()
    try:

        def connect(target_id):
            bus = Transport(
                endpoint,
                site,
                target_id,
                os.environ.get("WRS_AGENT_TOKEN", ""),
                role,
            )
            buses.append(bus)
            return bus

        transport = connect(target)
        if role in {"wrs", "tts"}:
            if action_factory is not None:
                owner = action_factory(journal)
                if inspect.isawaitable(owner):
                    owner = await owner
            elif role == "wrs" and backend == "wrs":
                from wrs_agent.env.wrs import make_wrs_environment

                owner = await make_wrs_environment(journal, duration=duration, scene=scene)
            elif role == "wrs":
                owner = make_mock_environment(journal, duration=duration, fault=fault)
            elif tts_backend == "qwen":
                from wrs_agent.speech.tts import make_qwen_tts

                owner = await make_qwen_tts(journal, prepared_texts=tts_prepared_texts)
            else:
                owner = make_mock_tts(journal, duration=duration)
            register_actions(transport, owner)
        elif role == "agent":
            if model_provider == "glm":
                from wrs_agent.planner.providers.glm import GLMClient, GLMConfig

                model = GLMClient(GLMConfig.from_env(), live_model=live_model)
            else:
                model = MockClient(deferred=deferred_planner)
            registry = NodeRegistry(
                {
                    name: connect(env_id + d["suffix"])
                    for name, d in definitions.items()
                    if d["enabled"]
                },
                definitions,
                skill_bindings,
            )
            clients = {
                name: ActionClient(bus, node_id=name)
                for name, bus in registry.buses.items()
                if definitions[name]["actions"]
            }
            owner = Runtime(
                clients,
                skill_bindings,
                planner=ModelPlanner(model),
                registry=registry,
            )
            register_runtime(transport, owner)
            if deferred_planner:

                async def release(payload):
                    Empty.model_validate(payload)
                    model.gate.set()
                    return {"released": True, "provider": "mock"}

                transport.register_handler("request/test/planner/release", release, control=True)
        else:

            def role_bus(required_role):
                matches = [
                    d for d in definitions.values() if d["type"] == required_role and d["enabled"]
                ]
                if len(matches) != 1:
                    raise ValueError("voice_requires_one_node_per_role")
                return connect(env_id + matches[0]["suffix"])

            close_voice = register_voice(
                transport,
                ActionClient(role_bus("wrs")),
                ActionClient(role_bus("tts")),
                role_bus("agent"),
            )

        info = register_node(
            transport,
            node_id,
            role,
            owner if role in {"wrs", "tts"} else None,
        )

        if role == "agent":
            owner.registry.local[node_id] = info

        async def shutdown(payload):
            Empty.model_validate(payload)
            done.set()
            return {"stopping": True}

        transport.register_handler(f"request/{role}/shutdown", shutdown, control=True)
        print(f"ready {role} {target}", flush=True)
        await done.wait()
    finally:
        try:
            if close_voice:
                await close_voice()
            if owner:
                await owner.close()
            if model:
                await model.aclose()
        finally:
            for bus in buses:
                await bus.close()
            lock.close()
