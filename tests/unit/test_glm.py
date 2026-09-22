"""Native GLM fixtures only. No external HTTP, account or hardware required."""

import asyncio
import copy
import json
import socket
import ssl
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from wrs_agent.planner import ModelPlanner, PlanRequest
from wrs_agent.planner.providers import ModelRequest
from wrs_agent.planner.providers.glm import (
    CODING_BASE_URL,
    GLMClient,
    GLMConfig,
    GLMError,
    parse_reply,
)
from wrs_agent.schemas import MAX_BYTES

FIXTURE = Path(__file__).parents[2] / "examples" / "models" / "fixtures" / "glm_tool_call.json"
REQUEST = ModelRequest("put A in B", {"world": {}, "skills": []})


def reply_body():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def as_bytes(body):
    return json.dumps(body).encode()


async def test_native_tool_roundtrip_and_reused_client(monkeypatch):
    monkeypatch.setenv("GLM_API_KEY", "must-not-leave-the-process")
    requests = []

    def respond(request):
        requests.append(request)
        assert str(request.url) == CODING_BASE_URL + "/chat/completions"
        assert request.headers["Authorization"] == "Bearer offline-fixture"
        assert request.headers["User-Agent"] == "WRS-Agent/0.1.0"
        body = json.loads(request.content)
        assert body["model"] == "account-model"
        assert body["stream"] is False and body["tool_choice"] == "auto"
        assert [t["function"]["name"] for t in body["tools"]] == ["propose_plan"]
        return httpx.Response(200, json=reply_body())

    client = GLMClient(GLMConfig(model="account-model"), transport=httpx.MockTransport(respond))
    try:
        reply = await client.complete(REQUEST)
        assert reply.finish == "complete" and reply.usage["total_tokens"] == 100
        arguments = reply_body()["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"]
        assert reply.text == arguments  # Native JSON is not parsed and re-serialized here.
        assert reply.metadata["message"]["tool_calls"][0]["id"] == "proposal-1"
        decision = await ModelPlanner(client).plan(
            PlanRequest(user_goal=REQUEST.goal, world={}, skills=[])
        )
        assert decision.kind == "execute"
        assert decision.plan.steps[-1].skill == "verify"
        assert len(requests) == 2
    finally:
        await client.aclose()
    assert client._http.is_closed


def test_thinking_is_omitted_until_explicitly_configured():
    """Models older than GLM-4.5 reject the field, so an unset config sends neither."""
    from wrs_agent.planner.providers.glm import request_body

    body = request_body(REQUEST, GLMConfig(model="fixture"))
    assert "thinking" not in body and "reasoning_effort" not in body


@pytest.mark.parametrize("effort", ["low", "high", "max"])
def test_effort_levels_keep_thinking_enabled(effort):
    """GLM-5.3 accepts only an enabled type, and reads the depth from reasoning_effort."""
    from wrs_agent.planner.providers.glm import request_body

    body = request_body(REQUEST, GLMConfig(model="fixture", thinking=effort))
    assert body["thinking"] == {"type": "enabled"}
    assert body["reasoning_effort"] == effort


def test_off_disables_thinking_without_claiming_an_effort():
    """GLM-5.3 rejects this server-side; the adapter never rewrites it into a level."""
    from wrs_agent.planner.providers.glm import request_body

    body = request_body(REQUEST, GLMConfig(model="fixture", thinking="off"))
    assert body["thinking"] == {"type": "disabled"}
    assert "reasoning_effort" not in body


def test_model_reads_text_not_wire_escapes():
    """encode() escapes non-ASCII for peers that decode it; a model would read the escape."""
    from wrs_agent.planner.providers.glm import request_body

    goal = "将机械臂移动到命名姿态 B。"
    request = ModelRequest(goal, {"world": {"held": "工件"}, "skills": []})
    content = request_body(request, GLMConfig(model="fixture"))["messages"][1]["content"]
    assert goal in content and "工件" in content
    assert "\\u" not in content
    assert json.loads(content)["goal"] == goal


@pytest.mark.parametrize(
    "configured,expected",
    [("", None), ("off", "off"), ("low", "low"), ("HIGH", "high"), (" max ", "max")],
)
def test_thinking_from_environment(monkeypatch, configured, expected):
    monkeypatch.setenv("GLM_MODEL", "fixture")
    monkeypatch.setenv("GLM_THINKING", configured)
    assert GLMConfig.from_env().thinking == expected


