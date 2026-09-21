"""Short Chinese utterances with resident Qwen3-ASR; no remote audio or hidden downloads."""

import os
import sys
import time
from dataclasses import dataclass
from importlib.util import find_spec
from pathlib import Path

from wrs_agent.speech.assets import model_directory, offline_cuda


@dataclass(frozen=True)
class Transcript:
    text: str
    inference_seconds: float


class QwenASR:
    def __init__(self, *, vocabulary=()):
        if isinstance(vocabulary, str) or len(vocabulary) > 64:
            raise ValueError("asr_vocabulary_requires_at_most_64_words")
        if any(not isinstance(word, str) or not 0 < len(word) <= 32 for word in vocabulary):
            raise ValueError("invalid_asr_vocabulary_word")
        self.vocabulary = "、".join(vocabulary)
        if find_spec("qwen_asr") is None:
            environment = Path(__file__).resolve().parents[2] / ".local/venvs/qwen-asr"
            interpreter = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
            raise RuntimeError(
                f"qwen_asr is not installed in {sys.executable}. "
                f"Run this example with {interpreter}; "
                "prepare that environment with scripts/setup_speech.ps1 if missing."
            )
        directory = model_directory("asr")
        torch = offline_cuda()
        from qwen_asr import Qwen3ASRModel

        self.model = Qwen3ASRModel.from_pretrained(
            str(directory), device_map="cuda:0", dtype=torch.bfloat16,
            attn_implementation="sdpa", local_files_only=True,
            max_inference_batch_size=1, max_new_tokens=64,
        )

    def transcribe(self, audio, sample_rate=16000):
        import numpy as np

        audio = np.asarray(audio, dtype=np.float32)
        if audio.ndim != 1 or not 0 < len(audio) <= sample_rate * 4:
            raise ValueError("asr_requires_mono_command_at_most_4_seconds")
        if sample_rate != 16000 or not np.isfinite(audio).all():
            raise ValueError("asr_requires_finite_16khz_audio")
        started = time.perf_counter()
        results = self.model.transcribe(
            audio=(audio, sample_rate), language="Chinese",
            context="机械臂控制指令：" + self.vocabulary + "。" if self.vocabulary else "",
        )
        return Transcript(results[0].text.strip(), time.perf_counter() - started)

    def warmup(self):
        import numpy as np

        self.transcribe(np.zeros(8000, dtype=np.float32))


def record_command(*, threshold=0.015, silence_seconds=0.25, max_seconds=3.0):
    """Explicit push-to-talk session, ending after speech + silence, with no queued recordings.

    Blocking device reads belong in asyncio.to_thread(). RMS segmentation is not intent/VAD
    authority: only a complete recognized command can reach Voice. Overlong/overflowed input
    is discarded as a whole, not truncated into a potentially different command.
    """
    if not 0 < threshold < 1 or not 0 < silence_seconds < max_seconds <= 4:
        raise ValueError("invalid_microphone_segmentation_settings")
    import numpy as np
    import sounddevice as sd

    rate, block = 16000, 320
    heard, quiet, waiting = False, 0, 0
    chunks, preroll = [], []
    with sd.InputStream(samplerate=rate, channels=1, dtype="float32", blocksize=block) as stream:
        while True:
            audio, overflowed = stream.read(block)
            if overflowed:
                raise RuntimeError("microphone_overflow: utterance_discarded")
            loud = float(np.sqrt(np.mean(audio ** 2))) >= threshold
            if not heard:
                preroll = [*preroll[-4:], audio.copy()]
                waiting += block
                if not loud:
                    if waiting >= rate * 5:
                        return None
                    continue
                heard = True
                chunks.extend(preroll)
            else:
                chunks.append(audio.copy())
            quiet = 0 if loud else quiet + block
            if len(chunks) * block >= rate * max_seconds:
                return None
            if quiet >= rate * silence_seconds:
                return np.concatenate(chunks).reshape(-1)
