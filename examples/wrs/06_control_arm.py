"""连接已有 WRS 节点：上、下、左、右各走 2 cm；可在另一终端打开 viewer。"""

from pathlib import Path

from examples._session import use_local_token
from wrs_agent import TaskState, connect, step

CONFIG = Path(__file__).with_name("bindings.toml")

if __name__ == "__main__":
    use_local_token("wrs")
    with connect("tcp/127.0.0.1:7449", env_id="wrs-demo", bindings=CONFIG) as system:
        snapshot = system.snapshot(node="wrs")
        if snapshot.admission == "HELD" and snapshot.stop_confirmed:
            # 仿真节点带历史日志重启后，显式允许新动作；不恢复旧任务。
            receipt = system.allow_actions(node="wrs")
            if not receipt.accepted:
                raise RuntimeError(receipt.reason)

        ready = step("move_named_pose", pose="B")
        up = step("move_relative", dz=0.02, after=ready)
        down = step("move_relative", dz=-0.02, after=up)
        left = step("move_relative", dy=0.02, after=down)
        right = step("move_relative", dy=-0.02, after=left)
        task = system.start(ready, up, down, left, right)
        result = task.wait(timeout=20)
        print("任务结果：", result.state)
        print("TCP 位置：", system.snapshot().data.robot.kinematics.tcp_pos)
        if result.state != TaskState.SUCCEEDED:
            raise RuntimeError(result.reason)
