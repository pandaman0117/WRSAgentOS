"""“别说了”只取消播报，机器人动作继续。"""

import time

from wrs_agent import launch

if __name__ == "__main__":
    with launch(backend="wrs", duration=2.0) as system:
        motion = system.action("move_named_pose", pose="B")
        speech = system.action("speak", text="我正在向 B 移动。")
        time.sleep(0.2)

        receipt = system.send_text("别说了", input_id="quiet-001")
        print("识别意图：", receipt.disposition)
        print("播报结果：", speech.wait().state)
        print("机器人结果：", motion.wait().state)
