"""终端三：中文语音控制 WRS；使用 qwen-asr 环境运行，建议戴耳机避免回声。"""

import asyncio
import time
from pathlib import Path

from examples._session import use_local_token
from examples.voice.commands import COMMANDS, normalize
from wrs_agent import System, step
from wrs_agent.policy import text_intent
from wrs_agent.schemas import TERMINAL, TextInput
from wrs_agent.speech.asr import QwenASR, record_command

CONFIG = Path(__file__).with_name("wrs_bindings.toml")


async def dispatch(system, text, captured):
    text = normalize(text)
    if not text:
        print("没有识别到文字，没有执行动作。")
        return
    intent, _ = text_intent(TextInput(text=text))
    if intent in {"stop", "cancel_tts", "query"}:
        # 确定的停止直接走 Voice 控制入口，不等待 Planner、运动或 TTS。
        receipt = await system.send_text(text)
        print("控制结果：", receipt.disposition, receipt.accepted, receipt.phase)
        if receipt.overview is not None:
            print("任务状态：", receipt.overview["state"], "任务：", receipt.overview["task_id"])
        if receipt.phase == "STOPPING":
            print("停止已受理，仍在等待资源停止确认；可说“状态”查询。")
        return
    if text not in COMMANDS:
        print("未匹配完整指令，没有执行动作。支持：", "、".join(COMMANDS), "、停止、状态")
        return
    current = await system.snapshot(node="wrs")
    if (current.boot_id, current.control_epoch) != (captured.boot_id, captured.control_epoch):
        print("收音期间控制权限已变化，请重新说指令。")
        return
    overview = await system.status()
    if overview["task_id"] and overview["state"] not in TERMINAL:
        print("任务仍在执行/停止确认中；请先说“停止”，确认结束后再给新指令。")
        return
    if current.admission == "UNKNOWN" or not current.stop_confirmed:
        print("机器人状态未确认，拒绝新动作。")
        return
    if current.admission == "HELD":
        # 新的一句明确运动指令允许新任务；旧任务永远不会续跑。
        receipt = await system.allow_actions(node="wrs")
        if not receipt.accepted:
            print("未能允许新任务：", receipt.reason)
            return
    skill, parameters, speech = COMMANDS[text]
    motion = step(skill, **parameters)
    announcement = step("speak", text=speech)
    task = await system.start(motion, announcement)
    print("新任务：", task.id, "；运动与播报并行，可继续说“停止”。")
    # 不在这里 task.wait()，下一次语音输入必须能在运动中进入。


async def main():
    print("加载 Qwen3-ASR 0.6B 并预热，语言固定为中文……", flush=True)
    recognizer = await asyncio.to_thread(
        QwenASR, vocabulary=[*COMMANDS, "停止", "停止播报", "状态"],
    )
    await asyncio.to_thread(recognizer.warmup)
    async with System.connect(
        "tcp/127.0.0.1:7449", env_id="wrs-demo", bindings=CONFIG,
    ) as system:
        print("回车开始说话，短暂停顿后识别；输入 s 直接停止，q 结束观察。")
        print("指令：", "、".join(COMMANDS), "、停止、停止播报、状态")
        while True:
            choice = await asyncio.to_thread(input, "准备好后按回车 > ")
            if choice.strip().lower() == "q":
                break  # 客户端退出不取消远端任务。
            if choice.strip().lower() == "s":
                print(await system.send_text("停止"))
                continue
            captured = await system.snapshot(node="wrs")
            print("请说话（最多 3 秒，不保存录音）……", flush=True)
            audio = await asyncio.to_thread(record_command)
            if audio is None:
                print("没有完整短句；没有发送指令。")
                continue
            transcript = await asyncio.to_thread(recognizer.transcribe, audio)
            print(f"识别：{transcript.text}；推理 {transcript.inference_seconds:.3f} 秒")
            started = time.perf_counter()
            await dispatch(system, transcript.text, captured)
            print(f"指令处理 {time.perf_counter() - started:.3f} 秒（不代表物理停止耗时）")


if __name__ == "__main__":
    use_local_token("wrs")
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("已停止收音；远端任务未自动取消。")
