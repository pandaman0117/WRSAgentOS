import subprocess
from unittest.mock import patch

import pytest

from wrs_agent.processes import NO_WINDOW, ROUTER, check_router_version

VERSION_LINE = b"zenohd v1.9.0 built with rustc 1.93.0 (254b59607 2026-01-19)\n"
LOG_LINE = b"2026-09-17T03:12:20.445133Z  INFO main ThreadId(01) zenohd: " + VERSION_LINE


@pytest.mark.parametrize(
    "output",
    [
        VERSION_LINE,
        LOG_LINE + VERSION_LINE,
        LOG_LINE + VERSION_LINE.replace(b"\n", b"\r\n"),
        b"zenohd v1.9.0\n",
        b"zenohd 1.9.0\r\n",
    ],
    ids=["official", "log-prefix", "windows-newlines", "bare-version", "no-v-prefix"],
)
def test_router_version_accepts_pinned_version_with_logging(output):
    with patch("wrs_agent.processes.subprocess.check_output", return_value=output) as probe:
        check_router_version(ROUTER)
    probe.assert_called_once_with([str(ROUTER), "--version"], timeout=5, creationflags=NO_WINDOW)


@pytest.mark.parametrize(
    "output",
    [
        b"zenohd v1.10.1 built with rustc\n",
        b"zenohd v1.9.00 built with rustc\n",
        b"zenohd v1.9.0-dev built with rustc\n",
        LOG_LINE + b"zenohd v1.10.1 built with rustc\n",
        LOG_LINE,
        b"",
    ],
    ids=["different", "longer-version", "prerelease", "misleading-log", "log-only", "empty"],
)
def test_router_version_rejects_mismatch_with_diagnostics(output):
    with (
        patch("wrs_agent.processes.subprocess.check_output", return_value=output),
        pytest.raises(RuntimeError, match="zenohd_version_mismatch") as error,
    ):
        check_router_version(ROUTER)
    assert "expected 1.9.0" in str(error.value)
    assert str(ROUTER) in str(error.value)
    assert repr(output.decode().strip()) in str(error.value)


@pytest.mark.parametrize(
    "error",
    [
        subprocess.CalledProcessError(1, ["zenohd", "--version"], output=VERSION_LINE),
        subprocess.TimeoutExpired(["zenohd", "--version"], 5),
    ],
    ids=["nonzero-exit", "timeout"],
)
def test_router_version_probe_failure_is_not_accepted(error):
    with (
        patch("wrs_agent.processes.subprocess.check_output", side_effect=error),
        pytest.raises(type(error)),
    ):
        check_router_version(ROUTER)


@pytest.mark.parametrize(
    "arguments",
    [
        ["agent", "--model-provider", "llm"],
        ["agent", "--deferred-planner"],
        ["wrs", "--duration", "0"],
        ["wrs", "--backend", "hardware"],
        ["wrs", "--backend", "wrs_virtual"],
    ],
)
async def test_cli_rejects_unsafe_configuration_before_starting(monkeypatch, arguments):
    import sys

    from wrs_agent import __main__ as cli

    async def must_not_start(**kwargs):
        pytest.fail("Invalid command must not start a node or contact a model")

    monkeypatch.setattr(sys, "argv", ["wrs_agent", *arguments])
    monkeypatch.setattr(cli, "serve_node", must_not_start)
    with pytest.raises(SystemExit) as error:
        await cli.main()
    assert error.value.code == 2


@pytest.mark.parametrize("token", [None, "short", "x" * 129])
async def test_connect_rejects_missing_or_invalid_credential_before_open(monkeypatch, token):
    from wrs_agent import System

    if token is None:
        monkeypatch.delenv("WRS_AGENT_TOKEN", raising=False)
    else:
        monkeypatch.setenv("WRS_AGENT_TOKEN", token)

    def unexpected(*args):
        pytest.fail("Invalid credential must not open a transport")

    monkeypatch.setattr("wrs_agent.system.Transport", unexpected)
    with pytest.raises(ValueError, match="WRS_AGENT_TOKEN"):
        async with System.connect():
            pytest.fail("Connection must not be admitted")


async def test_directory_setup_failure_closes_the_connection(monkeypatch):
    from wrs_agent import System

    monkeypatch.setenv("WRS_AGENT_TOKEN", "unit-credential-only")
    opened, closed = [], []

    class ConnectionFixture:
        def __init__(self, endpoint, site, env_id, token, source):
            self.endpoint, self.site, self.env_id = endpoint, site, env_id
            opened.append(self)

        async def close(self):
            closed.append(self)

    def fail_directory(*args, **kwargs):
        raise OSError("directory setup failed")

    monkeypatch.setattr("wrs_agent.system.Transport", ConnectionFixture)
    monkeypatch.setattr("wrs_agent.system.NodeRegistry", fail_directory)
    with pytest.raises(OSError, match="directory setup failed"):
        async with System.connect():
            pytest.fail("Partial connection must not be admitted")
    assert len(opened) == 1 and closed == opened


