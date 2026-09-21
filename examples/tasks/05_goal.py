"""先等待 Mock Planner 生成计划，再等待任务执行完成。"""

from wrs_agent import launch

if __name__ == "__main__":
    with launch(backend="wrs") as system:
        planning = system.goal("home")
        proposed = planning.wait()
        print("规划结果：", proposed.state)

        if proposed.task is not None:
            print("任务结果：", proposed.task.wait().state)
        else:
            print("说明：", proposed.reason)
