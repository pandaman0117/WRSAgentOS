"""远程按住说话：麦克风在打开页面的设备上，识别和 UR7e 在本机。

先运行 05_start_wrs_voice.py。用 qwen-asr 环境启动本文件。
本机或 SSH 端口转发打开 http://127.0.0.1:8010 （浏览器把这当成本机，可以直接用麦克风）。
同一局域网的其他设备打开 https://<本机地址>:8443 ，首次需信任 .local/remote-mic 里的证书。
Zenoh 仍只在 127.0.0.1。页面只接收一段 16 kHz 单声道浮点音频，不把音频送进控制总线。
"""

import asyncio
import json
import ssl
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np

from examples._session import use_local_token
from examples.voice.commands import COMMANDS, normalize
from wrs_agent import System, step
from wrs_agent.policy import text_intent
from wrs_agent.schemas import TERMINAL, TextInput
from wrs_agent.nodes.asr.qwen import QwenASR

CONFIG = Path(__file__).with_name("wrs_bindings.toml")
CERT_DIR = Path(__file__).resolve().parents[2] / ".local/remote-mic"
HTTP_PORT = 8010
HTTPS_PORT = 8443
RATE = 16000
MAX_SECONDS = 4.0
MIN_SECONDS = 0.2

PAGE = """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>远程语音控制</title>
<style>
  body { font-family: sans-serif; margin: 24px; background: #f2f2f0; color: #222; }
  button { font-size: 28px; padding: 28px 18px; width: 100%; max-width: 420px;
           border: 0; border-radius: 12px; background: #167464; color: white; }
  button.held { background: #b45309; }
  p { max-width: 42rem; line-height: 1.5; }
  #status { font-weight: 600; }
</style>
</head>
<body>
<h1>远程语音控制 UR7e</h1>
<p>按住按钮说话，松开后识别。麦克风用的是这台设备，机械臂在运行页面服务的那台机器上。</p>
<button id="talk" type="button">按住说话</button>
<p id="status">待命</p>
<p id="heard">最近识别：（无）</p>
<p id="words"></p>
<script>
const button = document.getElementById("talk");
const statusEl = document.getElementById("status");
const heardEl = document.getElementById("heard");
const words = document.getElementById("words");
const RATE = 16000;
const MAX_SAMPLES = RATE * 4;
let audioCtx, source, processor, stream, chunks, held = false, stopRequested = false;

function setStatus(text) { statusEl.textContent = text; }

function resample(input, fromRate) {
  const count = Math.round(input.length * RATE / fromRate);
  const out = new Float32Array(count);
  for (let i = 0; i < count; i++) {
    const x = i * fromRate / RATE;
    const j = Math.floor(x);
    const t = x - j;
    const a = input[Math.min(j, input.length - 1)];
    const b = input[Math.min(j + 1, input.length - 1)];
    out[i] = a + (b - a) * t;
  }
  return out;
}

async function begin(event) {
  event.preventDefault();
  if (held) return;
  stopRequested = false;
  button.classList.add("held");
  chunks = [];
  setStatus("正在听…");
  stream = await navigator.mediaDevices.getUserMedia({
    audio: { channelCount: 1, echoCancellation: true }, video: false,
  });
  if (stopRequested) {
    stream.getTracks().forEach((track) => track.stop());
    button.classList.remove("held");
    setStatus("没有完整短句，没有发送。");
    return;
  }
  audioCtx = new AudioContext();
  source = audioCtx.createMediaStreamSource(stream);
  processor = audioCtx.createScriptProcessor(4096, 1, 1);
  processor.onaudioprocess = (item) => {
    if (held) chunks.push(new Float32Array(item.inputBuffer.getChannelData(0)));
  };
  source.connect(processor);
  processor.connect(audioCtx.destination);
  held = true;
  button.setPointerCapture(event.pointerId);
  if (stopRequested) finish();
}

async function finish() {
  stopRequested = true;
  if (!held) return;
  held = false;
  button.classList.remove("held");
  processor.disconnect();
  source.disconnect();
  stream.getTracks().forEach((track) => track.stop());
  const rate = audioCtx.sampleRate;
  await audioCtx.close();
  const length = chunks.reduce((sum, item) => sum + item.length, 0);
  const joined = new Float32Array(length);
  let offset = 0;
  chunks.forEach((item) => { joined.set(item, offset); offset += item.length; });
  const audio = resample(joined, rate);
  if (audio.length > MAX_SAMPLES || audio.length < RATE * 0.2) {
    setStatus("没有完整短句，没有发送。请按住并说完一个指令。");
    return;
  }
  setStatus("正在识别…");
  const response = await fetch("/utterance", {
    method: "POST",
    headers: { "Content-Type": "application/octet-stream" },
    body: audio.buffer,
  });
  const body = await response.json();
  heardEl.textContent = "最近识别：" + (body.text || "（无）");
  setStatus(body.message || "没有结果");
}

button.addEventListener("pointerdown", (event) => {
  begin(event).catch((error) => {
    held = false;
    button.classList.remove("held");
    setStatus("无法使用麦克风：" + error.message);
  });
});
button.addEventListener("pointerup", () => finish().catch((error) => setStatus(error.message)));
button.addEventListener("pointercancel", () => finish());
fetch("/commands").then((response) => response.json()).then((names) => {
  words.textContent = "指令：" + names.join("、");
});
</script>
</body>
</html>
"""


