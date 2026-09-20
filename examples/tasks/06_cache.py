"""在相同状态下重复同一目标，观察计划缓存减少模型调用。"""

from wrs_agent import launch

if __name__ == "__main__":
    with launch(duration=0.05) as system:
        # 先让 A 位于 B，使下面两次任务的起始条件一致。
        system.action("pick", object="A").wait()
        system.action("place", object="A", target="B").wait()

        first = system.goal("put A in B").wait()
        print("第一次任务：", first.task.wait().state)
        print("第一次规划后，模型调用：", system.status()["planner_calls"])

        second = system.goal("put A in B").wait()
        print("第二次任务：", second.task.wait().state)
        print("第二次规划后，模型调用：", system.status()["planner_calls"])
        print("缓存命中次数：", system.status()["cache_hits"])
