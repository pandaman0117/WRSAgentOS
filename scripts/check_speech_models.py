"""Opt-in local model probe: no microphone, playback, network, API keys or robot commands."""

import argparse
import json
import threading
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("component", choices=["tts", "asr"])
    args = parser.parse_args()
    import torch

    directory = Path(".local/speech-check")
    directory.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    results = []
    if args.component == "tts":
        import soundfile as sf

        from wrs_agent.speech.tts import QwenTTS

        model = QwenTTS()
        loaded = time.perf_counter() - started
        # Warm up before measuring; otherwise the first sample is charged for CUDA
        # initialisation and hides the steady-state cost, as it did before this probe.
        model.render("预热。", threading.Event())
        samples = (
            ("up", "向上。"),
            ("stop", "停止。"),
            # A long utterance of the kind the planner actually produces: only comparing it
            # against the short ones separates per-call overhead from per-token decoding.
            ("long", "当前机械臂六个关节角为：约0.00弧度、0.36弧度、0.49弧度、0.00弧度。"),
        )
        for name, text in samples:
            span = {"steps": 0, "first": None, "last": None}

            def count(module, inputs, span=span):
                now = time.perf_counter()
                if span["first"] is None:
                    span["first"] = now
                span["last"] = now
                span["steps"] += 1

            hook = model.model.model.talker.register_forward_pre_hook(count)
            started = time.perf_counter()
            try:
                wave, rate = model.render(text, threading.Event())
            finally:
                hook.remove()
            finished = time.perf_counter()
            sf.write(directory / f"{name}.wav", wave, rate)
            audio_seconds = len(wave) / rate
            results.append({
                "text": text,
                "characters": len(text),
                "seconds": finished - started,
                "audio_seconds": audio_seconds,
                "slower_than_realtime": (finished - started) / audio_seconds,
                "talker_steps": span["steps"],
                # Three spans that add up to the total: everything before the first talker
                # forward, the decode loop itself, and turning audio tokens back to a waveform.
                "before_decode": span["first"] - started,
                "decode": span["last"] - span["first"],
                "after_decode": finished - span["last"],
            })
    else:
        import soundfile as sf
        from scipy.signal import resample_poly

        from wrs_agent.speech.asr import QwenASR

        model = QwenASR(vocabulary=[
            "向上", "向下", "向左", "向右", "向前", "向后", "回到初始位置",
            "停止", "停止播报", "状态",
        ])
        loaded = time.perf_counter() - started
        model.warmup()
        for name in ("up", "stop"):
            wave, rate = sf.read(directory / f"{name}.wav", dtype="float32")
            wave = resample_poly(wave, 16000, rate)
            result = model.transcribe(wave)
            results.append({"sample": name, "text": result.text,
                            "seconds": result.inference_seconds,
                            "exact_match": result.text.rstrip("。.!！") == {
                                "up": "向上", "stop": "停止"}[name]})
    report = {"component": args.component, "gpu": torch.cuda.get_device_name(),
              "torch": torch.__version__, "load_seconds": loaded, "samples": results,
              "peak_allocated_mib": torch.cuda.max_memory_allocated() / 1024**2,
              "audio_devices_tested": False}
    output = json.dumps(report, ensure_ascii=False, indent=2)
    (directory / f"{args.component}.json").write_text(output + "\n", encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
