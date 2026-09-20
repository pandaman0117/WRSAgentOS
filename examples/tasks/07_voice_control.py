"""ASR/UI handoff: recognized text in, scoped control or a planning receipt out."""

from wrs_agent import launch, step


def main():
    with launch(duration=1) as system:
        task = system.start(step("move_named_pose", pose="B"), step("speak", text="Working"))
        for state in task.watch():
            if len(state.active_actions) == 2:
                break
        print(system.send_text("做到哪一步了").overview["state"])
        assert (
            system.send_text("停止", input_id="utterance", is_final=False).disposition == "ignore"
        )
        receipt = system.send_text("停止", input_id="utterance")
        assert receipt.accepted and receipt.task_id == task.id
        print("stop accepted:", receipt.phase, "task:", task.status().state)
        # Cancellation finishes independently; submit a new goal only after confirmation.
        assert task.wait().state == "CANCELLED"
        next_task = system.start(step("move_named_pose", pose="C"))
        assert next_task.wait().state == "SUCCEEDED"
        # Stable input_id allows the caller to reconcile a lost reply without a second goal.
        goal = system.send_text("put A in B", input_id="next-goal")
        planned = system.planning(goal.request_id).wait()
        assert planned.task.wait().state == "SUCCEEDED"
        print("recognized text -> planning -> task:", planned.task.id, "SUCCEEDED")


if __name__ == "__main__":
    main()
