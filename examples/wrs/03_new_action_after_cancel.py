"""直接动作取消后，明确开放机器人准入，再提交一项新动作。"""

import time

from wrs_agent import ActionState, launch

if __name__ == "__main__":
    with launch(backend="wrs", duration=1.0) as system:
        motion = system.action("move_named_pose", pose="B")
        time.sleep(0.2)
        motion.cancel()
        stopped = motion.wait()
        print("旧动作：", stopped.state)

        if stopped.state == ActionState.CANCELLED:
            receipt = system.allow_actions()
            print("允许新动作：", receipt.accepted)
            if receipt.accepted:
                next_motion = system.action("move_named_pose", pose="home")
                print("新动作：", next_motion.wait().state)
