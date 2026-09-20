"""调用一次 Mock 机器人动作，等待它完成。"""

from wrs_agent import launch

if __name__ == "__main__":
    with launch() as system:
        motion = system.action("move_named_pose", pose="B")
        result = motion.wait()

        print("动作结果：", result.state)
        print("当前位置：", system.snapshot().data.pose)
