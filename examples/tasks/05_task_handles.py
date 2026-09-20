"""Task handles stay attached to the original execution after replacement."""

from wrs_agent import launch, step


def main():
    with launch(duration=0.2) as system:
        task = system.start(step("move_named_pose", pose="B"))
        receipt = task.hold()
        assert receipt.accepted, receipt
        # STOPPING is an acceptance receipt; replacement waits for stop confirmation.
        replacement = task.replace(step("move_named_pose", pose="C"))
        assert replacement.wait().state == "SUCCEEDED"
        assert task.wait().state == "CANCELLED"
        assert system.task(task.id).status().task_id == task.id
        print("old", task.status().state, "new", replacement.status().state)
        # Planning and execution have different identities and separate waits.
        planned = system.goal("put A in B").wait()
        assert planned.task is not None, planned
        print("planned task", planned.task.wait().state)


if __name__ == "__main__":
    main()
