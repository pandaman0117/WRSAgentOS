"""终端一：启动独立 Qwen TTS 节点，播报启动短句，然后等待客户端。"""

import asyncio
from pathlib import Path

from examples._session import use_local_token
from wrs_agent import ActionState, System

CONFIG = Path(__file__).resolve().parents[2] / "configs/tts.toml"
GREETING = "语音播报节点已启动。"


async def main():
    print("加载 Qwen TTS；首次合成用于预热，随后播放启动提示。", flush=True)
    async with System.launch(
        bindings=CONFIG,
        port=7450,
        env_id="tts-demo",
        tts_backend="qwen",
        tts_prepared_texts=[GREETING],
    ) as system:
        greeting = await system.action("speak", text=GREETING)
        result = await greeting.wait(timeout=30)
        if result.state != ActionState.SUCCEEDED:
            raise RuntimeError(f"启动播报未完成：{result.state}，{result.reason}")
        print("TTS 就绪：tcp/127.0.0.1:7450；另开终端运行 02_speak.py。", flush=True)
        print("这里只启动 Router 和 TTS，不需要 WRS、Voice 或大模型。", flush=True)
        await asyncio.Event().wait()


if __name__ == "__main__":
    use_local_token("tts", create=True)
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("TTS 节点已关闭。")
