"""Explicit bindings, Zenoh presence, and receiver-queried readiness."""

import asyncio
import re
import threading

import zenoh

from wrs_agent.errors import AgentError, error_info, from_exception
from wrs_agent.schemas import Empty, ErrorInfo, NodeInfo, new_id
from wrs_agent.skills import SKILLS, require_contract

# Nodes without an ActionExecutor still declare what they contribute.
INPUT_CAPABILITY = {
    "agent": "task.coordinate",
    "asr": "input.transcribe",
}


def register_node(bus, node_id, node_type, executor=None):
    boot_id = executor.boot_id if executor else new_id()
    bus.node_id = node_id
    if executor is not None:
        executor.node_id = node_id

    async def info(payload):
        Empty.model_validate(payload)
        cap = executor.capabilities() if executor else None
        ready = executor.admission == "OPEN" if executor else True
        return NodeInfo(
            node_id=node_id,
            node_type=node_type,
            boot_id=boot_id,
            ready=ready,
            health="ready" if ready else executor.admission.lower(),
            skills=cap.skills if cap else {},
            capabilities=sorted(
                {c for entry in executor.skills.values() for c in entry.spec.required_capabilities}
            )
            if cap
            else [INPUT_CAPABILITY.get(node_type, "interaction.replay")],
            resources=cap.resources if cap else [],
            error=None
            if ready
            else error_info("node_not_ready", node_id=node_id, stage="discovery"),
        ).model_dump()

    bus.register_handler(f"request/node/{node_id}", info)
    # This token is owned by the same session as the services, not a separate heartbeat.
    token = bus.session.liveliness().declare_token(bus.key(f"presence/{node_id}/{boot_id}"))
    bus.handles.append(token)
    return info