@pytest.mark.parametrize("stale", ["0", "1", "true", "disabled"])
def test_superseded_boolean_thinking_fails_loudly(monkeypatch, stale):
    """A boolean left from the old contract must not silently mean the account default."""
    monkeypatch.setenv("GLM_MODEL", "fixture")
    monkeypatch.setenv("GLM_THINKING", stale)
    with pytest.raises(GLMError, match="^glm_thinking_invalid$"):
        GLMConfig.from_env()


def test_invalid_thinking_is_safe(monkeypatch):
    monkeypatch.setenv("GLM_MODEL", "fixture")
    monkeypatch.setenv("GLM_THINKING", "private-invalid-value")
    with pytest.raises(GLMError, match="^glm_thinking_invalid$") as error:
        GLMConfig.from_env()
    assert "private" not in error.value.error.model_dump_json()


async def test_timing_splits_one_call_into_spans():
    """Spans are observation, so assert structure and ordering, never wall-clock values."""
    client = GLMClient(
        GLMConfig(model="fixture"),
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=reply_body())),
    )
    planner = ModelPlanner(client)
    try:
        await planner.plan(PlanRequest(user_goal="put A in B", world={}, skills=[]))
        timing, model = planner.last_timing, planner.last_timing.model
        assert min(model.total, model.wait, model.receive, model.parse) >= 0
        assert model.wait + model.receive + model.parse == pytest.approx(model.total)
        assert timing.total >= model.total and timing.validate >= 0
        # Counts come from the reply, so they stay out of the locally measured spans.
        assert planner.last_usage == reply_body()["usage"]
        assert not hasattr(timing, "usage")
    finally:
        await client.aclose()


async def test_failed_planning_keeps_no_stale_spans():
    def fail(request):
        raise httpx.ConnectError("private", request=request)

    client = GLMClient(GLMConfig(model="fixture"), transport=httpx.MockTransport(fail))
    planner = ModelPlanner(client)
    try:
        with pytest.raises(GLMError):
            await planner.plan(PlanRequest(user_goal="goal", world={}, skills=[]))
        assert planner.last_timing is None and planner.last_usage == {}
    finally:
        await client.aclose()


@pytest.mark.parametrize("content", ["Still planning.", '{"kind":"execute","plan":{"steps":[]}}'])
def test_text_is_answer_never_executable(content):
    body = reply_body()
    body["choices"][0] = {
        "finish_reason": "stop",
        "message": {"role": "assistant", "content": content},
    }
    reply = parse_reply(as_bytes(body))
    decision = json.loads(reply.text)
    assert decision["kind"] == "answer" and decision["plan"] is None
    assert decision["text"] == content


@pytest.mark.parametrize(
    "fault", ["two_tools", "wrong_tool", "partial", "authority", "cycle", "empty"]
)
async def test_bad_tool_calls_fail_closed(fault):
    body = reply_body()
    calls = body["choices"][0]["message"]["tool_calls"]
    if fault == "two_tools":
        calls.append(copy.deepcopy(calls[0]))
    elif fault == "wrong_tool":
        calls[0]["function"]["name"] = "run_shell"
    elif fault == "partial":
        calls[0]["function"]["arguments"] = '{"kind":"execute","plan":'
    elif fault == "authority":
        arguments = json.loads(calls[0]["function"]["arguments"])
        arguments["control_epoch"] = 999
        calls[0]["function"]["arguments"] = json.dumps(arguments)
    elif fault == "cycle":
        arguments = json.loads(calls[0]["function"]["arguments"])
        arguments["plan"]["steps"][0]["depends_on"] = ["verify"]
        calls[0]["function"]["arguments"] = json.dumps(arguments)
    else:
        calls.clear()
    client = GLMClient(
        GLMConfig(model="fixture"),
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body)),
    )
    try:
        # Protocol errors belong to GLM; malformed/unsafe plans belong to Planner.
        error = GLMError if fault in {"two_tools", "wrong_tool", "empty"} else ValidationError
        with pytest.raises(error):
            await ModelPlanner(client).plan(
                PlanRequest(user_goal="put A in B", world={}, skills=[])
            )
    finally:
        await client.aclose()


@pytest.mark.parametrize("finish", ["length", "sensitive", "network_error", "unknown", None])
async def test_incomplete_cannot_become_decision(finish):
    body = reply_body()
    body["choices"][0]["finish_reason"] = finish
    client = GLMClient(
        GLMConfig(model="fixture"),
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body)),
    )
    try:
        with pytest.raises(ValueError, match="incomplete_model_reply"):
            await ModelPlanner(client).plan(PlanRequest(user_goal="goal", world={}, skills=[]))
    finally:
        await client.aclose()


