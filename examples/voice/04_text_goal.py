"""把一句完整文字交给 Mock Planner，取得任务并等待结果。"""

from wrs_agent import launch

if __name__ == "__main__":
    with launch() as system:
        receipt = system.send_text("put A in B", input_id="goal-001")
        proposed = system.planning(receipt.request_id).wait()
        print("规划结果：", proposed.state)

        if proposed.task is not None:
            print("任务结果：", proposed.task.wait().state)
        else:
            print("说明：", proposed.reason)
