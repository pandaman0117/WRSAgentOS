"""Task replacement and delayed messages over real cross-process Zenoh."""

import pytest
from conftest import eventually

from wrs_agent import System, step
from wrs_agent.processes import LocalStack
from wrs_agent.schemas import Plan, new_id
from wrs_agent.transport import RemoteError

pytestmark = pytest.mark.zenoh


async def test_scoped_cancel_rejects_late_controls_and_revision_does_not_execute():
    async with System.launch(duration=0.4) as system:
        a = await system.start(step("move_named_pose", pose="B"))
        await eventually(system.snapshot, lambda w: w.active_action is not None)
        robot = system.clients["wrs"]
        old_action = (await system.snapshot()).active_action
        await eventually(lambda: robot.status(old_action), lambda s: s.state == "RUNNING")
        response = await system._transports["voice"].request(
            "request/voice/event",
            {
                "event_id": new_id(),
                "kind": "revise",
                "plan": Plan(steps=[step("move_named_pose", pose="C")]).model_dump(),
            },
        )
        assert response["disposition"] == "clarify"
        assert (await a.cancel()).accepted
        assert (await a.wait()).state == "CANCELLED"
        b = await system.start(step("move_named_pose", pose="C"))
        with pytest.raises(RemoteError, match="task_id_required"):
            await system.agent.request(
                "request/task/cancel", {"request_id": new_id()}, control=True
            )
        with pytest.raises(RemoteError, match="stale_task"):
            await system.agent.request(
                "request/task/cancel", {"request_id": new_id(), "task_id": a.id}, control=True
            )
        assert (await b.wait()).state == "SUCCEEDED"
        assert b.id != a.id and (await a.status()).state == "CANCELLED"
        assert (await robot.status(old_action)).state == "CANCELLED"
        assert (await system.snapshot()).data.pose == "C"
        assert (await robot.transport.request("request/health", {}))["executions"] == 2


async def test_late_planner_reply_cannot_replace_new_task():
    async with LocalStack(deferred=True, duration=0.2) as stack:
        system = stack.system
        ack = await system.goal("old goal")
        pending = await eventually(system.status, lambda s: s["planner_calls"] == 1)
        assert pending["task_id"] is None and pending["planning_request_id"] == ack.request_id
        new = await system.start(step("move_named_pose", pose="C"))
        await system.agent.request("request/test/planner/release", {}, control=True)
        final = await new.wait()
        assert final.task_id == new.id and final.state == "SUCCEEDED"
        overview = await system.status()
        assert overview["planning"] == "IDLE" and overview["revision"] == 0
        assert (await system.snapshot()).data.pose == "C"
        assert (await stack.system.clients["wrs"].transport.request("request/health", {}))[
            "executions"
        ] == 1
