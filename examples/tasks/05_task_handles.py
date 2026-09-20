"""Cancel, wait for the original result, then start an independent task."""

from wrs_agent import launch, step


def main():
    with launch(duration=0.2) as system:
        task = system.start(step("move_named_pose", pose="B"))
        receipt = task.cancel()
        assert receipt.accepted, receipt
        # STOPPING acknowledges cancellation. Wait before submitting new work.
        assert task.wait().state == "CANCELLED"
        next_task = system.start(step("move_named_pose", pose="C"))
        assert next_task.wait().state == "SUCCEEDED"
        assert next_task.id != task.id
        assert system.task(task.id).status().state == "CANCELLED"
        print("old", task.status().state, "new", next_task.status().state)
        # Planning and execution have different identities and separate waits.
        planned = system.goal("put A in B").wait()
        assert planned.task is not None, planned
        print("planned task", planned.task.wait().state)


if __name__ == "__main__":
    main()
