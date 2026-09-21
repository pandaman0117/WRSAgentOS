"""终端二：向已就绪的独立 TTS 节点提交一句真实播报。"""

from pathlib import Path

from examples._session import use_local_token
from wrs_agent import connect

CONFIG = Path(__file__).resolve().parents[2] / "configs/tts.toml"

if __name__ == "__main__":
    use_local_token("tts")
    with connect("tcp/127.0.0.1:7450", env_id="tts-demo", bindings=CONFIG) as system:
        print("节点状态：", system.nodes()["tts"]["health"])
        speech = system.action("speak", text="你好，这是通过独立节点播放的中文语音。")
        print("动作编号：", speech.id)
        print("受理结果：", speech.receipt.accepted)
        result = speech.wait(timeout=60)
        print("播报结果：", result.state, result.reason)
        print("已完成播报次数：", system.snapshot(node="tts").data.completed)
