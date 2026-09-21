"""终端四：调用 greet；先启动 Router/Speaker，自动读取本组示例口令。"""

from pathlib import Path

from examples._session import use_local_token
from examples.nodes.greet_skill import register_greet
from wrs_agent import connect

BINDINGS = Path(__file__).with_name("bindings.toml")

if __name__ == "__main__":
    use_local_token("nodes")
    register_greet()
    with connect("tcp/127.0.0.1:7448", env_id="node-demo", bindings=BINDINGS) as system:
        greeting = system.action("greet", name="小明")
        print("问候结果：", greeting.wait().state)
