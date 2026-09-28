"""Microphone recording and scripted capture, without model dependencies.

record_* returns PCM audio; make_mock_capture returns scripted text directly,
matching the capture callback used by AsrNode after recognition.
"""

import time

# A lost button release must not record forever. Overlong input is discarded whole.
CAPTURE_SECONDS = 15.0


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
            loud = float(np.sqrt(np.mean(audio**2))) >= threshold
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


def record_push_to_talk(held, *, max_seconds=CAPTURE_SECONDS, min_seconds=0.2):
    """Record while the caller keeps the button down; the caller owns segmentation.

    Blocking device reads belong in asyncio.to_thread(). Releasing is the only normal end;
    max_seconds bounds a release signal that never arrives. An overlong, overflowed or
    accidental short press is discarded whole, never truncated into a different command.
    """
    if not 0 < min_seconds < max_seconds <= CAPTURE_SECONDS:
        raise ValueError("invalid_microphone_capture_settings")
    import numpy as np
    import sounddevice as sd

    rate, block = 16000, 320
    chunks = []
    with sd.InputStream(samplerate=rate, channels=1, dtype="float32", blocksize=block) as stream:
        while held():
            audio, overflowed = stream.read(block)
            if overflowed:
                raise RuntimeError("microphone_overflow: utterance_discarded")
            chunks.append(audio.copy())
            if len(chunks) * block >= rate * max_seconds:
                return None
    if len(chunks) * block < rate * min_seconds:
        return None
    return np.concatenate(chunks).reshape(-1)


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
