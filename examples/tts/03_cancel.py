"""终端二：取消正在合成或播放的语音；等待确认，不把受理当作已经停止。"""

import time
from pathlib import Path

from examples._session import use_local_token
from wrs_agent import ActionState, connect

CONFIG = Path(__file__).resolve().parents[2] / "configs/tts.toml"

if __name__ == "__main__":
    use_local_token("tts")
    with connect("tcp/127.0.0.1:7450", env_id="tts-demo", bindings=CONFIG) as system:
        speech = system.action(
            "speak",
            text="这是一段可以被取消的播报。合成和播放都在独立节点里进行，客户端可以请求停止。",
        )
        deadline = time.monotonic() + 10
        while speech.status().state == ActionState.ACCEPTED:
            if time.monotonic() >= deadline:
                raise TimeoutError("等待动作进入执行超时；未自动取消远端动作。")
            time.sleep(0.02)
        time.sleep(0.5)  # 此时可能还在合成，不假定扬声器已经发声。
        receipt = speech.cancel()
        print("取消受理：", receipt.accepted, receipt.phase)
        result = speech.wait(timeout=30)
        print("最终状态：", result.state, result.reason)
        print("停止已确认：", system.snapshot(node="tts").stop_confirmed)
