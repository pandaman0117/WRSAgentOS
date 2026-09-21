"""显示一项任务的状态变化；停止观察不会取消任务。"""

from wrs_agent import launch, step

if __name__ == "__main__":
    with launch(backend="wrs", duration=0.5) as system:
        first = step("move_named_pose", pose="B")
        second = step("move_named_pose", pose="C", after=first)
        task = system.start(first, second)

        for status in task.watch():
            print("任务状态：", status.state, "步骤结果：", status.steps)
