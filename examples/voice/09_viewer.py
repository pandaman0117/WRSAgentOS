"""显示 WRS 关节状态，并按住说话把目标交给 GLM；与 07 分开运行。"""

from pathlib import Path

from examples._session import use_local_token
from examples.voice.commands import normalize
from wrs_agent import AgentError, connect
from wrs_agent.env.viewer import viewer_hub
from wrs_agent.env.wrs import load_wrs, sync_scene_objects
from wrs_agent.policy import text_intent
from wrs_agent.schemas import TERMINAL, TextInput, new_id
from wrs_agent.speech.asr import CAPTURE_SECONDS

CONFIG = Path(__file__).with_name("wrs_bindings.toml")
VIEWER_PORT = 8001
# 这些判定自带正文：ANSWER 是模型的回答，其余是澄清或失败原因。
# DONE/IDLE 的 reason 可能来自上一次任务，不能当成本次回复。
REPLIED = {"ANSWER", "CLARIFY", "FAILED", "STALE", "REQUIRES_CONFIRMATION"}
# ASR 回的是稳定的机器码，这里换成能照着做的话。一个码可能对应几种原因，
# 提示要把它们都说到，不能只挑最常见的那种当成唯一解释。
REASONS = {
    "no_complete_utterance": (
        f"没收到完整语音：请在 {CAPTURE_SECONDS:.0f} 秒内说完一句，"
        "超时、太短或只录到环境声都会整段丢弃，请分句重说。"
    ),
    "capture_failed": "麦克风没能录下这一段，请检查设备后重按。",
    "voice_unconfirmed": "停止已发出但未收到确认，请再按一次并确认机器人已停。",
}

