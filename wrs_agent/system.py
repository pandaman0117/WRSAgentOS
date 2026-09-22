"""Small local user API. Every call still crosses the existing Zenoh boundary."""

import asyncio
import os
from contextlib import AsyncExitStack, asynccontextmanager

from wrs_agent.bindings import load_bindings
from wrs_agent.errors import AgentError
from wrs_agent.handles import GoalHandle, TaskHandle
from wrs_agent.nodes.actions import ActionClient
from wrs_agent.policy import text_intent
from wrs_agent.registry import NodeRegistry
from wrs_agent.schemas import (
    AsrPress,
    AsrResult,
    ControlRequest,
    Interaction,
    Plan,
    Step,
    TextInput,
    TextReceipt,
    new_id,
)
from wrs_agent.skills import SKILLS, lookup_skills
from wrs_agent.transport import Transport


def step(skill, *, after=(), **args):
    """Steps without dependencies may run concurrently on different resources."""
    dependencies = [after] if isinstance(after, Step) else list(after)
    return Step(
        step_id=new_id(),
        skill=skill,
        version=SKILLS[skill].spec.version if skill in SKILLS else 1,
        args=args,
        depends_on=[item.step_id for item in dependencies],
    )


class System:
    """A connection to configured nodes; launch() additionally owns local processes."""

    def __init__(self, transports, definitions, bindings, *, endpoint, site, env_id):
        self.endpoint, self.site, self.env_id = endpoint, site, env_id
        self.definitions = definitions
        self.bindings = bindings
        self._transports = transports
        self._local_stack = None  # Only for local process diagnostics, never needed to connect.
        self.roles = {}
        for name, definition in definitions.items():
            if definition["enabled"]:
                role = definition["type"]
                if role in self.roles:
                    raise ValueError("one_node_per_role_in_v1")
                self.roles[role] = name
        self.registry = NodeRegistry(transports, definitions, bindings)
        self.clients = {
            name: ActionClient(bus, node_id=name)
            for name, bus in transports.items()
            if definitions[name]["actions"]
        }

    def _role(self, role):
        if role not in self.roles:
            raise ValueError(f"node_role_not_configured: {role}")
        return self.roles[role]

    @property
    def agent(self):
        return self._transports[self._role("agent")]

    @classmethod
    @asynccontextmanager
    async def connect(
        cls,
        endpoint="tcp/127.0.0.1:7447",
        *,
        site="local",
        env_id="arm01",
        bindings=None,
        _token=None,
        _config=None,
    ):
        """Connect without starting/stopping nodes; credentials come from WRS_AGENT_TOKEN.

        _token/_config are the launcher's already-resolved session, not a second user config.
        Online/readiness checks happen when nodes/skills/actions are queried.
        """
        definitions, skill_bindings = _config if _config is not None else load_bindings(bindings)
        definitions = {name: dict(node) for name, node in definitions.items()}
        skill_bindings = dict(skill_bindings)
        token = os.environ.get("WRS_AGENT_TOKEN", "") if _token is None else _token
        if not 16 <= len(token) <= 128:
            raise ValueError(
                "Set WRS_AGENT_TOKEN in this terminal or IDE run configuration to the same "
                "session credential used by the running nodes (16 to 128 characters). "
                "See examples/README.md for connect/nodes setup; .env is not loaded automatically."
            )
        async with AsyncExitStack() as cleanup:
            transports, by_suffix = {}, {}
            for name, definition in definitions.items():
                if not definition["enabled"]:
                    continue
                suffix = definition["suffix"]
                if suffix not in by_suffix:
                    bus = Transport(endpoint, site, env_id + suffix, token, "input")
                    cleanup.push_async_callback(bus.close)
                    by_suffix[suffix] = bus
                transports[name] = by_suffix[suffix]
            yield cls(
                transports, definitions, skill_bindings, endpoint=endpoint, site=site, env_id=env_id
            )

    @classmethod
    @asynccontextmanager
    async def launch(
        cls, *, backend="mock", duration=0.4, bindings=None, scene=None,
        port=0, site="local", env_id=None,
        tts_backend="mock", tts_python=None, tts_prepared_texts=(),
        asr_backend="mock", asr_python=None, asr_script=(), asr_vocabulary=(),
    ):
        from wrs_agent.processes import LocalStack

        async with LocalStack(
            backend=backend,
            scene=scene,
            tts_backend=tts_backend,
            tts_python=tts_python,
            tts_prepared_texts=tts_prepared_texts,
            asr_backend=asr_backend,
            asr_python=asr_python,
            asr_script=asr_script,
            asr_vocabulary=asr_vocabulary,
            duration=duration,
            bindings=bindings,
            port=port,
            site=site,
            env_id=env_id,
        ) as stack:
            yield stack.system

    async def nodes(self):
        """Fresh node observations, queried directly, even if Agent is unavailable."""
        return await self.registry.refresh()

    async def skills(self):
        """Skills available on ready nodes; this does not invoke Planner."""
        online = await self.nodes()
        names = [name for name in self.clients if online.get(name, {}).get("ready")]
        caps = await asyncio.gather(
            *(self.registry.capabilities(name, self.clients[name]) for name in names)
        )
        return lookup_skills(dict(zip(names, caps, strict=True)), self.bindings)

    def task(self, task_id):
        """Reconnect to a task identity; status() reports task_not_found for unknown IDs."""
        return TaskHandle(self, task_id)

    async def start(self, *steps):
        """Accept an explicit plan and return its immutable execution identity."""
        result = await self.agent.request(
            "request/task/start",
            {"request_id": new_id(), "plan": Plan(steps=list(steps)).model_dump()},
        )
        return self.task(result["task_id"])

    def planning(self, request_id):
        """Attach to a planning request, including one accepted through Voice."""
        return GoalHandle(self, request_id)

    async def send_text(self, text, *, input_id=None, is_final=True, confidence=1.0):
        """Submit recognized text. ASR/UI adapters own capture and call this off their callback."""
        event = TextInput(
            input_id=input_id if input_id is not None else new_id(),
            text=text,
            is_final=is_final,
            confidence=confidence,
        )
        control = text_intent(event)[0] in {"stop", "cancel_tts"}
        raw = await self._transports[self._role("voice")].request(
            "request/voice/control_text" if control else "request/voice/text",
            event.model_dump(),
            control=control,
            timeout=5.0,
        )
        return TextReceipt.model_validate(raw)

    async def listen_begin(self, press_id=None):
        """Start one push-to-talk capture. The UI owns press and release, never a timer."""
        press = AsrPress() if press_id is None else AsrPress(press_id=press_id)
        raw = await self._transports[self._role("asr")].request(
            "request/asr/begin", press.model_dump(), control=True
        )
        return AsrResult.model_validate(raw)

    async def listen_end(self, press_id):
        """Release the button. Recognition and routing to Voice continue on the ASR node."""
        raw = await self._transports[self._role("asr")].request(
            "request/asr/end", AsrPress(press_id=press_id).model_dump(), control=True
        )
        return AsrResult.model_validate(raw)

    async def listen_result(self, press_id):
        """Poll one capture; the transcript goes only to the caller that held the button."""
        raw = await self._transports[self._role("asr")].request(
            "request/asr/result", AsrPress(press_id=press_id).model_dump()
        )
        return AsrResult.model_validate(raw)

    async def goal(self, text):
        request_id = new_id()
        await self.agent.request("request/task/goal", {"request_id": request_id, "goal": text})
        return GoalHandle(self, request_id)

    async def status(self):
        """Runtime overview; use task(id).status() to query a particular execution."""
        return await self.agent.request("request/task/status", {})

    async def action(self, skill, **args):
        """Explicit direct action; choose provider from configuration, never from model text."""
        if skill not in SKILLS:
            raise AgentError("unknown_skill", stage="discovery")
        if skill not in self.bindings:
            raise AgentError("provider_not_found", stage="discovery")
        name = self.bindings[skill]
        await self.registry.refresh([name])
        client = self.clients[self.registry.node_for(skill)]
        context = await client.context()
        self.registry.check_instance(name, context.boot_id)
        return await client.submit(
            skill, args, context=context, task_id=new_id(), version=SKILLS[skill].spec.version
        )

    async def snapshot(self, node=None):
        """Read one action node directly; defaults to the robot, never aggregates nodes."""
        node = node or self._role("wrs")
        if node not in self.clients:
            raise ValueError("node_snapshot_unsupported")
        return await self.clients[node].snapshot()

    async def allow_actions(self, node=None):
        """Allow new robot actions after confirmed stop; never continue an old action."""
        node = node or self._role("wrs")
        if self.definitions.get(node, {}).get("type") != "wrs" or node not in self.clients:
            raise ValueError("robot_allow_actions_unsupported")
        client = self.clients[node]
        state = await client.snapshot(control=True)
        return await client.control(
            "allow_actions",
            ControlRequest(
                interrupt_id=new_id(),
                boot_id=state.boot_id,
                control_epoch=state.control_epoch,
                state_version=state.state_version,
            ),
        )

    async def replay(self, kind):
        """Replay a verified intent through Voice, not ASR or a language classifier."""
        event = Interaction(event_id=new_id(), kind=kind)
        control = kind in {"stop", "barge_in"}
        return await self._transports[self._role("voice")].request(
            "request/voice/control" if control else "request/voice/event",
            event.model_dump(),
            control=control,
        )
