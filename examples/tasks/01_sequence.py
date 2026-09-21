"""WRS 机械臂先到 B，再向上移动 2 cm；after 指定先后关系。"""

from wrs_agent import launch, step

if __name__ == "__main__":
    with launch(backend="wrs") as system:
        ready = step("move_named_pose", pose="B")
        upward = step("move_relative", dz=0.02, after=ready)
        observe = step("observe", after=upward)

        task = system.start(ready, upward, observe)
        print("任务结果：", task.wait().state)
        print("TCP 位置：", system.snapshot().data.robot.kinematics.tcp_pos)