if __name__ == "__main__":
    use_local_token("voice")
    wrs = load_wrs()
    world = wrs.wvw.World(
        cam_pos=(0.9, 0.9, 0.7),
        cam_lookat_pos=(0, 0, 0.25),
        port=VIEWER_PORT,
        # 这个频率也决定按钮回执多久回到页面；太低会让按钮一直显示“…”。
        hz=30,
        auto_start_hub=False,
    )
    world.set_caption("WRS Lite6 — 语音目标执行")
    robot = wrs.xarm_lite6.Lite6()
    robot.add_to_scene(world.scene)
    wrs.wssop.frame().add_to_scene(world.scene)

    with connect("tcp/127.0.0.1:7451", env_id="voice-goal", bindings=CONFIG) as system:
        initial = system.snapshot(node="wrs")
        if initial.data.robot.kinematics is None or not initial.data.robot.kinematics.valid:
            raise RuntimeError("WRS 节点没有有效的关节状态。")
        robot.fk(initial.data.robot.kinematics.qs)
        displayed = {}
        sync_scene_objects(wrs, world.scene, initial.data.objects, displayed)
        nodes = system.nodes()
        # 停止要经过 Voice，所以两个节点都就绪才值得显示收音按钮。
        if not all(nodes.get(role, {}).get("ready") for role in ("asr", "voice")):
            raise RuntimeError("asr 或 voice 节点未就绪，请先启动 07_start_glm_voice.py。")
        # 一次按住的进度；回调与刷新都在主循环线程，够用普通字典。
        # began 记住按下这个边沿：松开可能早于下一帧，不能让这次按住整个丢掉。
        press = {"id": None, "releasing": False, "held": False, "began": False,
                 "stop": False, "authority": None}
        panel = world.ui.add_panel(
            "voice",
            title="语音指令",
            description="按住“按住说话”不放，说完松开。停止按钮不经过识别。",
        )
        panel.add_label("state", value="待命", label="状态")
        panel.add_label("heard", value="（无）", label="最近识别")
        # 规划单独一块：判定、模型回复和执行情况都比一行字长。
        plan_panel = world.ui.add_panel(
            "planner",
            title="规划与执行",
            anchor=wrs.viewer.web_ui.Anchor.TOP_LEFT,
            width=330,
            description="Planner 的判定、回复与调用情况；也反映其他客户端提交的目标。",
        )
        plan_panel.add_label("verdict", value="IDLE", label="判定")
        plan_panel.add_label("reply", value="（无）", label="回复")
        plan_panel.add_label("task", value="无", label="任务")
        plan_panel.add_label("steps", value="无", label="步骤")
        # UNKNOWN 只说“无法确认”，原因在 error 里：哪个节点、哪个阶段、什么代码。
        plan_panel.add_label("fault", value="（无）", label="故障")
        plan_panel.add_label("calls", value="模型 0 次", label="调用")

        def announce(state, heard=None):
            panel.set_value("state", state)
            if heard is not None:
                panel.set_value("heard", heard or "（无）")

        def describe(exc):
            return exc.error.message if isinstance(exc, AgentError) else "节点无响应"

        def describe_fault(error):
            """UNKNOWN/FAILED 的机器可读原因：没有它，界面上只剩一个状态词。"""
            if not error:
                return "（无）"
            where = "／".join(filter(None, (error["node_id"], error["stage"])))
            return f"{error['code']}（{where}）" if where else error["code"]

        def submit(text):
            # 按住按钮本身就声明了这句是对机器人说的，不再要求唤醒前缀。
            text = normalize(text)
            if not text:
                return "未提交：没有识别到内容。"
            if text_intent(TextInput(text=text))[0] != "goal":
                receipt = system.send_text(text)
                return f"{receipt.disposition}：{receipt.accepted}"
            overview = system.status()
            # UNKNOWN 算终态，却不表示已经确认：不知道动作有没有真的执行过。
            # Runtime 在这个状态上拒收新目标，只有停止能解开，重按说话按多少次都一样。
            if overview["state"] == "UNKNOWN":
                return "上一次任务结果无法确认；先点“立即停止”，确认后再下新目标。"
            if overview["planning"] == "WAITING" or (
                overview["task_id"] and overview["state"] not in TERMINAL
            ):
                return "仍有任务或规划；先说“停止”。"
            current = system.snapshot(node="wrs")
            if current.admission == "UNKNOWN" or not current.stop_confirmed:
                return "机器人状态未确认，拒绝新目标。"
            if current.admission == "HELD" and not system.allow_actions(node="wrs").accepted:
                return "未能允许新任务。"
            receipt = system.send_text(text)
            return f"目标已受理：{receipt.request_id}" if receipt.accepted else "目标未受理。"

        def report(result, snapshot):
            if result.receipt is not None:
                # 停止由 ASR 节点直接送到 Voice，不经过本脚本。
                announce(f"停止：{result.receipt.phase}", result.text)
            elif not result.text:
                announce(REASONS.get(result.reason, f"未收到完整语音（{result.reason}）"), "")
            elif result.reason:
                announce(REASONS.get(result.reason, f"未送达：{result.reason}"), result.text)
            elif press["authority"] != (snapshot.boot_id, snapshot.control_epoch):
                announce("收音期间控制权限变化，请重说。", result.text)
            else:
                announce(submit(result.text), result.text)

        def pump(snapshot):
            """每帧最多一次请求：开始、结束，或取一次识别结果。"""
            if press["id"] is None:
                if press["held"] or press["began"]:
                    press.update(id=new_id(), began=False)
                    press["authority"] = (snapshot.boot_id, snapshot.control_epoch)
                    system.listen_begin(press["id"])
                    announce("正在录音，松开结束。", "")
                return
            if not press["releasing"]:
                if press["held"]:
                    return
                system.listen_end(press["id"])
                press["releasing"] = True
                announce("识别中…")
                return
            result = system.listen_result(press["id"])
            if result.capturing:
                return
            press.update(id=None, releasing=False)
            report(result, snapshot)

        def update(dt):
            snapshot = system.snapshot(node="wrs")
            if snapshot.boot_id != initial.boot_id:
                raise RuntimeError("WRS 节点已重启，请重新连接 viewer。")
            state = snapshot.data.robot.kinematics
            if state is None or not state.valid:
                raise RuntimeError("WRS 关节状态无法确认，停止显示。")
            # 运动命令来自 Voice / GLM / Runtime；本回调仅用关节状态刷新显示。
            robot.fk(state.qs)
            sync_scene_objects(wrs, world.scene, snapshot.data.objects, displayed)
            try:
                if press["stop"]:
                    press["stop"] = False
                    announce(f"停止：{system.send_text('停止').phase}", "停止")
                    return
                pump(snapshot)
            except (AgentError, TimeoutError) as exc:
                # 只放弃这一次按住，显示和远端任务都继续；清掉按住状态，
                # 让用户松开再按才重试，免得按着不放把超时叠起来。
                press.update(id=None, releasing=False, began=False, held=False)
                announce(f"语音失败：{describe(exc)}，松开再按重试")

        def show_progress(dt):
            """规划判定、模型回复与调用情况；也反映其他客户端提交的目标。"""
            try:
                overview = system.status()
            except (AgentError, TimeoutError) as exc:
                plan_panel.set_value("verdict", f"查询失败：{describe(exc)}")
                return
            verdict = overview["planning"]
            plan_panel.set_value("verdict", verdict)
            if verdict == "WAITING":
                plan_panel.set_value("reply", "正在规划…")
            else:
                # ANSWER 的正文是模型的回答，不是错误；其余判定给的是澄清或原因。
                replied = verdict in REPLIED and overview["reason"]
                plan_panel.set_value("reply", overview["reason"] if replied else "（无）")
            plan_panel.set_value(
                "task",
                "无"
                if overview["task_id"] is None
                else f"{overview['state']}｜{overview['task_id'][:8]}",
            )
            # steps 只含已出结果的步骤，拿不到计划总数；执行中的步骤单独标出来。
            active = "、".join(overview["active_actions"])
            done = "；".join(f"{name}={state}" for name, state in overview["steps"].items())
            plan_panel.set_value("steps", f"执行中 {active}｜{done}" if active else done or "无")
            plan_panel.set_value("fault", describe_fault(overview["error"]))
            plan_panel.set_value(
                "calls",
                f"模型 {overview['planner_calls']} 次"
                f"｜缓存命中 {overview['cache_hits']}／未命中 {overview['cache_misses']}"
                + (f"｜排队 {overview['queued']}" if overview["queued"] else ""),
            )

        def begin_hold():
            # 按住回调只记状态：录音的 RPC 放到下一帧，页面按钮不等网络往返。
            press.update(held=True, began=True)

        def end_hold():
            press["held"] = False

        def request_stop():
            # 按钮回调要立刻返回，否则页面按钮一直停在 pending；停止本身在下一帧发出。
            press["stop"] = True
            panel.set_value("state", "停止中…")

        panel.add_hold_button(
            "talk", label="按住说话", on_press=begin_hold, on_release=end_hold,
        )
        panel.add_button("stop", label="立即停止", on_click=request_stop)
        world.schedule_interval(update, 0.1)
        world.schedule_interval(show_progress, 0.3)
        try:
            # 这个帮助函数只管理页面服务，场景和刷新逻辑都在本文件。
            with viewer_hub(VIEWER_PORT):
                print(f"打开 http://127.0.0.1:{VIEWER_PORT}，Ctrl+C 退出观察。", flush=True)
                print("按住“按住说话”说“向前移动”；说“停止”会立即走控制通道。", flush=True)
                world.run()
        finally:
            world.close()  # 关闭显示不会取消远端任务。
