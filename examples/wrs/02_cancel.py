"""取消 WRS 虚拟运动，并查询它是否确认停止。"""

import time

from wrs_agent import launch

if __name__ == "__main__":
    with launch(backend="wrs", duration=2.0) as system:
        motion = system.action("move_named_pose", pose="B")
        time.sleep(0.3)

        receipt = motion.cancel()
        print("取消受理：", receipt.accepted, receipt.phase)
        print("动作结果：", motion.wait().state)
        print("停止已确认：", system.snapshot().stop_confirmed)
