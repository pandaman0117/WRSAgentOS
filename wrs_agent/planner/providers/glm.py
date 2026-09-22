"""GLM Chat Completions adapter. Proposes plans; never executes provider tools."""

import asyncio
import json
import os
import socket
import ssl
import time
from dataclasses import replace
from typing import Literal

import httpx
from pydantic import Field, ValidationError

from wrs_agent.errors import AgentError
from wrs_agent.planner import PlanDecision
from wrs_agent.planner.providers import ModelReply, ModelRequest, ModelTiming
from wrs_agent.schemas import MAX_BYTES, Boundary, decode, encode

CODING_BASE_URL = "https://open.bigmodel.cn/api/coding/paas/v4"
STANDARD_BASE_URL = "https://open.bigmodel.cn/api/paas/v4"


class GLMConfig(Boundary):
    model: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.-]+$")
    base_url: Literal[
        "https://open.bigmodel.cn/api/coding/paas/v4",
        "https://open.bigmodel.cn/api/paas/v4",
    ] = CODING_BASE_URL
    protocol: Literal["chat_completions"] = "chat_completions"
    tool_calling: Literal[True] = True
    stream: Literal[False] = False
    # None omits both reasoning fields, leaving the account's model default. Less reasoning
    # trades planning quality for latency; Runtime still validates every plan before execution.
    thinking: Literal["off", "low", "high", "max"] | None = None
    timeout_s: float = Field(default=20.0, gt=0, le=120)
    max_tokens: int = Field(default=2048, ge=128, le=8192)

    @classmethod
    def from_env(cls):
        # Credentials and an endpoint do not identify an account's enabled model.
        model = os.environ.get("GLM_MODEL", "")
        if not model.strip():
            raise GLMError("glm_model_missing")
        thinking = os.environ.get("GLM_THINKING", "").strip().lower()
        if thinking not in {"", "off", "low", "high", "max"}:
            raise GLMError("glm_thinking_invalid")
        try:
            return cls(
                model=model,
                thinking=thinking or None,
                base_url=os.environ.get("GLM_BASE_URL", CODING_BASE_URL).rstrip("/"),
            )
        except ValidationError as exc:
            field = exc.errors(include_input=False)[0]["loc"][0]
            code = "glm_model_invalid" if field == "model" else "glm_base_url_invalid"
            raise GLMError(code) from None


class GLMError(AgentError):
    """Safe provider code survives Runtime/RPC without HTTP bodies or credentials."""

    def __init__(self, code):
        super().__init__(code, stage="planning")

    def __str__(self):
        return self.code



def transport_error_code(exc):
    """Classify known causes without copying URLs, headers or exception messages."""
    current = exc
    seen = set()
    for _ in range(12):
        if current is None or id(current) in seen:
            break
        seen.add(id(current))
        if isinstance(current, socket.gaierror):
            return "glm_dns_error"
        if isinstance(current, ssl.SSLCertVerificationError):
            return "glm_tls_certificate_error"
        if isinstance(current, ssl.SSLError):
            return "glm_tls_error"
        current = current.__cause__ or current.__context__
    if isinstance(exc, httpx.ProxyError):
        return "glm_proxy_error"
    if isinstance(exc, httpx.ConnectError):
        return "glm_connect_error"
    if isinstance(exc, httpx.RemoteProtocolError):
        return "glm_protocol_error"
    return "glm_transport_error"


def encode_for_model(value: dict) -> str:
    """Serialize for a tokenizer, not for decode(). The wire codec escapes non-ASCII, which
    a peer decodes back but a model reads as literal backslash-u text at twice the tokens."""
    result = json.dumps(value, allow_nan=False, separators=(",", ":"), ensure_ascii=False)
    if len(result.encode()) > MAX_BYTES:
        raise ValueError("payload_too_large")
    return result


def request_body(request: ModelRequest, config: GLMConfig) -> dict:
    body = {
        "model": config.model,
        "stream": config.stream,
        "max_tokens": config.max_tokens,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You propose plans for WRS-Agent. You cannot execute actions. "
                    "Use only the supplied skills and observed objects; never invent coordinates. "
                    "Submit at most one propose_plan call, or answer a question as plain text. "
                    "Dependencies must be acyclic, and steps sharing a resource must be ordered. "
                    "Include verification after manipulation, depending on the step it verifies. "
                    # Runtime discards prose on executable plans; generating it still costs time.
                    "Leave text empty when the plan is executable; the steps are the answer. "
                    "Unknown or ambiguous goals require clarification. "
                    "Never supply execution IDs, permissions, boot IDs or control epochs."
                ),
            },
            {
                "role": "user",
                "content": encode_for_model({"goal": request.goal, "context": request.context}),
            },
        ],
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "propose_plan",
                    "description": "Propose an answer, clarification or bounded task plan.",
                    "parameters": PlanDecision.model_json_schema(),
                },
            }
        ],
        "tool_choice": "auto",
    }
    if config.thinking == "off":
        # GLM-5.3 rejects a disabled type and wants "low" instead; models older than GLM-4.5
        # reject the field itself, so an unset config must still send neither field.
        body["thinking"] = {"type": "disabled"}
    elif config.thinking is not None:
        # Only GLM-5.2 and newer read the effort; older models accept and ignore it.
        body["thinking"] = {"type": "enabled"}
        body["reasoning_effort"] = config.thinking
    return body