def ensure_certificate(addresses):
    CERT_DIR.mkdir(parents=True, exist_ok=True)
    certificate, key = CERT_DIR / "cert.pem", CERT_DIR / "key.pem"
    names = ",".join(
        ["DNS:localhost", *[f"IP:{item}" for item in ("127.0.0.1", *addresses)]]
    )
    stamp = CERT_DIR / "names.txt"
    if certificate.is_file() and key.is_file() and stamp.is_file() and stamp.read_text() == names:
        return certificate, key
    subprocess.run(
        [
            "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
            "-keyout", str(key), "-out", str(certificate), "-days", "365",
            "-subj", "/CN=wrs-remote-mic", "-addext", f"subjectAltName={names}",
        ],
        check=True,
        capture_output=True,
    )
    stamp.write_text(names)
    return certificate, key


def local_addresses():
    import socket

    found = set()
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        probe.connect(("8.8.8.8", 80))
        found.add(probe.getsockname()[0])
        probe.close()
    except OSError:
        pass
    return sorted(found)


class RemoteMic:
    def __init__(self, loop, system, recognizer):
        self.loop, self.system, self.recognizer = loop, system, recognizer
        self.lock = asyncio.Lock()

    def serve(self):
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt, *args):
                print(f"[remote-mic] {self.address_string()} {fmt % args}", flush=True)

            def _send(self, status, body, content_type):
                data = body if isinstance(body, bytes) else body.encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                if self.path.split("?", 1)[0] == "/commands":
                    names = [*COMMANDS, "停止", "停止播报", "状态"]
                    self._send(200, json.dumps(names, ensure_ascii=False), "application/json")
                    return
                if self.path.split("?", 1)[0] not in {"/", "/index.html"}:
                    self._send(404, "not found", "text/plain; charset=utf-8")
                    return
                self._send(200, PAGE, "text/html; charset=utf-8")

            def do_POST(self):
                if self.path.split("?", 1)[0] != "/utterance":
                    self._send(404, "not found", "text/plain; charset=utf-8")
                    return
                length = int(self.headers.get("Content-Length", "0") or 0)
                body = self.rfile.read(length) if length else b""
                future = asyncio.run_coroutine_threadsafe(owner.accept(body), owner.loop)
                try:
                    result = future.result(timeout=60)
                    status = 200
                except Exception as exc:
                    result = {"ok": False, "text": "", "message": f"识别失败：{exc.__class__.__name__}"}
                    status = 500
                self._send(status, json.dumps(result, ensure_ascii=False), "application/json; charset=utf-8")

        def launch(server):
            thread = threading.Thread(target=server.serve_forever, name="remote-mic", daemon=True)
            thread.start()
            return server

        http = ThreadingHTTPServer(("127.0.0.1", HTTP_PORT), Handler)
        addresses = local_addresses()
        certificate, key = ensure_certificate(addresses)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(certificate, key)
        https = ThreadingHTTPServer(("0.0.0.0", HTTPS_PORT), Handler)
        https.socket = context.wrap_socket(https.socket, server_side=True)
        return launch(http), launch(https), addresses

    async def accept(self, body):
        if len(body) % 4 or not 0 < len(body) <= int(RATE * MAX_SECONDS) * 4:
            return {"ok": False, "text": "", "message": "音频长度无效，没有执行动作。"}
        audio = np.frombuffer(body, dtype="<f4")
        if not np.isfinite(audio).all() or audio.size < RATE * MIN_SECONDS:
            return {"ok": False, "text": "", "message": "没有完整短句，没有执行动作。"}
        async with self.lock:
            captured = await self.system.snapshot(node="wrs")
            transcript = await asyncio.to_thread(self.recognizer.transcribe, audio)
            message = await apply_command(self.system, transcript.text, captured)
            print(f"识别：{transcript.text}；{message}", flush=True)
            return {"ok": True, "text": transcript.text, "message": message}


