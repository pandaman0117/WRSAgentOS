"""真实 WRS IK/FK：到 B 后，上、下、左、右各移动 2 cm。"""

from wrs_agent import ActionState, launch

if __name__ == "__main__":
    with launch(backend="wrs") as system:
        ready = system.action("move_named_pose", pose="B").wait()
        if ready.state != ActionState.SUCCEEDED:
            raise RuntimeError(ready.reason)

        for direction, offset in (
            ("上", {"dz": 0.02}),
            ("下", {"dz": -0.02}),
            ("左", {"dy": 0.02}),
            ("右", {"dy": -0.02}),
        ):
            result = system.action("move_relative", **offset).wait()
            print(direction, result.state, system.snapshot().data.robot.kinematics.tcp_pos)
            if result.state != ActionState.SUCCEEDED:
                raise RuntimeError(result.reason)