class NodeRegistry:
    def __init__(self, buses, definitions, bindings):
        self.buses, self.definitions, self.bindings = buses, definitions, bindings
        self.entries, self.local, self._caps = {}, {}, {}
        self._lock = threading.Lock()
        self._live = {name: set() for name in definitions}
        self._dirty = set()
        self._arrived = {name: asyncio.Event() for name in definitions}
        self._seen, self._initialized = set(), set()
        loop = asyncio.get_running_loop()
        for name, definition in definitions.items():
            if not definition["enabled"] or name not in buses:
                continue
            bus = buses[name]
            prefix = bus.key(f"presence/{name}") + "/"

            def changed(sample, name=name, prefix=prefix):
                key = str(sample.key_expr)
                boot = key.removeprefix(prefix)
                if not key.startswith(prefix) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", boot):
                    return
                present = sample.kind == zenoh.SampleKind.PUT
                with self._lock:
                    live = self._live[name]
                    # Bound malformed deployments too. Overflow requires a new view;
                    # never choose an arbitrary instance.
                    if live is not None:
                        live.add(boot) if present else live.discard(boot)
                        if len(live) > 16:
                            self._live[name] = None
                    if name not in self._seen:
                        self._seen.add(name)
                        loop.call_soon_threadsafe(self._arrived[name].set)
                    self._dirty.add(name)

            handle = bus.session.liveliness().declare_subscriber(
                prefix + "*", zenoh.handlers.Callback(changed, indirect=False), history=True
            )
            bus.handles.append(handle)

    def _presence(self):
        with self._lock:
            for name in self._dirty:
                self.entries.pop(name, None)
                self._caps.pop(name, None)
            self._dirty.clear()
            return {name: None if live is None else set(live) for name, live in self._live.items()}

    def check_instance(self, name, boot_id):
        live = self._presence().get(name)
        if live is None or len(live) > 1:
            raise AgentError("node_ambiguous", node_id=name, stage="discovery")
        if not live:
            raise AgentError("node_unavailable", node_id=name, stage="discovery")
        if not boot_id or live != {boot_id}:
            raise AgentError("node_instance_changed", node_id=name, stage="discovery")

    async def refresh(self, names=None):
        async def query(name):
            definition = self.definitions[name]
            if not definition["enabled"] or name not in self.buses:
                return
            if name not in self._initialized:
                # history=True asks Zenoh for existing tokens. Bound only the initial wait;
                # later absence/presence is driven by native events, never a local expiry.
                # Sessions opened one per suffix receive history in turn, the last most of a
                # second after connect, so a present node only costs its own arrival time.
                try:
                    async with asyncio.timeout(1.0):
                        await self._arrived[name].wait()
                except TimeoutError:
                    pass
                self._initialized.add(name)
            live = self._presence()[name]
            if live is None or len(live) != 1:
                return
            boot_id = next(iter(live))
            try:
                raw = (
                    await self.local[name]({})
                    if name in self.local
                    else await self.buses[name].request(f"request/node/{name}", {}, timeout=0.3)
                )
                info = NodeInfo.model_validate(raw)
                if (info.node_id, info.node_type, info.boot_id) != (
                    name,
                    definition["type"],
                    boot_id,
                ):
                    raise AgentError("node_identity_mismatch", node_id=name, stage="discovery")
                self.check_instance(name, boot_id)
            except (TimeoutError, ValueError, RuntimeError) as exc:
                info = NodeInfo(
                    node_id=name,
                    node_type=definition["type"],
                    boot_id=boot_id,
                    health="unknown",
                    error=from_exception(
                        exc, validation_code="invalid_reply", node_id=name, stage="discovery"
                    ),
                )
            self.entries[name] = info

        await asyncio.gather(*(query(n) for n in (self.definitions if names is None else names)))
        return self.snapshot()

    def snapshot(self):
        presence = self._presence()
        result = {}
        for name, definition in self.definitions.items():
            live = presence[name]
            info = NodeInfo(
                node_id=name,
                node_type=definition["type"],
                error=error_info("node_unavailable", node_id=name, stage="discovery"),
            )
            if not definition["enabled"]:
                info = info.model_copy(
                    update={
                        "health": "unsupported",
                        "error": error_info("provider_not_found", node_id=name, stage="discovery"),
                    }
                )
            elif live is None or len(live) > 1:
                info = info.model_copy(
                    update={
                        "health": "unknown",
                        "error": error_info("node_ambiguous", node_id=name, stage="discovery"),
                    }
                )
            elif live:
                boot_id = next(iter(live))
                cached = self.entries.get(name)
                info = (
                    cached
                    if cached and cached.boot_id == boot_id
                    else info.model_copy(
                        update={
                            "boot_id": boot_id,
                            "health": "unknown",
                            "error": error_info("node_not_ready", node_id=name, stage="discovery"),
                        }
                    )
                )
            result[name] = info.model_dump()
        return result

    async def capabilities(self, name, client):
        info = self._ready(name)
        boot_id = info["boot_id"]
        cached = self._caps.get(name)
        if cached is None or cached[0] != boot_id:
            cap = await client.capabilities()
            self.check_instance(name, boot_id)
            self._caps[name] = (boot_id, cap)
        return self._caps[name][1]

    def _ready(self, name):
        entry = self.snapshot().get(name)
        if entry is None:
            raise AgentError("provider_not_found", node_id=name, stage="discovery")
        if not entry["ready"]:
            error = entry.get("error")
            raise AgentError(
                ErrorInfo.model_validate(error)
                if error
                else error_info("node_not_ready", node_id=name, stage="discovery")
            )
        return entry

    def node_for(self, skill, version=None):
        if skill not in SKILLS:
            raise AgentError("unknown_skill", stage="discovery")
        name = self.bindings.get(skill)
        if name is None:
            raise AgentError("provider_not_found", stage="discovery")
        entry = self._ready(name)
        require_contract(
            skill,
            SKILLS[skill].spec.version if version is None else version,
            entry["skills"],
            node_id=name,
            stage="discovery",
        )
        if not set(SKILLS[skill].spec.required_capabilities).issubset(entry["capabilities"]):
            raise AgentError("unsupported_skill_on_current_node", node_id=name, stage="discovery")
        return name
