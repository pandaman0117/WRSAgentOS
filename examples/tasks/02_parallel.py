"""让 Mock 机器人运动与 Mock 播报同时进行。"""

from wrs_agent import launch, step

if __name__ == "__main__":
    with launch(duration=1.0) as system:
        # 不同节点、没有 after 依赖，因此两步可以并行。
        motion = step("move_named_pose", pose="B")
        speech = step("speak", text="我正在移动。")
        task = system.start(motion, speech)

        for status in task.watch():
            print("正在执行的动作数量：", len(status.active_actions))
        print("任务结果：", task.status().state)
