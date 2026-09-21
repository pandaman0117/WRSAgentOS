"""Launch only owned processes; readiness uses TCP and authenticated RPC probes."""

import asyncio
import contextlib
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from wrs_agent.bindings import load_bindings
from wrs_agent.schemas import new_id
from wrs_agent.system import System

ROOT = Path(__file__).resolve().parents[1]
ROUTER_VERSION = "1.9.0"
ROUTER = ROOT / f".local/zenoh-{ROUTER_VERSION}" / (
    "zenohd.exe" if os.name == "nt" else "zenohd"
)
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class InstanceLock:
    def __init__(self, name):
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,200}", name):
            raise ValueError("invalid_instance_name")
        path = Path(tempfile.gettempdir()) / "wrs-agent-locks" / f"{name}.lock"
        path.parent.mkdir(parents=True, exist_ok=True)
        self.file = path.open("a+b")
        if path.stat().st_size == 0:
            self.file.write(b"0")
            self.file.flush()
        self.file.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.file.close()
            raise RuntimeError("node_already_running") from None

    def close(self):
        self.file.close()


def python_command(*args):
    """Use the caller's Python; preserve an explicitly isolated development launch."""
    command = [sys.executable, "-X", "utf8"]
    if sys.flags.no_site:
        command.extend(["-S", str(ROOT / "scripts/run.py")])
    return [*command, *map(str, args)]


def router_path():
    """Resolve an explicit override, the local pinned binary, or zenohd on PATH."""
    configured = os.environ.get("WRS_AGENT_ZENOHD")
    if configured is not None:
        path = Path(configured).expanduser().resolve()
        if not configured or not path.is_file():
            raise FileNotFoundError(f"WRS_AGENT_ZENOHD is not a file: {configured!r}")
        return path
    if ROUTER.is_file():
        return ROUTER
    found = shutil.which("zenohd")
    if found:
        return Path(found).resolve()
    raise FileNotFoundError(
        f"zenohd {ROUTER_VERSION} not found. Set WRS_AGENT_ZENOHD to its executable, "
        f"install it at {ROUTER}, or add it to PATH."
    )


def check_router_version(router=None):
    router = router_path() if router is None else Path(router)
    output = subprocess.check_output(
        [str(router), "--version"], timeout=5, creationflags=NO_WINDOW
    ).decode("utf-8", errors="replace")
    # RUST_LOG=info/debug adds a timestamped log before the standalone version line.
    match = re.search(r"(?m)^zenohd v?(\S+)", output)
    if match is None or match.group(1) != ROUTER_VERSION:
        raise RuntimeError(
            f"zenohd_version_mismatch: expected {ROUTER_VERSION}; "
            f"router={router}; output={output.strip()!r}"
        )


