"""Push-to-talk capture in its own process.

The transcript goes back to the caller that held the button, which applies its own admission
policy before submitting a goal. Only a stop is routed from here, because it must not depend
on that caller staying alive to relay it. Voice still receives recognized text, never audio.
"""

import asyncio
import threading
import time
from collections import OrderedDict

from wrs_agent.errors import AgentError
from wrs_agent.policy import text_intent
from wrs_agent.schemas import AsrPress, AsrResult, Empty, TextInput, TextReceipt
from wrs_agent.speech.asr import CAPTURE_SECONDS

CAPTURE_HISTORY = 256


def make_mock_capture(script=(), *, max_seconds=CAPTURE_SECONDS):
    """Offline fixture: hold for as long as the caller presses, then return scripted text."""
    pending = list(script)

    def capture(held):
        # One press consumes one scripted line, so a discarded press cannot shift the rest.
        deadline, text = time.monotonic() + max_seconds, pending.pop(0) if pending else None
        while held():
            if time.monotonic() >= deadline:
                return None
            time.sleep(0.005)
        return text

    return capture


def register_asr(bus, voice, capture, *, backend="mock"):
    """One microphone and one press at a time; the capture itself bounds a lost release."""
    press = None
    results = OrderedDict()
    lock = asyncio.Lock()

    def start(press_id):
        held = threading.Event()
        held.set()
        return {
            "press_id": press_id,
            "held": held,
            "finishing": None,
            "worker": asyncio.create_task(asyncio.to_thread(capture, held.is_set)),
        }

    async def drain(session):
        """Stop the device thread and discard its audio; never cancel it to claim a stop."""
        session["held"].clear()
        await asyncio.gather(session["worker"], return_exceptions=True)

    async def forward_stop(press_id, text):
        raw = await voice.request(
            "request/voice/control_text",
            TextInput(input_id=press_id, text=text).model_dump(),
            control=True,
        )
        return TextReceipt.model_validate(raw)

    async def begin(payload):
        nonlocal press
        request = AsrPress.model_validate(payload)
        async with lock:
            if press is not None and press["press_id"] == request.press_id:
                return AsrResult(press_id=request.press_id, capturing=True).model_dump()
            if request.press_id in results:
                raise AgentError("asr_press_finished")
            if press is not None:
                if not press["worker"].done() or press["finishing"] is not None:
                    raise AgentError("asr_busy")
                # Capture bounded itself and no release arrived: drop it, never send it late.
                await drain(press)
            press = start(request.press_id)
            return AsrResult(press_id=request.press_id, capturing=True).model_dump()

    async def recognize(session):
        """Transcribe and route after the release, so no caller waits on the GPU."""
        nonlocal press
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
                receipt = await forward_stop(session["press_id"], text)
            except Exception:
                # Voice may already have accepted it. The caller keeps the text and can
                # resend it under the same input_id, which Voice deduplicates.
                reason = "voice_unconfirmed"
        result = AsrResult(
            press_id=session["press_id"], text=text or "", reason=reason, receipt=receipt
        )
        async with lock:
            results[session["press_id"]] = result
            if len(results) > CAPTURE_HISTORY:
                results.popitem(last=False)
            if press is session:
                press = None

    async def end(payload):
        request = AsrPress.model_validate(payload)
        async with lock:
            if request.press_id in results:
                return results[request.press_id].model_dump()
            if press is None or press["press_id"] != request.press_id:
                raise AgentError("asr_press_not_found")
            if press["finishing"] is None:
                press["held"].clear()
                press["finishing"] = asyncio.create_task(recognize(press))
            return AsrResult(
                press_id=request.press_id, capturing=True, reason="recognizing"
            ).model_dump()

    async def result(payload):
        request = AsrPress.model_validate(payload)
        if request.press_id in results:
            return results[request.press_id].model_dump()
        if press is not None and press["press_id"] == request.press_id:
            reason = "recognizing" if press["finishing"] is not None else ""
            return AsrResult(
                press_id=request.press_id, capturing=True, reason=reason
            ).model_dump()
        raise AgentError("asr_press_not_found")

    async def health(payload):
        Empty.model_validate(payload)
        return {
            "backend": backend,
            "captures": len(results),
            "recording": press is not None and not press["worker"].done(),
        }

    async def close():
        nonlocal press
        session, press = press, None
        if session is not None:
            session["held"].clear()
            pending = [t for t in (session["finishing"], session["worker"]) if t is not None]
            await asyncio.gather(*pending, return_exceptions=True)

    bus.register_handler("request/asr/begin", begin, control=True)
    bus.register_handler("request/asr/end", end, control=True)
    bus.register_handler("request/asr/result", result)
    bus.register_handler("request/health", health)
    return close
