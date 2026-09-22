"""本例只接受这些完整中文指令；参数是世界坐标系米，不做模糊匹配。"""

import unicodedata

# 指令 -> 技能、参数、播报；播报与运动并行，不承诺运动已经成功。
COMMANDS = {
    "向上": ("move_relative", {"dz": 0.02}, "正在上移。"),
    "向下": ("move_relative", {"dz": -0.02}, "正在下移。"),
    "向左": ("move_relative", {"dy": 0.02}, "正在左移。"),
    "向右": ("move_relative", {"dy": -0.02}, "正在右移。"),
    "向前": ("move_relative", {"dx": 0.02}, "正在前移。"),
    "向后": ("move_relative", {"dx": -0.02}, "正在后移。"),
    "回到初始位置": ("move_named_pose", {"pose": "home"}, "正在回到初始位置。"),
}


def normalize(text):
    return unicodedata.normalize("NFKC", text).strip().rstrip("。.!！?？")


def addressed_text(text):
    """常开麦克风的循环收音用：普通目标需称呼“机器人”。

    前缀在这里兼两个作用：区分“在对机器人下命令”和房间里的闲聊，以及挡住被麦克风
    收回来的自己的播报（没有回声消除）。按住说话不需要它——按住按钮本身就界定了
    这一句是对机器人说的。明确停止与状态查询两种都不经过唤醒判断。
    """
    from wrs_agent.policy import text_intent
    from wrs_agent.schemas import TextInput

    text = normalize(text)
    if not text:
        return None
    if text_intent(TextInput(text=text))[0] in {"stop", "cancel_tts", "query"}:
        return text
    if not text.startswith("机器人"):
        return None
    text = text[len("机器人"):].lstrip(" ，,。:：!！")
    return text or None