class LocalStack:
    def __init__(
        self,
        *,
        duration=0.4,
        fault=None,
        port=0,
        site="local",
        env_id=None,
        deferred=False,
        backend="mock",
        model_provider="mock",
        live_model=False,
        bindings=None,
        scene=None,
        tts_backend="mock",
        tts_python=None,
        tts_prepared_texts=(),
    ):
        if backend not in {"mock", "wrs"}:
            raise ValueError("unsupported_backend")
        if model_provider not in {"mock", "glm"} or (model_provider == "glm" and not live_model):
            raise ValueError("invalid_model_provider_or_missing_live_opt_in")
        if tts_backend not in {"mock", "qwen"}:
            raise ValueError("unsupported_tts_backend")
        self.tts_backend = tts_backend
        self.tts_prepared_texts = tuple(tts_prepared_texts)
        self.tts_python = Path(tts_python).resolve() if tts_python else None
        if tts_backend == "qwen" and self.tts_python is None:
            relative = "Scripts/python.exe" if os.name == "nt" else "bin/python"
            self.tts_python = ROOT / ".local/venvs/qwen-tts" / relative
        if self.tts_python is not None and not self.tts_python.is_file():
            raise FileNotFoundError("Run scripts/setup_speech.ps1 first: " + str(self.tts_python))
        self.model_provider, self.live_model = model_provider, live_model
        self.backend = backend
        self.scene_path = Path(scene).resolve() if scene is not None else None
        if self.scene_path is not None:
            if backend != "wrs":
                raise ValueError("scene_requires_wrs_backend")
            from wrs_agent.scene import load_scene

            load_scene(self.scene_path)  # Fail before spawning processes.
        self.duration, self.fault, self.deferred = duration, fault, deferred
        self.system = None
        self._connection = None
        self.started = []
        self.bindings_path = Path(bindings).resolve() if bindings else None
        self.definitions, self.skill_bindings = load_bindings(self.bindings_path)
        self.roles = {}
        for name, definition in self.definitions.items():
            if definition["enabled"]:
                role = definition["type"]
                if role in self.roles:
                    raise ValueError("one_node_per_role_in_local_profile")
                self.roles[role] = name
        if self.scene_path is not None and "wrs" not in self.roles:
            raise ValueError("scene_requires_wrs_node")
        if any(role not in {"wrs", "tts", "agent", "voice"} for role in self.roles):
            raise ValueError("node_type_not_implemented")
        if "voice" in self.roles and not {"wrs", "tts", "agent"}.issubset(self.roles):
            raise ValueError("voice_requires_wrs_tts_agent")
        self.port, self.site = port, site
        self.env_id = env_id or backend + "-" + new_id()[:12]
        if not all(
            re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", value)
            for value in (
                site,
                self.env_id,
                *(self.env_id + d["suffix"] for d in self.definitions.values()),
            )
        ) or self.env_id in {".", ".."}:
            raise ValueError("invalid_namespace")
        self.token = os.environ.get("WRS_AGENT_TOKEN") or secrets.token_urlsafe(32)
        if not 16 <= len(self.token) <= 128:
            raise ValueError("WRS_AGENT_TOKEN must contain 16 to 128 characters")
        self.processes = []
        self.logs = []
        self.directory = ROOT / ".local/runs" / self.env_id

    def _spawn(self, name, command):
        log = (self.directory / f"{name}.log").open("wb")
        self.logs.append(log)
        env = os.environ.copy()
        env["WRS_AGENT_TOKEN"] = self.token
        process = subprocess.Popen(
            command,
            cwd=ROOT,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=NO_WINDOW,
        )
        self.processes.append(process)
        return process

    def start_router(self):
        # Refuse occupied ports; never attach to an unknown existing service.
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", self.port))
            self.port = probe.getsockname()[1]
        self.endpoint = f"tcp/127.0.0.1:{self.port}"
        config = {
            "mode": "router",
            "listen": {"endpoints": [self.endpoint]},
            "scouting": {"multicast": {"enabled": False}, "gossip": {"enabled": False}},
            "adminspace": {"enabled": False},
            "plugins_loading": {"enabled": False},
        }
        config_path = self.directory / "router.json5"
        config_path.write_text(json.dumps(config), encoding="utf-8")
        router = router_path()
        check_router_version(router)
        process = self._spawn("router", [str(router), "-c", str(config_path)])
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(f"Router exited; see {self.directory}")
            with socket.socket() as probe:
                probe.settimeout(0.05)
                if probe.connect_ex(("127.0.0.1", self.port)) == 0:
                    return process
            time.sleep(0.02)
        raise TimeoutError("router_ready_timeout")

    def node_command(self, role):
        result = python_command(
            "-m",
            "wrs_agent",
            role,
            "--endpoint",
            self.endpoint,
            "--site",
            self.site,
            "--env-id",
            self.env_id,
            "--journal",
            self.directory / f"{role}.sqlite3",
            "--duration",
            self.duration,
        )
        result.extend(["--node-id", self.roles[role]])
        if self.bindings_path:
            result.extend(["--bindings", str(self.bindings_path)])
        if role == "wrs":
            result.extend(["--backend", self.backend])
            if self.scene_path is not None:
                result.extend(["--scene", str(self.scene_path)])
        if role == "agent" and self.model_provider == "glm":
            result.extend(["--model-provider", "glm", "--live-model"])
        if self.deferred and role == "agent":
            result.append("--deferred-planner")
        if role == "tts":
            result.extend(["--tts-backend", self.tts_backend])
            for text in self.tts_prepared_texts:
                result.extend(["--tts-prepare", text])
            if self.tts_python is not None:
                # The optional speech node uses its own deps, without .local/deps or -S.
                result = [str(self.tts_python), "-X", "utf8", *result[result.index("-m"):]]
        if self.fault:
            result.extend(["--fault", self.fault])
        return result

    async def _wait_ready(self, bus, key, *, seconds=10):
        async with asyncio.timeout(seconds):
            while True:
                if any(p.poll() is not None for p in self.processes):
                    raise RuntimeError(f"Node exited; see {self.directory}")
                try:
                    return await bus.request(key, {}, timeout=0.5)
                except TimeoutError:
                    await asyncio.sleep(0.02)

    async def __aenter__(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        try:
            await asyncio.to_thread(self.start_router)
            self._connection = System.connect(
                self.endpoint,
                site=self.site,
                env_id=self.env_id,
                _token=self.token,
                _config=(self.definitions, self.skill_bindings),
            )
            self.system = await self._connection.__aenter__()
            self.system._local_stack = self
            # Only enabled TOML nodes start. Order keeps existing Voice dependencies explicit.
            for role in ("wrs", "tts", "agent", "voice"):
                if role not in self.roles:
                    continue
                node_id = self.roles[role]
                self._spawn(role, self.node_command(role))
                self.started.append(node_id)
                key = (
                    "request/capabilities"
                    if self.definitions[node_id]["actions"]
                    else "request/task/status"
                    if role == "agent"
                    else "request/health"
                )
                await self._wait_ready(
                    self.system._transports[node_id], key,
                    seconds=300 if role == "tts" and self.tts_backend == "qwen" else 10,
                )
            return self
        except BaseException:
            await self.__aexit__(None, None, None)
            raise

    async def __aexit__(self, *exc):
        try:
            if self.system is not None:
                for node_id in reversed(self.started):
                    role = self.definitions[node_id]["type"]
                    with contextlib.suppress(Exception):
                        await self.system._transports[node_id].request(
                            f"request/{role}/shutdown",
                            {},
                            timeout=1,
                            control=True,
                        )
                await self._connection.__aexit__(None, None, None)
        finally:
            await asyncio.to_thread(self._reap)

    def _reap(self):
        for process in reversed(self.processes):
            if process is self.processes[0] and process.poll() is None:
                process.terminate()
            if process.poll() is None:
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.terminate()
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=2)
        for log in self.logs:
            log.close()
