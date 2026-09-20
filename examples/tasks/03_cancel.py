"""取消旧任务，确认结束后再启动一项独立的新任务。"""

from wrs_agent import TaskState, launch, step

if __name__ == "__main__":
    with launch(duration=1.0) as system:
        task = system.start(step("move_named_pose", pose="B"))
        for status in task.watch():
            if status.active_actions:
                break

        receipt = task.cancel()
        print("取消受理：", receipt.accepted, receipt.phase)
        stopped = task.wait()
        print("旧任务：", stopped.state)

        if stopped.state == TaskState.CANCELLED:
            next_task = system.start(step("move_named_pose", pose="C"))
            print("新任务：", next_task.wait().state)
            print("旧句柄仍指向：", task.status().state)
