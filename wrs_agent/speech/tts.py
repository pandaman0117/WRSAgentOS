"""Qwen synthesis and local playback behind the existing speak action contract."""

import asyncio
import threading

from wrs_agent.actions import ActionExecutor, ExecutionUnknown, SkillFailure
from wrs_agent.skills import SKILLS, Skill, SpeakArgs, SpeechState
from wrs_agent.speech.assets import model_directory, offline_cuda


class QwenTTS:
    def __init__(self, *, speaker="Vivian"):
        directory = model_directory("tts")
        torch = offline_cuda()
        from qwen_tts import Qwen3TTSModel

        self.model = Qwen3TTSModel.from_pretrained(
            str(directory), device_map="cuda:0", dtype=torch.bfloat16,
            attn_implementation="sdpa", local_files_only=True,
        )
        self.speaker = speaker

    def render(self, text, stopped):
        # qwen-tts 0.1.1 does not forward arbitrary stopping_criteria to its talker.
        # The owner-only PyTorch hook checks between generation forwards instead.
        class SynthesisStopped(Exception):
            pass

        def check_stop(module, inputs):
            if stopped.is_set():
                raise SynthesisStopped

        hook = self.model.model.talker.register_forward_pre_hook(check_stop)
        try:
            waves, rate = self.model.generate_custom_voice(
                text=text, language="Chinese", speaker=self.speaker, max_new_tokens=2048,
            )
            return None if stopped.is_set() else (waves[0], rate)
        except SynthesisStopped:
            return None
        finally:
            hook.remove()


def play_audio(audio, rate, stopped):
    """Only the owner thread touches the stream; cancel aborts queued local output."""
    import numpy as np
    import sounddevice as sd

    audio = np.asarray(audio, dtype="float32").reshape(-1, 1)
    if not len(audio) or not np.isfinite(audio).all():
        raise SkillFailure("invalid_synthesized_audio")
    stream = None
    try:
        if stopped.is_set():
            return False
        stream = sd.OutputStream(samplerate=rate, channels=1, dtype="float32", latency="low")
        stream.start()
        block = max(1, rate // 50)
        for offset in range(0, len(audio), block):
            if stopped.is_set():
                stream.abort()
                return False
            if stream.write(audio[offset:offset + block]):
                raise RuntimeError("audio_output_underflow")
        if stopped.is_set():
            stream.abort()
            return False
        stream.stop()  # Drain the final buffer before reporting completion.
        return not stopped.is_set()
    except Exception as exc:
        if stream is not None:
            try:
                stream.abort()
            except Exception as abort_error:
                raise ExecutionUnknown("audio_abort_not_confirmed") from abort_error
        raise ExecutionUnknown("audio_output_not_confirmed") from exc
    finally:
        if stream is not None:
            try:
                stream.close()
            except Exception as close_error:
                raise ExecutionUnknown("audio_close_not_confirmed") from close_error


class SpeechBackend:
    """Single ActionExecutor owns this backend. No background playback or request queue."""

    def __init__(self, render, play=play_audio):
        self.render, self.play = render, play
        self.cache = {}

    def prepare(self, texts):
        if isinstance(texts, str) or len(set(self.cache).union(texts)) > 32:
            raise ValueError("too_many_prepared_utterances")
        for text in texts:
            SpeakArgs(text=text)
            audio = self.render(text, threading.Event())
            if audio is None:
                raise RuntimeError("speech_preparation_failed")
            self.cache[text] = audio
        # Only explicitly prepared fixed phrases are cached, never arbitrary user transcripts.

    async def speak(self, state, args, stop, progress):
        stopped = threading.Event()
        if stop.is_set():
            return False

        def synthesize():
            try:
                audio = self.cache.get(args.text)
                if audio is None:
                    audio = self.render(args.text, stopped)
            except Exception as exc:
                raise SkillFailure("speech_synthesis_failed") from exc
            return audio

        async def relay_stop():
            await stop.wait()
            stopped.set()

        relay = asyncio.create_task(relay_stop())
        worker = asyncio.create_task(asyncio.to_thread(synthesize))
        try:
            audio = await asyncio.shield(worker)
            # The control loop owns stop. Check it here before scheduling playback,
            # even when the relay coroutine has not yet notified the worker thread.
            if stop.is_set():
                stopped.set()
            if stopped.is_set() or audio is None:
                return False
            worker = asyncio.create_task(asyncio.to_thread(self.play, *audio, stopped))
            completed = await asyncio.shield(worker)
        except asyncio.CancelledError:
            stopped.set()
            # A cancelled coroutine is not proof of stopped playback.
            await asyncio.shield(worker)
            raise
        finally:
            relay.cancel()
            await asyncio.gather(relay, return_exceptions=True)
        if completed and not stop.is_set():
            state.completed += 1
            state.last_text = args.text
            progress(1.0)
            return True
        return False


async def make_qwen_tts(journal, *, prepared_texts=()):
    # Loading/preparation happen before node readiness, never per action or on the control loop.
    renderer = await asyncio.to_thread(QwenTTS)
    backend = SpeechBackend(renderer.render)
    await asyncio.to_thread(backend.prepare, prepared_texts)
    return make_speech_executor(journal, backend)


def make_speech_executor(journal, backend):
    contract = SKILLS["speak"]
    skill = Skill(
        contract.spec.model_copy(update={"verification": "local_audio_output_drained"}),
        contract.arguments, backend.speak,
    )
    return ActionExecutor(
        journal, state=SpeechState(), skills={"speak": skill}, backend="qwen_tts",
        duration=0,
        capabilities_extra={
            "robot_controls": False, "controller_flush": False, "controlled_stop": True,
            "verification": "local_audio_output_drained",
            "stop_scope": "local_audio_stream_abort",
        },
    )
