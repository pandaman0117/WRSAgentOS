"""终端一：启动常驻 Mock TTS。先设置 WRS_AGENT_TOKEN，再运行本文件。"""

import asyncio
import os
from pathlib import Path

from wrs_agent import System

BINDINGS = Path(__file__).resolve().parents[2] / "configs/tts.toml"


async def main():
    if not os.environ.get("WRS_AGENT_TOKEN"):
        raise SystemExit("请在两个终端中设置相同的 WRS_AGENT_TOKEN，长度至少 16 字符。")

    async with System.launch(bindings=BINDINGS, port=7447, env_id="connect-demo"):
        print("TTS 已就绪，请运行 02_client.py；Ctrl+C 退出。", flush=True)
        await asyncio.Event().wait()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("服务已关闭。")
