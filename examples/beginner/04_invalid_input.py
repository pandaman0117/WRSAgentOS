"""读取一次被拒绝的调用所返回的错误。"""

from wrs_agent import AgentError, launch

if __name__ == "__main__":
    with launch(backend="wrs") as system:
        try:
            system.action("move_named_pose", pose="不存在的位置")
        except AgentError as error:
            print("错误代码：", error.code)
            print("错误说明：", error.error.message)
