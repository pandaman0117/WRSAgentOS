"""终端四：直接调用独立 Speaker 节点上的 greet 技能。"""

from pathlib import Path

from examples.nodes.greet_skill import register_greet
from wrs_agent import connect

BINDINGS = Path(__file__).with_name("bindings.toml")

if __name__ == "__main__":
    register_greet()
    with connect("tcp/127.0.0.1:7448", env_id="node-demo", bindings=BINDINGS) as system:
        greeting = system.action("greet", name="小明")
        print("问候结果：", greeting.wait().state)