async def apply_command(system, text, captured):
    """Same admission rules as 06_push_to_talk.dispatch; returns the sentence shown on the page."""
    text = normalize(text)
    if not text:
        return "没有识别到文字，没有执行动作。"
    intent, _ = text_intent(TextInput(text=text))
    if intent in {"stop", "cancel_tts", "query"}:
        receipt = await system.send_text(text)
        detail = f"控制结果：{receipt.disposition}，受理 {receipt.accepted}"
        if receipt.phase:
            detail += f"，阶段 {receipt.phase}"
        return detail
    if text not in COMMANDS:
        return "未匹配完整指令，没有执行动作。支持：" + "、".join([*COMMANDS, "停止", "状态"])
    current = await system.snapshot(node="wrs")
    if (current.boot_id, current.control_epoch) != (captured.boot_id, captured.control_epoch):
        return "收音期间控制权限已变化，请重新说指令。"
    overview = await system.status()
    if overview["task_id"] and overview["state"] not in TERMINAL:
        return "任务仍在执行或停止确认中；请先说“停止”，确认结束后再给新指令。"
    if current.admission == "UNKNOWN" or not current.stop_confirmed:
        return "机器人状态未确认，拒绝新动作。"
    if current.admission == "HELD":
        receipt = await system.allow_actions(node="wrs")
        if not receipt.accepted:
            return f"未能允许新任务：{receipt.reason}"
    skill, parameters, speech = COMMANDS[text]
    task = await system.start(step(skill, **parameters), step("speak", text=speech))
    return f"新任务 {task.id}：{speech} 运动与播报并行，可继续说“停止”。"


async def main():
    print("加载 Qwen3-ASR 0.6B 并预热，语言固定为中文……", flush=True)
    recognizer = await asyncio.to_thread(
        QwenASR, vocabulary=[*COMMANDS, "停止", "停止播报", "状态"],
    )
    await asyncio.to_thread(recognizer.warmup)
    async with System.connect(
        "tcp/127.0.0.1:7449", env_id="wrs-demo", bindings=CONFIG,
    ) as system:
        remote = RemoteMic(asyncio.get_running_loop(), system, recognizer)
        _http, _https, addresses = remote.serve()
        print(f"本机或 SSH 转发：http://127.0.0.1:{HTTP_PORT}", flush=True)
        for address in addresses:
            print(f"局域网：https://{address}:{HTTPS_PORT}", flush=True)
        print("指令：", "、".join([*COMMANDS, "停止", "停止播报", "状态"]), flush=True)
        await asyncio.Event().wait()


if __name__ == "__main__":
    use_local_token("wrs")
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("已停止远程收音；远端任务未自动取消。")
