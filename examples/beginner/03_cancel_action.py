"""取消一段 Mock 播报。Mock 不会实际发出声音。"""

import time

from wrs_agent import launch

if __name__ == "__main__":
    with launch(duration=2.0) as system:
        speech = system.action("speak", text="这是一段可以被取消的播报。")
        time.sleep(0.2)

        receipt = speech.cancel()
        print("取消受理：", receipt.accepted, receipt.phase)
        print("动作结果：", speech.wait().state)
