"""终端二：连接 01_start_system.py，完成播报后只关闭客户端。"""

from pathlib import Path

from wrs_agent import connect

BINDINGS = Path(__file__).resolve().parents[2] / "configs/tts.toml"

if __name__ == "__main__":
    with connect("tcp/127.0.0.1:7447", env_id="connect-demo", bindings=BINDINGS) as system:
        speech = system.action("speak", text="客户端已连接。")
        print("播报结果：", speech.wait().state)
        print("客户端退出后，TTS 服务继续运行。")
