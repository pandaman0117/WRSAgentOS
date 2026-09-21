"""执行过程中询问进度，不打断任务。"""

from wrs_agent import launch, step

if __name__ == "__main__":
    with launch(backend="wrs", duration=1.0) as system:
        task = system.start(step("move_named_pose", pose="B"))
        answer = system.send_text("做到哪一步了")

        print("识别意图：", answer.disposition)
        print("当前任务：", answer.overview["state"])
        print("任务结果：", task.wait().state)
