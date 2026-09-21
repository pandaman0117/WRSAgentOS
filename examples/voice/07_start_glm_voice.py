"""终端一：启动在线 GLM 语音任务系统；本例可产生模型费用，凭据来自环境。"""

import asyncio
from pathlib import Path

from examples._session import use_local_token
from wrs_agent import ActionState
from wrs_agent.planner.providers.glm import GLMClient, GLMConfig, GLMError
from wrs_agent.processes import LocalStack

CONFIG = Path(__file__).with_name("wrs_bindings.toml")
GREETING = "语音任务系统已启动。"


async def main():
    # 先验证配置与凭据；这里只构造/关闭客户端，不发送模型请求。
    try:
        config = GLMConfig.from_env()
        validation = GLMClient(config, live_model=True)
    except GLMError as exc:
        raise SystemExit(f"GLM 配置错误：{exc.error.message}") from None
    await validation.aclose()
    print("加载 WRS 与 Qwen TTS，启动后会播放提示。", flush=True)
    async with LocalStack(
        backend="wrs", bindings=CONFIG, duration=4.0,
        port=7451, env_id="voice-goal",
        model_provider="glm", live_model=True,
        tts_backend="qwen", tts_prepared_texts=[GREETING],
    ) as stack:
        system = stack.system
        greeting = await system.action("speak", text=GREETING)
        result = await greeting.wait(timeout=30)
        if result.state != ActionState.SUCCEEDED:
            raise RuntimeError(f"启动播报未完成：{result.state}，{result.reason}")
        print("就绪：运行 08_listen_goals.py 收音，09_viewer.py 显示 WRS。", flush=True)
        print("未配置在线模型时直接退出，不会改用 Mock Planner。", flush=True)
        await asyncio.Event().wait()


if __name__ == "__main__":
    use_local_token("voice", create=True)
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("在线语音任务系统已关闭。")
