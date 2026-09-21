"""用识别后的“停止”文本打断正在执行的任务，不使用麦克风。"""

from wrs_agent import launch, step

if __name__ == "__main__":
    with launch(backend="wrs", duration=2.0) as system:
        task = system.start(step("move_named_pose", pose="B"))
        for status in task.watch():
            if status.active_actions:
                break

        # ASR 接入时，把它识别出的完整文字交给同一个入口。
        receipt = system.send_text("停止", input_id="stop-001")
        print("识别意图：", receipt.disposition)
        print("停止受理：", receipt.accepted, receipt.phase)
        print("任务结果：", task.wait().state)