def test_refusal_cannot_become_decision():
    body = reply_body()
    body["choices"][0]["message"]["refusal"] = "Declined"
    assert parse_reply(as_bytes(body)).finish != "complete"


@pytest.mark.parametrize(
    "data",
    [b"null", b"{", b'{"choices":[]}', b'{"choices":[{}]}', b" " * (MAX_BYTES + 1)],
    ids=["null", "partial", "no_choices", "no_message", "oversize"],
)
def test_malformed_response(data):
    with pytest.raises(GLMError, match="^glm_invalid_reply$"):
        parse_reply(data)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"stream": True},
        {"thinking": {"type": "enabled"}},
        {"protocol": "anthropic"},
        {"base_url": "https://untrusted.invalid"},
        {"timeout_s": float("inf")},
        {"model": ""},
    ],
)
def test_unsupported_configuration_rejected(kwargs):
    with pytest.raises(ValidationError):
        GLMConfig(**({"model": "fixture"} | kwargs))


def test_live_opt_in_and_required_environment(monkeypatch):
    monkeypatch.delenv("GLM_MODEL", raising=False)
    monkeypatch.delenv("GLM_API_KEY", raising=False)
    with pytest.raises(GLMError, match="^glm_model_missing$") as error:
        GLMConfig.from_env()
    assert "GLM_MODEL" in error.value.error.message
    with pytest.raises(GLMError, match="glm_live_model_opt_in_required"):
        GLMClient(GLMConfig(model="fixture"))
    with pytest.raises(GLMError, match="glm_api_key_missing_or_invalid"):
        GLMClient(GLMConfig(model="fixture"), live_model=True)
    monkeypatch.setenv("GLM_MODEL", "explicit-account-model")
    monkeypatch.setenv("GLM_BASE_URL", CODING_BASE_URL + "/")
    assert GLMConfig.from_env().model == "explicit-account-model"


@pytest.mark.parametrize("status", [301, 401, 429, 503])
async def test_errors_no_body_leak_no_retry_or_paid_fallback(status):
    urls = []

    def respond(request):
        urls.append(str(request.url))
        return httpx.Response(
            status,
            text="secret-provider-diagnostic",
            headers={"location": "https://open.bigmodel.cn/api/paas/v4/chat/completions"},
        )

    client = GLMClient(GLMConfig(model="fixture"), transport=httpx.MockTransport(respond))
    try:
        with pytest.raises(GLMError, match=f"^glm_http_{status}$"):
            await client.complete(REQUEST)
        assert urls == [CODING_BASE_URL + "/chat/completions"]
    finally:
        await client.aclose()


async def test_total_timeout_and_cancellation():
    entered, closed = asyncio.Event(), asyncio.Event()

    async def never_returns(request):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            closed.set()

    client = GLMClient(
        GLMConfig(model="fixture", timeout_s=0.05),
        transport=httpx.MockTransport(never_returns),
    )
    try:
        with pytest.raises(GLMError, match="^glm_timeout$"):
            await client.complete(REQUEST)
        assert closed.is_set()
        entered.clear()
        closed.clear()
        pending = asyncio.create_task(client.complete(REQUEST))
        await entered.wait()
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        assert closed.is_set()
    finally:
        await client.aclose()


async def test_network_failure_redacted():
    def fail(request):
        raise httpx.ConnectError("sensitive network diagnostic", request=request)

    client = GLMClient(GLMConfig(model="fixture"), transport=httpx.MockTransport(fail))
    try:
        with pytest.raises(GLMError, match="^glm_connect_error$"):
            await client.complete(REQUEST)
    finally:
        await client.aclose()


async def test_oversized_reply_bounded_and_closed():
    client = GLMClient(
        GLMConfig(model="fixture"),
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, content=b"x" * (MAX_BYTES + 1))
        ),
    )
    try:
        with pytest.raises(GLMError, match="^glm_reply_too_large$"):
            await client.complete(REQUEST)
    finally:
        await client.aclose()

