"""终端二：循环收音，唤醒目标交给在线模型，停止走本地控制；建议使用耳机。"""

import asyncio
from pathlib import Path

from examples._session import use_local_token
from examples.voice.commands import addressed_text
from wrs_agent import AgentError, System
from wrs_agent.policy import text_intent
from wrs_agent.schemas import TERMINAL, TextInput
from wrs_agent.speech.asr import QwenASR, record_command

CONFIG = Path(__file__).with_name("wrs_bindings.toml")


async def show_result(system, request_id):
    try:
        planned = await system.planning(request_id).wait(timeout=150)
        print("规划结果：", planned.state, planned.reason, flush=True)
        if planned.task is not None:
            print("执行任务：", planned.task.id, flush=True)
            result = await planned.task.wait(timeout=120)
            print("任务结果：", result.state, result.reason, flush=True)
    except TimeoutError:
        print("观察超时；远端任务未取消，可说“停止”或“状态”。", flush=True)
    except AgentError as exc:
        print("查询失败：", exc.error.message, flush=True)


async def submit_text(system, text, captured, observing=False):
    text = addressed_text(text)
    if text is None:
        return None
    intent, reason = text_intent(TextInput(text=text))
    if intent in {"stop", "cancel_tts", "query"}:
        receipt = await system.send_text(text)
        print("控制结果：", receipt.disposition, receipt.accepted, receipt.phase, flush=True)
        if receipt.overview is not None:
            print("任务状态：", receipt.overview["state"], flush=True)
        return None
    if intent != "goal":
        print("未提交目标：", reason, flush=True)
        return None
    current = await system.snapshot(node="wrs")
    if (current.boot_id, current.control_epoch) != (captured.boot_id, captured.control_epoch):
        print("收音期间控制权限变化，请重新说目标。", flush=True)
        return None
    overview = await system.status()
    # UNKNOWN 算终态，却不表示已经确认：不知道动作有没有真的执行过。
    # Runtime 在这个状态上拒收新目标，只有停止能解开，重说多少遍都一样。
    if overview["state"] == "UNKNOWN":
        print("上一次任务结果无法确认；先说“停止”，确认结束后再说新目标。", flush=True)
        return None
    if observing or overview["planning"] == "WAITING" or (
        overview["task_id"] and overview["state"] not in TERMINAL
    ):
        print("仍有任务或规划；先停止，确认结束后再说新目标。", flush=True)
        return None
    if current.admission == "UNKNOWN" or not current.stop_confirmed:
        print("机器人状态未确认，拒绝新目标。", flush=True)
        return None
    if current.admission == "HELD":
        receipt = await system.allow_actions(node="wrs")
        if not receipt.accepted:
            print("未能允许新任务：", receipt.reason, flush=True)
            return None
    # 返回受理即继续收音；不能在收音循环里等待云端规划/运动/播报完成。
    receipt = await system.send_text(text)
    print("目标受理：", receipt.accepted, receipt.request_id, flush=True)
    return receipt.request_id


async def main():
    print("加载并预热本地 ASR；连接成功后开始循环收音。", flush=True)
    recognizer = await asyncio.to_thread(
        QwenASR, vocabulary=["机器人", "停止", "停止播报", "状态", "移动到", "初始位置"],
    )
    await asyncio.to_thread(recognizer.warmup)
    async with System.connect(
        "tcp/127.0.0.1:7451", env_id="voice-goal", bindings=CONFIG,
    ) as system:
        nodes = await system.nodes()
        if any(not entry["boot_id"] for entry in nodes.values()) or not all(
            nodes[role]["ready"] for role in ("voice", "agent")
        ):
            raise RuntimeError("请先启动 07_start_llm_voice.py 并等待就绪。")
        print("开始收音。说“机器人，移动到 B”；“停止”无需唤醒。Ctrl+C 关闭收音。", flush=True)
        print("每句最多 4 秒，不保存录音；识别期间有短暂收音间隙。", flush=True)
        observer = None
        try:
            while True:
                captured = await system.snapshot(node="wrs")
                audio = await asyncio.to_thread(record_command, max_seconds=4.0)
                if audio is None:
                    continue
                transcript = await asyncio.to_thread(recognizer.transcribe, audio)
                print(
                    f"识别：{transcript.text}（{transcript.inference_seconds:.3f} 秒）", flush=True,
                )
                try:
                    request_id = await submit_text(
                        system, transcript.text, captured,
                        observing=observer is not None and not observer.done(),
                    )
                except AgentError as exc:
                    print("提交失败：", exc.error.message, flush=True)
                    continue
                if request_id is not None:
                    # 同时只观察一项规划/任务，不累积后台任务。
                    observer = asyncio.create_task(show_result(system, request_id))
        finally:
            if observer is not None:
                observer.cancel()
                await asyncio.gather(observer, return_exceptions=True)


if __name__ == "__main__":
    use_local_token("voice")
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("收音已关闭；远端任务未自动取消。")
