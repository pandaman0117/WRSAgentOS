"""Node ownership and failure handling, without devices, model APIs, or Zenoh threads."""

import asyncio
import sys
import threading
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from conftest import eventually

from wrs_agent.nodes import Node
from wrs_agent.nodes.asr import AsrNode
from wrs_agent.nodes.tts import TtsNode
from wrs_agent.nodes.tts.backend import make_mock_tts
from wrs_agent.nodes.voice import VoiceNode
from wrs_agent.processes import LocalStack


@pytest.fixture
def io(monkeypatch):
    events, buses = [], []

    class Lock:
        def __init__(self, name):
            events.append("lock")
        def close(self):
            events.append("unlock")

    class Bus:
        def __init__(self, endpoint, site, target, token, source):
            self.target = self.env_id = target
            self.site = site
            self.handlers = {}
            self.handles = []
            self.session = self
            buses.append(self)
            events.append("connect")

        def register_handler(self, name, handler, *, control=False):
            self.handlers[name] = handler

        def key(self, name):
            return f"unit/{self.target}/{name}"

        def liveliness(self):
            return self

        def declare_token(self, key):
            events.append("presence")
            return SimpleNamespace(undeclare=lambda: events.append("unpublish"))

        def publish(self, *args):
            return None

        async def close(self):
            for handle in self.handles:
                handle.undeclare()
            events.append("disconnect")

    monkeypatch.setattr("wrs_agent.nodes.node.InstanceLock", Lock)
    monkeypatch.setattr("wrs_agent.nodes.node.Transport", Bus)
    return SimpleNamespace(events=events, buses=buses)


def test_construction_does_not_connect_acquire_lock_or_load_backend(io, tmp_path):
    journal = tmp_path / "not-created.sqlite3"
    node = TtsNode(
        node_id="speaker", actions=True,
        options={"backend": "qwen"}, journal=journal,
    )
    assert node.options.backend == "qwen"
    assert io.events == [] and not journal.exists()


async def test_partial_setup_closes_acquired_resources_without_announcing_ready(io):
    class Broken(Node):
        async def setup(self):
            self.on_close(lambda: io.events.append("first"))
            async def last():
                io.events.append("last")
            self.on_close(last)
            raise ValueError("setup_failed")

        async def teardown(self):
            io.events.append("teardown")

    with pytest.raises(ValueError, match="setup_failed"):
        await Broken(node_id="speaker")._serve()
    assert io.events == ["lock", "connect", "teardown", "last", "first", "disconnect", "unlock"]
    assert not io.buses[0].handlers


async def test_cleanup_failure_does_not_skip_other_resources_or_connection(io):
    class BrokenCleanup(Node):
        async def setup(self):
            self.on_close(lambda: io.events.append("first"))
            async def fail():
                io.events.append("failed-close")
                raise ValueError("cleanup_failed")
            self.on_close(fail)
            self.on_close(lambda: io.events.append("last"))
            self._done.set()

        async def teardown(self):
            io.events.append("teardown")

    with pytest.raises(ValueError, match="cleanup_failed"):
        await BrokenCleanup(node_id="speaker")._serve()
    assert io.events[-7:] == [
        "teardown", "last", "failed-close", "first", "unpublish", "disconnect", "unlock",
    ]


async def test_setup_finishes_before_presence_and_shutdown_registration(io):
    entered, release = asyncio.Event(), asyncio.Event()
    class Slow(Node):
        features = ("input.test",)
        async def setup(self):
            entered.set()
            await release.wait()

    node = Slow(node_id="speaker")
    serving = asyncio.create_task(node._serve())
    try:
        await entered.wait()
        assert "presence" not in io.events and not io.buses[0].handlers
        release.set()
        await eventually(lambda: node._info, bool)
        info = await node.info({})
        assert info["node_type"] == "custom" and info["features"] == ["input.test"]
        assert info["ready"]
        result = await io.buses[0].handlers["request/node/speaker/shutdown"]({})
        assert result == {"stopping": True}
        await serving
    finally:
        release.set()
        serving.cancel()
        await asyncio.gather(serving, return_exceptions=True)


