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
        for name, text in (("up", "向上。"), ("stop", "停止。")):
            started = time.perf_counter()
            wave, rate = model.render(text, threading.Event())
            elapsed = time.perf_counter() - started
            sf.write(directory / f"{name}.wav", wave, rate)
            results.append({"text": text, "seconds": elapsed, "audio_seconds": len(wave) / rate})
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
