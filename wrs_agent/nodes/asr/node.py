"""Push-to-talk node; each instance owns its capture session and result history."""

import asyncio
import threading
from collections import OrderedDict
from typing import Literal

from wrs_agent.errors import AgentError
from wrs_agent.nodes.asr.capture import make_mock_capture
from wrs_agent.nodes.node import Node
from wrs_agent.nodes.options import Texts
from wrs_agent.policy import text_intent
from wrs_agent.schemas import AsrPress, AsrResult, Boundary, Empty, TextInput, TextReceipt

CAPTURE_HISTORY = 256


class AsrOptions(Boundary):
    backend: Literal["mock", "qwen"] = "mock"
    script: Texts = ()
    vocabulary: Texts = ()


class AsrNode(Node):
    node_type = "asr"
    options_type = AsrOptions
    features = ("input.transcribe",)
    requires = ("voice",)
    launch_options = {
        "backend": "asr_backend",
        "script": "asr_script",
        "vocabulary": "asr_vocabulary",
    }

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._press = None
        self._results = OrderedDict()
        self._lock = asyncio.Lock()
        self.capture = None
        self.voice = None

    async def create_capture(self):
        """Override to use another capture backend; keep the session and control rules."""
        if self.options.backend == "qwen":
            from wrs_agent.nodes.asr.qwen import make_qwen_capture

            return await asyncio.to_thread(make_qwen_capture, vocabulary=self.options.vocabulary)
        return make_mock_capture(self.options.script)

    async def setup(self):
        self.capture = await self.create_capture()
        registry = self.discover()
        voice_id = await registry.wait_for(
            self.peers.get("voice"), role="voice", timeout=None,
        )
        self.voice = self.connect(voice_id)
        self.transport.register_handler("request/asr/begin", self.begin, control=True)
        self.transport.register_handler("request/asr/end", self.end, control=True)
        self.transport.register_handler("request/asr/result", self.result)
        self.transport.register_handler("request/health", self.health)

    def _start_capture(self, press_id):
        held = threading.Event()
        held.set()
        return {
            "press_id": press_id,
            "held": held,
            "finishing": None,
            "worker": asyncio.create_task(asyncio.to_thread(self.capture, held.is_set)),
        }

    async def _drain_capture(self, session):
        """Stop the device thread and discard its audio; never cancel it to claim a stop."""
        session["held"].clear()
        await asyncio.gather(session["worker"], return_exceptions=True)

    async def _forward_stop(self, press_id, text):
        raw = await self.voice.request(
            "request/voice/control_text",
            TextInput(input_id=press_id, text=text).model_dump(),
            control=True,
        )
        return TextReceipt.model_validate(raw)

    async def begin(self, payload):
        request = AsrPress.model_validate(payload)
        async with self._lock:
            if self._press is not None and self._press["press_id"] == request.press_id:
                return AsrResult(press_id=request.press_id, capturing=True).model_dump()
            if request.press_id in self._results:
                raise AgentError("asr_press_finished")
            if self._press is not None:
                if not self._press["worker"].done() or self._press["finishing"] is not None:
                    raise AgentError("asr_busy")
                # Capture bounded itself and no release arrived: drop it, never send it late.
                await self._drain_capture(self._press)
            self._press = self._start_capture(request.press_id)
            return AsrResult(press_id=request.press_id, capturing=True).model_dump()

    async def _recognize(self, session):
        """Transcribe and route after the release, so no caller waits on the GPU."""
        try:
            text = await session["worker"]
        except Exception:
            # Device failures carry paths and settings; keep the reason a fixed code.
            text, reason = None, "capture_failed"
        else:
            reason = "" if text else "no_complete_utterance"
        receipt = None
        if text and text_intent(TextInput(text=text))[0] in {"stop", "cancel_tts"}:
            try:
                receipt = await self._forward_stop(session["press_id"], text)
            except Exception:
                # Voice may already have accepted it. The caller keeps the text and can
                # resend it under the same input_id, which Voice deduplicates.
                reason = "voice_unconfirmed"
        result = AsrResult(
            press_id=session["press_id"], text=text or "", reason=reason, receipt=receipt
        )
        async with self._lock:
            self._results[session["press_id"]] = result
            if len(self._results) > CAPTURE_HISTORY:
                self._results.popitem(last=False)
            if self._press is session:
                self._press = None

    async def end(self, payload):
        request = AsrPress.model_validate(payload)
        async with self._lock:
            if request.press_id in self._results:
                return self._results[request.press_id].model_dump()
            if self._press is None or self._press["press_id"] != request.press_id:
                raise AgentError("asr_press_not_found")
            if self._press["finishing"] is None:
                self._press["held"].clear()
                self._press["finishing"] = asyncio.create_task(self._recognize(self._press))
            return AsrResult(
                press_id=request.press_id, capturing=True, reason="recognizing"
            ).model_dump()

    async def result(self, payload):
        request = AsrPress.model_validate(payload)
        if request.press_id in self._results:
            return self._results[request.press_id].model_dump()
        if self._press is not None and self._press["press_id"] == request.press_id:
            reason = "recognizing" if self._press["finishing"] is not None else ""
            return AsrResult(press_id=request.press_id, capturing=True, reason=reason).model_dump()
        raise AgentError("asr_press_not_found")

    async def health(self, payload):
        Empty.model_validate(payload)
        return {
            "backend": self.options.backend,
            "captures": len(self._results),
            "recording": self._press is not None and not self._press["worker"].done(),
        }

    async def teardown(self):
        session, self._press = self._press, None
        if session is not None:
            session["held"].clear()
            pending = [t for t in (session["finishing"], session["worker"]) if t is not None]
            await asyncio.gather(*pending, return_exceptions=True)