@pytest.mark.parametrize("profile", ["vision", "voice"])
def test_launch_rejects_unimplemented_or_incomplete_profile(tmp_path, profile):
    from wrs_agent.processes import LocalStack

    config = tmp_path / "bindings.toml"
    config.write_text(
        f'[nodes.{profile}]\ntype="{profile}"\nsuffix="-{profile}"\n'
        "actions=false\nenabled=true\n[skills]\n",
        encoding="utf-8",
    )
    reason = "node_type_not_implemented" if profile == "vision" else "voice_requires"
    with pytest.raises(ValueError, match=reason):
        LocalStack(bindings=config)


@pytest.mark.parametrize("env_id", ["../outside", "..", ".", "a/b", "a" * 81])
def test_local_namespace_rejected_before_creating_files_or_processes(env_id):
    from wrs_agent.processes import LocalStack

    with pytest.raises(ValueError, match="invalid_namespace"):
        LocalStack(env_id=env_id)


@pytest.mark.parametrize(
    "role, options, reason",
    [
        ("unknown", {}, "unsupported_node_role"),
        ("agent", {"unexpected": True}, "Extra inputs are not permitted"),
        ("wrs", {"backend": "hardware"}, "backend"),
        ("wrs", {"backend": "wrs_virtual"}, "backend"),
        ("wrs", {"duration": 0}, "greater than 0"),
        ("agent", {"provider": "mock"}, "Extra inputs are not permitted"),
        (
            "agent",
            {"deferred_planner": True},
            "Extra inputs are not permitted",
        ),
    ],
)
async def test_python_node_entry_rejects_invalid_configuration(monkeypatch, role, options, reason):
    from wrs_agent.nodes.serve import serve_node

    def unexpected(*args):
        pytest.fail("Invalid configuration must not acquire a lock or open a transport")

    monkeypatch.setattr("wrs_agent.nodes.node.InstanceLock", unexpected)
    monkeypatch.setattr("wrs_agent.nodes.node.Transport", unexpected)
    with pytest.raises(ValueError, match=reason):
        await serve_node(role, options=options)


@pytest.mark.parametrize("filename", ["01_plan.py", "02_execute.py"])
@pytest.mark.parametrize(
    "variable,value",
    [
        ("LLM_MODEL", None),
        ("LLM_MODEL", ""),
        ("LLM_MODEL", " \t"),
        ("LLM_MODEL", "private-invalid-model!"),
        ("LLM_MODEL", "x" * 129),
        ("LLM_BASE_URL", None),
        ("LLM_BASE_URL", "http://private-invalid-endpoint.example/v1"),
        ("LLM_PROTOCOL", "private-invalid-protocol"),
        ("LLM_REASONING_EFFORT", "private-invalid-effort"),
        ("LLM_EXTRA_BODY", "private-not-json"),
        ("LLM_EXTRA_BODY", '{"model": "private-override"}'),
        ("LLM_API_KEY", None),
    ],
    ids=["missing-model", "empty-model", "blank-model", "invalid-model", "long-model",
         "missing-endpoint", "plaintext-endpoint", "invalid-protocol", "invalid-effort",
         "invalid-extra-body", "conflicting-extra-body", "missing-key"],
)
async def test_online_model_examples_reject_invalid_config_before_launch(
    monkeypatch, filename, variable, value
):
    import runpy

    from wrs_agent.processes import ROOT

    for name in ("PROTOCOL", "REASONING_EFFORT", "EXTRA_BODY", "EXTRA_HEADERS", "PROXY"):
        monkeypatch.delenv("LLM_" + name, raising=False)
    monkeypatch.setenv("LLM_API_KEY", "private-offline-test-key")
    monkeypatch.setenv("LLM_MODEL", "test-model")
    monkeypatch.setenv("LLM_BASE_URL", "https://open.bigmodel.cn/api/coding/paas/v4")
    if value is None:
        monkeypatch.delenv(variable, raising=False)
    else:
        monkeypatch.setenv(variable, value)

    def unexpected(*args, **kwargs):
        pytest.fail("Invalid configuration must fail before creating clients or launching nodes")

    monkeypatch.setattr("httpx.AsyncClient", unexpected)
    monkeypatch.setattr("wrs_agent.processes.LocalStack", unexpected)
    entry = runpy.run_path(str(ROOT / "examples/models" / filename))
    with pytest.raises(SystemExit, match=variable) as error:
        await entry["main"]()
    assert "private-" not in str(error.value)



@pytest.mark.parametrize("name", ["../escape", "a/b", "", "x" * 201])
def test_instance_lock_rejects_invalid_names(name):
    from wrs_agent.processes import InstanceLock

    with pytest.raises(ValueError, match="invalid_instance_name"):
        InstanceLock(name)


def test_router_override_takes_precedence_over_local_and_path(monkeypatch, tmp_path):
    from wrs_agent import processes

    explicit = tmp_path / "custom router"
    local = tmp_path / "local router"
    explicit.touch()
    local.touch()
    monkeypatch.setenv("WRS_AGENT_ZENOHD", str(explicit))
    monkeypatch.setattr(processes, "ROUTER", local)

    def unexpected(*args):
        pytest.fail("An explicit router must not fall back to PATH")

    monkeypatch.setattr(processes.shutil, "which", unexpected)
    assert processes.router_path() == explicit.resolve()