def parse_reply(data: bytes) -> ModelReply:
    """Decode the native protocol; ModelPlanner validates the proposed decision."""
    try:
        body = decode(data)
        choices = body["choices"]
        if not isinstance(choices, list) or len(choices) != 1:
            raise ValueError("one_choice_required")
        choice = choices[0]
        message = choice["message"]
        if not isinstance(message, dict) or message.get("role") != "assistant":
            raise ValueError("assistant_message_required")
        finish = choice["finish_reason"]
        usage = body.get("usage") or {}
        if not isinstance(usage, dict):
            raise ValueError("invalid_usage")
        metadata = {
            "provider": "glm",
            "protocol": "chat_completions",
            "id": body.get("id"),
            "model": body.get("model"),
            "finish_reason": finish,
            "message": message,
        }
        if message.get("refusal") or finish not in {"stop", "tool_calls"}:
            return ModelReply("", "incomplete", usage, metadata)
        calls = message.get("tool_calls") or []
        if calls:
            if not isinstance(calls, list) or len(calls) != 1:
                raise ValueError("one_tool_required")
            call = calls[0]
            if call["type"] != "function" or call["function"]["name"] != "propose_plan":
                raise ValueError("unexpected_tool")
            arguments = call["function"]["arguments"]
            if not isinstance(arguments, str):
                raise ValueError("json_arguments_required")
            text = arguments  # Parse the proposal once, at the Planner boundary.
        else:
            if finish != "stop":
                raise ValueError("missing_tool")
            # Text that resembles JSON is still an answer, never executable.
            if not isinstance(message["content"], str):
                raise ValueError("text_required")
            text = encode({"kind": "answer", "text": message["content"], "plan": None}).decode()
        return ModelReply(text, "complete", usage, metadata)
    except (KeyError, TypeError, ValueError, RecursionError):
        raise GLMError("glm_invalid_reply") from None


class GLMClient:
    def __init__(
        self,
        config: GLMConfig,
        *,
        live_model: bool = False,
        transport: httpx.MockTransport | None = None,
    ):
        # Only an explicit offline HTTP fixture bypasses the live opt-in.
        if transport is not None and not isinstance(transport, httpx.MockTransport):
            raise GLMError("glm_offline_transport_required")
        if transport is None and not live_model:
            raise GLMError("glm_live_model_opt_in_required")
        key = "offline-fixture" if transport is not None else os.environ.get("GLM_API_KEY", "")
        if not key or len(key) > 512 or not key.isascii() or any(c.isspace() for c in key):
            raise GLMError("glm_api_key_missing_or_invalid")
        self.config = config
        self._http = httpx.AsyncClient(
            base_url=config.base_url + "/",
            headers={"Authorization": f"Bearer {key}", "User-Agent": "WRS-Agent/0.1.0"},
            timeout=config.timeout_s,
            follow_redirects=False,
            # An explicit transport disables HTTPX environment proxy discovery, and its
            # trust_env keeps SSL_CERT_FILE/SSL_CERT_DIR out of the TLS context. The retry
            # covers connection setup only: a request already sent is never repeated.
            transport=transport or httpx.AsyncHTTPTransport(retries=1, trust_env=False),
        )

    async def complete(self, request: ModelRequest) -> ModelReply:
        body = request_body(request, self.config)
        started, first_byte = time.perf_counter(), None
        try:
            async with asyncio.timeout(self.config.timeout_s):
                async with self._http.stream("POST", "chat/completions", json=body) as response:
                    if response.status_code != 200:
                        raise GLMError(f"glm_http_{response.status_code}")
                    data = bytearray()
                    async for chunk in response.aiter_bytes():
                        if first_byte is None:
                            first_byte = time.perf_counter()
                        if len(data) + len(chunk) > MAX_BYTES:
                            raise GLMError("glm_reply_too_large")
                        data.extend(chunk)
            received = time.perf_counter()
            reply = parse_reply(bytes(data))  # An empty body fails here, so first_byte is set.
            done = time.perf_counter()
            timing = ModelTiming(
                total=done - started,
                wait=first_byte - started,
                receive=received - first_byte,
                parse=done - received,
            )
            return replace(reply, timing=timing)
        except (httpx.TimeoutException, TimeoutError):
            raise GLMError("glm_timeout") from None
        except httpx.HTTPError as exc:
            raise GLMError(transport_error_code(exc)) from None

    async def aclose(self) -> None:
        await self._http.aclose()
