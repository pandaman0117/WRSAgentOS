import asyncio
from types import SimpleNamespace

import pytest
from conftest import eventually

from wrs_agent.nodes.asr import AsrNode
from wrs_agent.nodes.asr.capture import make_mock_capture
from wrs_agent.schemas import AsrResult, TextReceipt


class Bus:
    def __init__(self):
        self.handlers = {}

    def register_handler(self, key, handler, **kwargs):
        self.handlers[key] = handler


class Voice:
    """Records the endpoint the ASR node chose; Voice itself re-checks the intent."""

    def __init__(self, fail=False):
        self.calls, self.fail = [], fail

    async def request(self, suffix, payload, *, control=False, **kwargs):
        self.calls.append((suffix, payload, control))
        if self.fail:
            raise TimeoutError("voice unavailable")
        return TextReceipt(
            input_id=payload["input_id"],
            disposition="stop" if control else "goal",
            accepted=True,
            request_id=None if control else payload["input_id"],
        ).model_dump()


async def node(script=(), *, fail=False, max_seconds=4.0):
    bus, voice = Bus(), Voice(fail=fail)

    class FixtureNode(AsrNode):
        async def create_capture(self):
            return make_mock_capture(script, max_seconds=max_seconds)

        def connect(self, node_id):
            return voice

    async def wait_for(node_id=None, **kwargs):
        return node_id or "voice"

    instance = FixtureNode(peers={"voice": "voice"})
    instance.discover = lambda: SimpleNamespace(wait_for=wait_for)
    instance.transport = bus
    await instance.setup()
    return bus.handlers, voice, instance.teardown


async def settled(handlers, press_id):
    """Release only acknowledges; the transcript is polled like an action status."""
    return await eventually(
        lambda: handlers["request/asr/result"]({"press_id": press_id}),
        lambda raw: not AsrResult.model_validate(raw).capturing,
    )


async def press(handlers, press_id, *, hold=0):
    begin = AsrResult.model_validate(await handlers["request/asr/begin"]({"press_id": press_id}))
    assert begin.capturing and not begin.text
    if hold:
        await asyncio.sleep(hold)
    ack = AsrResult.model_validate(await handlers["request/asr/end"]({"press_id": press_id}))
    assert ack.capturing and ack.reason == "recognizing"
    return AsrResult.model_validate(await settled(handlers, press_id))


async def test_goal_transcript_returns_to_the_caller_without_being_submitted():
    handlers, voice, close = await node(["机器人，移动到 B"])
    try:
        result = await press(handlers, "p1")
        assert result.text == "机器人，移动到 B" and not result.reason
        # The caller checks admission and task state before it submits a goal.
        assert result.receipt is None and not voice.calls
    finally:
        await close()


async def test_stop_is_routed_here_and_does_not_wait_for_the_caller():
    handlers, voice, close = await node(["停止"])
    try:
        result = await press(handlers, "p1")
        suffix, payload, control = voice.calls[0]
        assert (suffix, control) == ("request/voice/control_text", True)
        # The press ID is the input ID, so a resend deduplicates inside Voice.
        assert payload["input_id"] == "p1" and payload["is_final"] is True
        assert result.text == "停止" and result.receipt.disposition == "stop"
    finally:
        await close()


async def test_repeated_begin_and_end_stay_idempotent():
    handlers, voice, close = await node(["停止"])
    try:
        first = await handlers["request/asr/begin"]({"press_id": "p1"})
        assert await handlers["request/asr/begin"]({"press_id": "p1"}) == first
        await handlers["request/asr/end"]({"press_id": "p1"})
        await handlers["request/asr/end"]({"press_id": "p1"})
        result = await settled(handlers, "p1")
        assert await handlers["request/asr/end"]({"press_id": "p1"}) == result
        # One utterance reaches Voice once, however often the UI retries.
        assert len(voice.calls) == 1
        with pytest.raises(ValueError, match="asr_press_finished"):
            await handlers["request/asr/begin"]({"press_id": "p1"})
    finally:
        await close()


async def test_one_microphone_refuses_a_second_concurrent_press():
    handlers, voice, close = await node(["first", "second"])
    try:
        await handlers["request/asr/begin"]({"press_id": "p1"})
        with pytest.raises(ValueError, match="asr_busy"):
            await handlers["request/asr/begin"]({"press_id": "p2"})
        for endpoint in ("end", "result"):
            with pytest.raises(ValueError, match="asr_press_not_found"):
                await handlers[f"request/asr/{endpoint}"]({"press_id": "p2"})
        assert not voice.calls
    finally:
        await close()


async def test_overlong_press_is_discarded_whole_and_never_reaches_voice():
    handlers, voice, close = await node(["机器人，移动到 B"], max_seconds=0.05)
    try:
        result = await press(handlers, "p1", hold=0.2)
        assert result.text == "" and result.reason == "no_complete_utterance"
        assert not voice.calls
    finally:
        await close()


async def test_lost_release_frees_the_microphone_without_sending_late_audio():
    handlers, voice, close = await node(["stale", "停止"], max_seconds=0.05)
    try:
        await handlers["request/asr/begin"]({"press_id": "p1"})
        await asyncio.sleep(0.2)  # Capture bounds itself; the release never arrives.
        assert (await handlers["request/health"]({}))["recording"] is False
        result = await press(handlers, "p2")
        assert result.text == "停止"
        # Only the new press is routed; the abandoned one is dropped, not queued.
        assert [call[1]["input_id"] for call in voice.calls] == ["p2"]
    finally:
        await close()


async def test_unreachable_voice_keeps_the_stop_transcript_for_the_caller():
    handlers, voice, close = await node(["停止"], fail=True)
    try:
        result = await press(handlers, "p1")
        # Never reported as stopped; the caller still has the text and can retry the stop.
        assert result.text == "停止"
        assert result.reason == "voice_unconfirmed" and result.receipt is None
    finally:
        await close()


async def test_asr_instances_do_not_share_press_ids_or_transcripts():
    first, voice_a, close_a = await node(["first"])
    second, voice_b, close_b = await node(["second"])
    try:
        a, b = await asyncio.gather(press(first, "same-id"), press(second, "same-id"))
        assert (a.text, b.text) == ("first", "second")
        assert not voice_a.calls and not voice_b.calls
        await close_a()
        assert (await second["request/asr/result"]({"press_id": "same-id"}))["text"] == "second"
    finally:
        await close_a()
        await close_b()
