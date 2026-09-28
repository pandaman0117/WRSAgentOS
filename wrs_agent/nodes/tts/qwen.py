"""Qwen synthesis; model preparation completes before node readiness."""

import asyncio

from wrs_agent.nodes.model_assets import model_directory, offline_cuda
from wrs_agent.nodes.tts.backend import SpeechBackend, make_speech_executor

# Check cancellation between chunks, including when CUDA graph replay skips Python hooks.
STOP_CHECK_STEPS = 8


class QwenTTS:
    def __init__(self, *, speaker="Vivian"):
        directory = model_directory("tts")
        torch = offline_cuda()
        from faster_qwen3_tts import FasterQwen3TTS

        self.model = FasterQwen3TTS.from_pretrained(
            str(directory),
            device="cuda",
            dtype=torch.bfloat16,
            attn_implementation="sdpa",
            local_files_only=True,
        )
        # Capturing the CUDA graphs belongs to load time, never to the first action.
        self.model.warmup()
        self.speaker = speaker

    def render(self, text, stopped):
        # Replaying a CUDA graph never calls Python forward hooks, so synthesis can only be
        # interrupted between streamed chunks. Abandoning the generator is safe; the model
        # still serves later requests. Playback joins the chunks.
        chunks, rate = [], None
        stream = self.model.generate_custom_voice_streaming(
            text=text,
            speaker=self.speaker,
            language="Chinese",
            max_new_tokens=2048,
            chunk_size=STOP_CHECK_STEPS,
        )
        try:
            for audio, sample_rate, _ in stream:
                if stopped.is_set():
                    return None
                chunks.append(audio)
                rate = sample_rate
        finally:
            stream.close()
        return None if stopped.is_set() or not chunks else (chunks, rate)


async def make_qwen_tts(journal, *, prepared_texts=()):
    # Loading/preparation happen before node readiness, never per action or on the control loop.
    renderer = await asyncio.to_thread(QwenTTS)
    backend = SpeechBackend(renderer.render)
    await asyncio.to_thread(backend.prepare, prepared_texts)
    return make_speech_executor(journal, backend)
