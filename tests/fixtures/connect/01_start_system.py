"""Offline Mock TTS service fixture for connection and credential regressions."""

import asyncio
from pathlib import Path

from examples._session import use_local_token
from wrs_agent import System

BINDINGS = Path(__file__).resolve().parents[3] / "configs/tts.toml"


async def main():
    async with System.launch(bindings=BINDINGS, port=7447, env_id="connect-demo"):
        print("TTS 已就绪，请运行 02_client.py；Ctrl+C 退出。", flush=True)
        await asyncio.Event().wait()


if __name__ == "__main__":
    # 启动前准备共享口令，供 02_client 连接本服务。
    use_local_token("tts", create=True)
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("服务已关闭。")
