"""查看当前系统能做哪些事，不执行动作。"""

from wrs_agent import launch

if __name__ == "__main__":
    with launch(backend="wrs") as system:
        for skill in system.skills():
            print(skill.name, "版本", skill.version, "—", skill.description)