async def test_held_executor_is_initialized_but_does_not_grant_actions(io, tmp_path):
    class Speaker(Node):
        async def setup(self):
            executor = make_mock_tts(tmp_path / "speech.sqlite3")
            executor.admission = "HELD"
            self.actions(executor)

    node = Speaker(node_id="speaker", actions=True)
    serving = asyncio.create_task(node._serve())
    try:
        await eventually(lambda: node._info, bool)
        info = await node.info({})
        assert info["boot_id"] == node.executor.boot_id
        assert not info["ready"] and info["health"] == "held"
        assert info["skills"] == {"speak": 1}
        assert node.executor.node_id == "speaker"
        await io.buses[0].handlers["request/node/speaker/shutdown"]({})
        await serving
    finally:
        serving.cancel()
        await asyncio.gather(serving, return_exceptions=True)


async def test_action_registration_cannot_override_deployment_permission(io):
    closed = []
    class Unpermitted(Node):
        async def setup(self):
            async def close():
                closed.append(True)
            self.actions(SimpleNamespace(close=close))

    with pytest.raises(ValueError, match="actions_not_configured"):
        await Unpermitted(node_id="speaker")._serve()
    assert closed == [True] and "presence" not in io.events


async def test_cancelled_startup_still_releases_resources(io):
    entered = asyncio.Event()
    class Waiting(Node):
        async def setup(self):
            self.on_close(lambda: io.events.append("released"))
            entered.set()
            await asyncio.Event().wait()

    serving = asyncio.create_task(Waiting(node_id="speaker")._serve())
    await entered.wait()
    serving.cancel()
    with pytest.raises(asyncio.CancelledError):
        await serving
    assert io.events[-3:] == ["released", "disconnect", "unlock"]
    assert "presence" not in io.events


async def test_background_failure_is_reported_and_other_worker_is_joined(io):
    waiting = asyncio.Event()
    async def worker():
        try:
            waiting.set()
            await asyncio.Event().wait()
        finally:
            io.events.append("worker-closed")

    class Workers(Node):
        async def setup(self):
            self.spawn(worker())
            async def fail():
                await waiting.wait()
                raise LookupError("worker_failed")
            self.spawn(fail())

    with pytest.raises(LookupError, match="worker_failed"):
        async with asyncio.timeout(1):
            await Workers(node_id="speaker")._serve()
    assert "worker-closed" in io.events
    assert io.events[-2:] == ["disconnect", "unlock"]


@pytest.mark.parametrize("fail", [False, True])
@pytest.mark.parametrize("model_loader", [False, True])
async def test_launcher_starts_all_nodes_and_joins_concurrent_readiness(
    monkeypatch, tmp_path, fail, model_loader,
):
    stack = (
        LocalStack(tts_backend="qwen", tts_python=sys.executable) if model_loader else LocalStack()
    )
    stack.directory = tmp_path / "run"
    stack.endpoint = "tcp/127.0.0.1:12345"
    spawned, probes, cancelled, shutdowns = [], [], [], []
    everyone = asyncio.Event()

    async def request(key, payload, **kwargs):
        shutdowns.append(key)
        return {"stopping": True}

    buses = {name: SimpleNamespace(request=request) for name in stack.roles.values()}
    async def nodes():
        return []

    system = SimpleNamespace(registry=SimpleNamespace(transport=buses.__getitem__), nodes=nodes)

    @asynccontextmanager
    async def connect(*args, **kwargs):
        yield system
        shutdowns.append("connection-closed")

    async def probe(node_id, **kwargs):
        assert kwargs["seconds"] == (300 if model_loader else 10)
        assert set(spawned) == set(stack.roles)
        probes.append(node_id)
        if len(probes) == len(stack.roles):
            everyone.set()
        await everyone.wait()
        if fail:
            if node_id == "wrs":
                raise RuntimeError("startup_failed")
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.append(node_id)
        return node_id

    monkeypatch.setattr("wrs_agent.processes.System.connect", connect)
    monkeypatch.setattr(stack, "start_router", lambda: None)
    monkeypatch.setattr(stack, "_spawn", lambda role, command: spawned.append(role))
    monkeypatch.setattr(stack, "_wait_ready", probe)
    monkeypatch.setattr(stack, "_reap", lambda: shutdowns.append("reaped"))

    async with asyncio.timeout(1):
        if fail:
            with pytest.raises(ExceptionGroup, match="TaskGroup"):
                await stack.__aenter__()
            assert len(cancelled) == len(stack.roles) - 1
        else:
            async with stack:
                assert everyone.is_set() and stack.system is system
    assert {f"request/node/{name}/shutdown" for name in stack.roles.values()}.issubset(shutdowns)
    assert shutdowns[-2:] == ["connection-closed", "reaped"]