@pytest.mark.parametrize(
    "error_type,cause_type,expected",
    [
        (httpx.ConnectError, socket.gaierror, "glm_dns_error"),
        (httpx.ConnectError, ssl.SSLCertVerificationError, "glm_tls_certificate_error"),
        (httpx.ConnectError, ssl.SSLEOFError, "glm_tls_error"),
        (httpx.ConnectError, None, "glm_connect_error"),
        (httpx.ProxyError, None, "glm_proxy_error"),
        (httpx.RemoteProtocolError, None, "glm_protocol_error"),
        (httpx.ReadError, None, "glm_transport_error"),
        (httpx.ReadTimeout, None, "glm_timeout"),
    ],
)
async def test_network_causes_are_classified_without_disclosing_values(
    error_type, cause_type, expected
):
    def fail(request):
        error = error_type("private-key-and-proxy-details", request=request)
        if cause_type is not None:
            raise error from cause_type(1, "private-underlying-diagnostic")
        raise error

    client = GLMClient(GLMConfig(model="fixture"), transport=httpx.MockTransport(fail))
    try:
        with pytest.raises(GLMError, match=f"^{expected}$") as error:
            await client.complete(REQUEST)
        assert "private-" not in error.value.error.model_dump_json()
        assert error.value.__suppress_context__
    finally:
        await client.aclose()


def test_network_error_classification_handles_context_and_cycles():
    from wrs_agent.planner.providers.glm import transport_error_code

    error = httpx.ConnectError("private")
    error.__context__ = socket.gaierror(11001, "private")
    assert transport_error_code(error) == "glm_dns_error"
    error.__context__ = error
    assert transport_error_code(error) == "glm_connect_error"


async def test_planning_example_reports_network_failure_and_cleans_up(monkeypatch):
    import runpy
    from contextlib import asynccontextmanager
    from types import SimpleNamespace

    from wrs_agent.processes import ROOT

    monkeypatch.setenv("GLM_MODEL", "fixture")
    monkeypatch.setenv("GLM_BASE_URL", CODING_BASE_URL)
    state = {"closed": False}

    def fail(request):
        raise httpx.ConnectError("private") from socket.gaierror(11001, "private")

    client = GLMClient(GLMConfig(model="fixture"), transport=httpx.MockTransport(fail))

    async def snapshot():
        return SimpleNamespace(data=SimpleNamespace(model_dump=lambda: {}))

    async def skills():
        return []

    @asynccontextmanager
    async def stack(**kwargs):
        try:
            yield SimpleNamespace(system=SimpleNamespace(snapshot=snapshot, skills=skills))
        finally:
            state["closed"] = True

    monkeypatch.setattr("wrs_agent.planner.providers.glm.GLMClient", lambda *a, **kw: client)
    monkeypatch.setattr("wrs_agent.processes.LocalStack", stack)
    entry = runpy.run_path(str(ROOT / "examples/models/01_plan.py"))
    with pytest.raises(SystemExit, match="glm_dns_error") as error:
        await entry["main"]()
    assert "无法解析" in str(error.value) and "private" not in str(error.value)
    assert state["closed"] and client._http.is_closed


async def test_connection_check_sends_no_key_and_accepts_http_error_as_reachable(
    monkeypatch, capsys
):
    import runpy

    from wrs_agent.processes import ROOT

    requests = []

    def respond(request):
        requests.append(request)
        assert "authorization" not in request.headers
        assert request.method == "GET"
        assert not request.content
        return httpx.Response(401)

    monkeypatch.setenv("GLM_API_KEY", "private-key-that-must-not-be-sent")
    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(respond), **kwargs),
    )
    entry = runpy.run_path(str(ROOT / "scripts/check_glm_connection.py"))
    assert await entry["check"](CODING_BASE_URL) == 0
    assert len(requests) == 1
    assert "private" not in capsys.readouterr().out

async def test_live_client_never_uses_environment_proxy_without_sending_requests(monkeypatch):
    monkeypatch.setenv("GLM_API_KEY", "offline-key-no-request")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("NO_PROXY", "")
    monkeypatch.delenv("ALL_PROXY", raising=False)
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    monkeypatch.delenv("SSL_CERT_DIR", raising=False)
    client = GLMClient(GLMConfig(model="fixture"), live_model=True)
    try:
        # A proxy in the environment must never silently carry robot planning requests.
        selected = client._http._transport_for_url(httpx.URL(CODING_BASE_URL))
        assert selected is client._http._transport
    finally:
        await client.aclose()


async def test_offline_fixture_never_uses_environment_proxy(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("SSL_CERT_FILE", "missing-test-certificate-file")
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json=reply_body())

    transport = httpx.MockTransport(respond)
    client = GLMClient(GLMConfig(model="fixture"), transport=transport)
    try:
        assert (await client.complete(REQUEST)).finish == "complete"
        assert len(requests) == 1
    finally:
        await client.aclose()
