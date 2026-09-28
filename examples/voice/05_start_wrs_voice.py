"""终端一：真实 WRS + Qwen TTS + Runtime + Voice；先完成语音安装和模型下载。"""

import asyncio
from pathlib import Path

from examples._session import use_local_token
from examples.voice.commands import COMMANDS
from wrs_agent import ActionState, System

CONFIG = Path(__file__).with_name("wrs_bindings.toml")
GREETING = "语音播报节点已启动。"


async def main():
    print("正在加载 Qwen TTS 并预合成短句；就绪前会播放启动提示。", flush=True)
    async with System.launch(
        backend="wrs",
        bindings=CONFIG,
        port=7449,
        env_id="wrs-demo",
        duration=4.0,  # 将仿真运动展开为 4 秒，便于观察运动中语音取消。
        tts_backend="qwen",
        tts_prepared_texts=[GREETING, *(speech for _, _, speech in COMMANDS.values())],
    ) as system:
        greeting = await system.action("speak", text=GREETING)
        result = await greeting.wait(timeout=30)
        if result.state != ActionState.SUCCEEDED:
            raise RuntimeError(f"启动播报未完成：{result.state}，{result.reason}")
        robot = await system.snapshot(node="wrs")
        speaker = await system.clients["tts"].features()
        # 带历史去重日志重启时准入为 HELD；06 收到明确运动指令后才 allow_actions。
        print("WRS 准入：", robot.admission, flush=True)
        print("播报后端：", speaker.backend, flush=True)
        print("就绪：tcp/127.0.0.1:7449，env wrs-demo。", flush=True)
        print(
            "另开终端从仓库根目录运行 examples/wrs/07_viewer.py（http://127.0.0.1:8000）"
            "和 examples/voice/06_push_to_talk.py（需要 ASR 环境）。",
            flush=True,
        )
        await asyncio.Event().wait()


if __name__ == "__main__":
    use_local_token("wrs", create=True)
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("语音系统已关闭。")