async def test_teardown_failure_still_cleans_resources_and_closes_node(io):
    class BrokenTeardown(Node):
        async def setup(self):
            self.on_close(lambda: io.events.append("released"))
            self._done.set()

        async def teardown(self):
            raise LookupError("teardown_failed")

    node = BrokenTeardown(node_id="speaker")
    with pytest.raises(LookupError, match="teardown_failed"):
        await node._serve()
    assert io.events[-4:] == ["released", "unpublish", "disconnect", "unlock"]
    with pytest.raises(RuntimeError, match="node_not_running"):
        node.connect("speaker")
    with pytest.raises(RuntimeError, match="node_already_started"):
        await node._serve()


@pytest.mark.parametrize("cancelled", [False, True])
async def test_asr_node_exit_waits_for_capture_thread_before_closing_connections(io, cancelled):
    entered, stopping, release, finished = (threading.Event() for _ in range(4))

    class CaptureNode(AsrNode):
        async def create_capture(self):
            def capture(held):
                entered.set()
                while held():
                    if release.wait(0.005):
                        break
                stopping.set()
                assert release.wait(3)
                finished.set()
                return "停止"
            return capture

    forwarded = []

    async def record_request(*args, **kwargs):
        forwarded.append((args, kwargs))
        return {}

    async def wait_for(node_id=None, **kwargs):
        return node_id or "voice"

    node = CaptureNode(peers={"voice": "voice"})
    node.discover = lambda: SimpleNamespace(wait_for=wait_for)
    node.connect = lambda node_id: SimpleNamespace()
    serving = asyncio.create_task(node._serve())
    try:
        await eventually(lambda: node._info, bool)
        node.voice.request = record_request
        await node.transport.handlers["request/asr/begin"]({"press_id": "held"})
        await eventually(entered.is_set, bool)
        if cancelled:
            serving.cancel()
        else:
            await node.transport.handlers["request/node/asr/shutdown"]({})
        await eventually(stopping.is_set, bool)
        assert not serving.done() and not finished.is_set()
        assert "disconnect" not in io.events
        release.set()
        if cancelled:
            with pytest.raises(asyncio.CancelledError):
                await serving
        else:
            await serving
        assert finished.is_set() and node.transport is None
        assert io.events[-1] == "unlock"
        # An unreleased utterance is discarded on node exit, never routed as a command.
        assert not node._results and not forwarded
    finally:
        release.set()
        if not serving.done():
            serving.cancel()
        await asyncio.gather(serving, return_exceptions=True)


@pytest.mark.parametrize("node_class", [VoiceNode, AsrNode])
async def test_cancelled_dependency_wait_releases_directory_and_connection(
    io, monkeypatch, node_class,
):
    entered, cancelled = asyncio.Event(), set()

    class Directory:
        def __init__(self, *args, **kwargs):
            pass

        async def wait_for(self, node_id=None, *, role=None, timeout=10):  # noqa: ASYNC109
            assert timeout is None
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.add(role)

        async def close(self):
            io.events.append("directory-closed")

    monkeypatch.setattr("wrs_agent.nodes.node.NodeRegistry", Directory)
    node = node_class()
    serving = asyncio.create_task(node._serve())
    await entered.wait()
    serving.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(serving, 1)
    assert cancelled == set(node.requires)
    assert "presence" not in io.events
    assert io.events[-3:] == ["directory-closed", "disconnect", "unlock"]


async def test_voice_keeps_verified_peers_while_another_dependency_initializes(monkeypatch):
    from wrs_agent.nodes.voice import VoiceNode

    node = VoiceNode()
    node.transport = SimpleNamespace(register_handler=lambda *args, **kwargs: None)
    channels = {role: object() for role in node.requires}
    found_robot = asyncio.Event()
    stale = set()

    async def wait_for(node_id, *, role, timeout):  # noqa: ASYNC109 - directory fixture
        if role == "tts":
            await found_robot.wait()
            stale.add("wrs")  # A later ordinary description query timed out.
        elif role == "wrs":
            found_robot.set()
        return role

    def connect(node_id):
        if node_id in stale:
            raise TimeoutError("description_expired_during_startup")
        return channels[node_id]

    monkeypatch.setattr(node, "discover", lambda: SimpleNamespace(wait_for=wait_for))
    monkeypatch.setattr(node, "connect", connect)
    await node.setup()
    assert node.wrs.transport is channels["wrs"]
    assert node.tts.transport is channels["tts"]
    assert node.agent_bus is channels["agent"]
