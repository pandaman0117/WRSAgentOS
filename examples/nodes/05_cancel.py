"""终端四：取消自定义节点正在执行的长问候。"""

import time
from pathlib import Path

from examples._session import use_local_token
from examples.nodes.greet_skill import register_greet
from wrs_agent import connect

BINDINGS = Path(__file__).with_name("bindings.toml")

if __name__ == "__main__":
    use_local_token("nodes")
    register_greet()
    with connect("tcp/127.0.0.1:7448", env_id="node-demo", bindings=BINDINGS) as system:
        greeting = system.action("greet", name="正在阅读独立节点与技能示例的开发同学")
        time.sleep(0.15)

        receipt = greeting.cancel()
        print("取消受理：", receipt.accepted, receipt.phase)
        print("问候结果：", greeting.wait().state)
