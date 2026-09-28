"""One node lifecycle. Subclasses initialize features; resources stay composed."""

import asyncio
import inspect
import os
import re
from contextlib import AsyncExitStack

from wrs_agent.instance_lock import InstanceLock
from wrs_agent.nodes.action_rpc import register_actions
from wrs_agent.registry import NodeRegistry, register_node
from wrs_agent.schemas import Empty
from wrs_agent.transport import Transport


class Node:
    """Construct without side effects, then run once through serve_node().

    Override setup() and optionally teardown(); neither requires a super() call.
    Register cleanup as each resource is acquired, including during partial setup.
    """

    node_type = "custom"
    options_type = Empty
    launch_options = {}  # Existing launch/CLI argument names, declared by each built-in node.
    features = ()
    action_service = False
    requires = ()

    def __init__(
        self, *, node_id=None, options=None, suffix=None, actions=None, peers=None,
        skill_bindings=None,
        endpoint="tcp/127.0.0.1:7447", site="local", env_id="arm01", journal=None,
    ):
        self.options = self.options_type.model_validate({} if options is None else options)
        self.node_id = node_id or self.node_type
        self.action_service = self.action_service if actions is None else actions
        if type(self.action_service) is not bool:
            raise ValueError("invalid_action_service")
        self.peers = dict(peers or {})
        self.skill_bindings = dict(skill_bindings or {})
        self.endpoint, self.site, self.env_id = endpoint, site, env_id
        self.target = env_id + ("-" + self.node_id if suffix is None else suffix)
        if env_id in {".", ".."} or not all(
            isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", value)
            for value in (
                site, env_id, self.target, self.node_id, *self.peers, *self.peers.values(),
            )
        ):
            raise ValueError("invalid_namespace")
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,40}", self.node_id):
            raise ValueError("invalid_node_id")
        self.journal = journal or f".local/state/{site}-{self.target}.sqlite3"
        self.transport = None
        self.executor = None
        self.registry = None
        self._connection_cleanup = AsyncExitStack()
        self._cleanup = AsyncExitStack()
        self._done = None
        self._info = None
        self._failure = None
        self._used = False

    async def setup(self):
        raise NotImplementedError("Implement setup() to register this node's features.")

    async def teardown(self):
        """Optional business cleanup; registered resources are closed afterwards."""

    def on_close(self, callback):
        """Own one synchronous or asynchronous cleanup callback, in reverse acquisition order."""
        if self._done is None:
            raise RuntimeError("node_not_running")

        async def close():
            result = callback()
            if inspect.isawaitable(result):
                await result

        self._cleanup.push_async_callback(close)

    def discover(self):
        """Own a directory view only when this node needs other nodes."""
        if self._done is None or self.transport is None:
            raise RuntimeError("node_not_running")
        if self.registry is None:
            self.registry = NodeRegistry(
                self.transport, env_id=self.env_id, bindings=self.skill_bindings,
            )
            self.on_close(self.registry.close)
        return self.registry

    def connect(self, node_id):
        """Reuse this node's session or a service already found by its directory."""
        if self._done is None:
            raise RuntimeError("node_not_running")
        if node_id == self.node_id:
            return self.transport
        return self.discover().transport(node_id)

    def actions(self, executor):
        """Own an executor and expose the existing Action protocol, regardless of node type."""
        if executor is self.executor:
            raise ValueError("one_executor_per_node")
        self.on_close(executor.close)
        if self.executor is not None:
            raise ValueError("one_executor_per_node")
        if not self.action_service:
            raise ValueError("actions_not_configured")
        if self.transport is None:
            raise RuntimeError("node_not_running")
        executor.node_id = self.node_id
        self.executor = executor
        register_actions(self.transport, executor)

    def add_skills(self, *skills):
        """Append local bindings through the same registration API used at startup."""
        if self._done is None or self.executor is None:
            raise RuntimeError("action_executor_not_registered")
        self.executor.add_skills(*skills)

    def spawn(self, coroutine):
        """Own a background coroutine; an unhandled failure stops the node visibly."""
        if self._done is None:
            coroutine.close()
            raise RuntimeError("node_not_running")
        task = asyncio.create_task(coroutine)

        def completed(task):
            if not task.cancelled() and (error := task.exception()) is not None:
                if self._failure is None:
                    self._failure = error
                self._done.set()

        async def close():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

        task.add_done_callback(completed)
        self.on_close(close)
        return task

    async def info(self, payload):
        """Local shortcut for Agent's registry; the network uses the same queried state."""
        return await self._info(payload)

    async def _serve(self):
        if self._used:
            raise RuntimeError("node_already_started")
        self._used = True
        self._done = asyncio.Event()
        scope = "action" if self.action_service else self.node_id
        try:
            async with AsyncExitStack() as cleanup:
                lock = InstanceLock(f"{self.site}-{self.target}-{scope}")
                cleanup.callback(lock.close)
                await cleanup.enter_async_context(self._connection_cleanup)
                await cleanup.enter_async_context(self._cleanup)
                self.transport = Transport(
                    self.endpoint, self.site, self.target,
                    os.environ.get("WRS_AGENT_TOKEN", ""), self.node_id,
                )
                self._connection_cleanup.push_async_callback(self.transport.close)
                try:
                    await self.setup()
                    if self.action_service and self.executor is None:
                        raise ValueError("action_executor_not_registered")
                    if self._failure is not None:
                        raise self._failure
                    self._info = register_node(
                        self.transport, self.node_id, self.node_type, self.executor,
                        features=self.features, env_id=self.env_id,
                    )

                    async def shutdown(payload):
                        Empty.model_validate(payload)
                        self._done.set()
                        return {"stopping": True}

                    self.transport.register_handler(
                        f"request/node/{self.node_id}/shutdown", shutdown, control=True,
                    )
                    print(f"ready {self.node_type} {self.target}", flush=True)
                    await self._done.wait()
                    if self._failure is not None:
                        raise self._failure
                finally:
                    await self.teardown()
        finally:
            self._done = None
            self.transport = None
