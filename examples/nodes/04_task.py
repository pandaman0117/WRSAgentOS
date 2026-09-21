"""终端四：让 Runtime 调度自定义技能，与普通任务使用同一接口。"""

from pathlib import Path

from examples._session import use_local_token
from examples.nodes.greet_skill import register_greet
from wrs_agent import connect, step

BINDINGS = Path(__file__).with_name("bindings.toml")

if __name__ == "__main__":
    use_local_token("nodes")
    register_greet()
    with connect("tcp/127.0.0.1:7448", env_id="node-demo", bindings=BINDINGS) as system:
        task = system.start(step("greet", name="开发同学"))
        print("任务结果：", task.wait().state)
