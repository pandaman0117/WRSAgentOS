"""仅执行节点导入的 greet 技能定义与实现；客户端从节点发现合同。"""

import asyncio

from pydantic import Field

from wrs_agent.schemas import Boundary
from wrs_agent.skills import Skill


class GreetArgs(Boundary):
    name: str = Field(min_length=1, max_length=40)


async def greet(state, options: GreetArgs, stop, progress):
    text = f"你好，{options.name}！"
    for index, character in enumerate(text):
        if stop.is_set():
            return False
        print(character, end="", flush=True)
        progress((index + 1) / len(text))
        try:
            await asyncio.wait_for(stop.wait(), timeout=0.03)
        except TimeoutError:
            pass
    if stop.is_set():
        return False
    print(flush=True)
    state.completed += 1
    state.last_text = text
    return state.last_text == text


GREET = Skill(
    name="greet",
    arguments=GreetArgs,
    handler=greet,
    description="在控制台打印一句问候",
    resources=("speaker",),
    verification="console_text_complete",
)