@pytest.mark.parametrize("configured", ["", "missing", "directory"])
def test_invalid_router_override_does_not_fall_back(monkeypatch, tmp_path, configured):
    from wrs_agent import processes

    local = tmp_path / "local router"
    local.touch()
    monkeypatch.setattr(processes, "ROUTER", local)
    if configured == "directory":
        value = str(tmp_path)
    elif configured:
        value = str(tmp_path / configured)
    else:
        value = configured
    monkeypatch.setenv("WRS_AGENT_ZENOHD", value)
    with pytest.raises(FileNotFoundError, match="WRS_AGENT_ZENOHD"):
        processes.router_path()


def test_local_router_precedes_path(monkeypatch, tmp_path):
    from wrs_agent import processes

    local = tmp_path / "local router"
    local.touch()
    monkeypatch.delenv("WRS_AGENT_ZENOHD", raising=False)
    monkeypatch.setattr(processes, "ROUTER", local)

    def unexpected(*args):
        pytest.fail("A local pinned router must take precedence over PATH")

    monkeypatch.setattr(processes.shutil, "which", unexpected)
    assert processes.router_path() == local


def test_router_can_be_found_on_path(monkeypatch, tmp_path):
    from wrs_agent import processes

    executable = tmp_path / "PATH router"
    executable.touch()
    monkeypatch.delenv("WRS_AGENT_ZENOHD", raising=False)
    monkeypatch.setattr(processes, "ROUTER", tmp_path / "absent")
    monkeypatch.setattr(processes.shutil, "which", lambda name: str(executable))
    assert processes.router_path() == executable.resolve()


def test_missing_router_explains_configuration(monkeypatch, tmp_path):
    from wrs_agent import processes

    monkeypatch.delenv("WRS_AGENT_ZENOHD", raising=False)
    monkeypatch.setattr(processes, "ROUTER", tmp_path / "absent")
    monkeypatch.setattr(processes.shutil, "which", lambda name: None)
    with pytest.raises(FileNotFoundError, match="zenohd 1.9.0 not found") as error:
        processes.router_path()
    assert "WRS_AGENT_ZENOHD" in str(error.value)
    assert "PATH" in str(error.value)


def test_version_check_uses_configured_router(monkeypatch, tmp_path):
    from wrs_agent import processes

    executable = tmp_path / "configured router"
    executable.touch()
    monkeypatch.setenv("WRS_AGENT_ZENOHD", str(executable))
    with patch("wrs_agent.processes.subprocess.check_output", return_value=VERSION_LINE) as probe:
        processes.check_router_version()
    probe.assert_called_once_with(
        [str(executable.resolve()), "--version"], timeout=5, creationflags=NO_WINDOW
    )


def test_local_launch_passes_only_each_nodes_own_startup_parameters():
    import json

    from wrs_agent.processes import LocalStack

    stack = LocalStack()
    stack.endpoint = "tcp/127.0.0.1:12345"
    agent = stack.node_command("agent")
    voice = stack.node_command("voice")
    assert "--bindings" not in agent and "--bindings" not in voice
    assert "--suffix=" in agent and "--no-actions" in agent
    assert json.loads(agent[agent.index("--peers") + 1]) == {}
    assert json.loads(voice[voice.index("--peers") + 1]) == {
        "wrs": "wrs", "tts": "tts", "agent": "agent",
    }


async def test_standalone_node_entry_does_not_read_a_deployment_file(monkeypatch):
    from wrs_agent.nodes import Node
    from wrs_agent.nodes.serve import serve_node

    constructed = []

    class Standalone(Node):
        async def _serve(self):
            constructed.append(self)

    def unexpected(*args):
        pytest.fail("Standalone Node must not read a launch profile")

    monkeypatch.setattr("wrs_agent.nodes.serve.load_bindings", unexpected)
    await serve_node(Standalone, node_id="late-worker", actions=True)
    instance, = constructed
    assert instance.target == "arm01-late-worker" and instance.action_service
    assert not hasattr(instance, "definitions")


async def test_explicit_node_profile_is_resolved_only_at_the_entry_point(monkeypatch, tmp_path):
    from wrs_agent.nodes import Node
    from wrs_agent.nodes.serve import serve_node

    config = tmp_path / "launch.toml"
    config.write_text(
        '[nodes.worker]\ntype="custom"\nsuffix="-work"\nactions=true\nenabled=true\n'
        '[nodes.speaker]\ntype="tts"\nsuffix="-speech"\nactions=true\nenabled=true\n'
        '[skills]\nspeak="speaker"\n', encoding="utf-8",
    )
    constructed = []

    class Worker(Node):
        requires = ("tts",)

        async def _serve(self):
            constructed.append(self)

    await serve_node(Worker, node_id="worker", bindings=config)
    instance, = constructed
    assert instance.target == "arm01-work" and instance.action_service
    assert instance.peers == {"tts": "speaker"}
    assert instance.skill_bindings == {"speak": "speaker"}
    assert not hasattr(instance, "definitions")
