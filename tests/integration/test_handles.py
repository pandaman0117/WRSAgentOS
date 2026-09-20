"""Identity-bound handles over real Zenoh, including reconnect and process restart."""

import asyncio
import secrets

import pytest
from conftest import eventually

from wrs_agent import GoalState, System, TaskState, step
from wrs_agent.processes import LocalStack
from wrs_agent.schemas import Plan, new_id
from wrs_agent.transport import RemoteError

pytestmark = pytest.mark.zenoh


async def test_handles_cancel_and_reconnect_without_cancelling_observation(monkeypatch):
    monkeypatch.setenv("WRS_AGENT_TOKEN", secrets.token_urlsafe(32))
    async with LocalStack(duration=0.4) as stack:
        owner = stack.system
        async with System.connect(stack.endpoint, env_id=stack.env_id) as client:
            first = await client.start(step("move_named_pose", pose="B"))
            assert not hasattr(first, "replace") and not hasattr(first, "hold")
            with pytest.raises(TimeoutError):
                await first.wait(timeout=0.01)
            stream = first.watch()
            await anext(stream)
            await stream.aclose()
            assert (await first.status()).state is TaskState.RUNNING
        async with System.connect(stack.endpoint, env_id=stack.env_id) as client:
            same = client.task(first.id)
            assert (await same.wait()).state is TaskState.SUCCEEDED
            held = await client.start(step("move_named_pose", pose="B"))
            await eventually(client.snapshot, lambda s: s.active_action is not None)
            receipt = await held.cancel()
            assert receipt.accepted and receipt.state is TaskState.CANCELLING
            assert (await held.wait()).state is TaskState.CANCELLED
            newer = await client.start(step("move_named_pose", pose="C"))
            assert newer.id != held.id
            assert (await newer.wait()).state == "SUCCEEDED"
            assert (await held.wait()).state is TaskState.CANCELLED
            assert (await same.status()).state == "SUCCEEDED"
            assert (await owner.task(newer.id).status()).state == "SUCCEEDED"
            with pytest.raises(RemoteError, match="task_not_found"):
                await client.task("missing").status()
        # Runtime process restart has no implicit task resurrection.
        agent = stack.processes[3]
        agent.terminate()
        await asyncio.to_thread(agent.wait, timeout=3)
        stack.processes.remove(agent)
        stack._spawn("agent-restarted", stack.node_command("agent"))
        await stack._wait_ready(owner.agent, "request/task/status")
        with pytest.raises(RemoteError, match="task_not_found"):
            await owner.task(first.id).status()


async def test_queued_and_planning_handles_keep_their_own_identity():
    async with System.launch(duration=0.06) as system:
        first = await system.start(step("move_named_pose", pose="B"))
        queued = await system.agent.request(
            "request/task/enqueue",
            {
                "request_id": new_id(),
                "plan": Plan(steps=[step("move_named_pose", pose="C")]).model_dump(),
            },
        )
        second = system.task(queued["task_id"])
        assert (await first.wait()).state == "SUCCEEDED"
        assert (await second.wait()).state == "SUCCEEDED"
        goal = await system.goal("put A in B")
        planned = await goal.wait()
        assert planned.state is GoalState.DONE and planned.request_id == goal.request_id
        assert planned.task is not None
        assert (await planned.task.wait()).state is TaskState.SUCCEEDED
        third = await system.start(step("move_named_pose", pose="home"))
        assert (await third.wait()).state == "SUCCEEDED"
        assert (await goal.status()).task.id == planned.task.id
        assert (await planned.task.status()).state == "SUCCEEDED"


async def test_old_plan_cannot_rebind_restarted_robot_and_tts_completed_restart_accepts():
    async with System.launch(duration=0.9) as system:
        stack = system._local_stack
        spoken = step("speak", text="before robot")
        task = await system.start(spoken, step("move_named_pose", pose="B", after=spoken))
        await eventually(lambda: system.snapshot("tts"), lambda s: s.active_action is not None)
        robot = stack.processes[1]
        old_boot = (await system.snapshot()).boot_id
        await system.clients["wrs"].transport.request("request/wrs/shutdown", {}, control=True)
        await asyncio.to_thread(robot.wait, timeout=3)
        stack.processes.remove(robot)
        stack._spawn("wrs-restarted", stack.node_command("wrs"))
        await stack._wait_ready(system.clients["wrs"].transport, "request/capabilities")
        await eventually(
            system.nodes, lambda s: s["wrs"]["ready"] and s["wrs"]["boot_id"] != old_boot
        )
        assert (await task.wait()).state in {"FAILED", "CANCELLED"}
        assert (await system.clients["wrs"].transport.request("request/health", {}))[
            "executions"
        ] == 0
        tts = next(p for p in stack.processes if p.args == stack.node_command("tts"))
        await system.clients["tts"].transport.request("request/tts/shutdown", {}, control=True)
        await asyncio.to_thread(tts.wait, timeout=3)
        stack.processes.remove(tts)
        stack._spawn("tts-restarted", stack.node_command("tts"))
        await stack._wait_ready(system.clients["tts"].transport, "request/capabilities")
        await eventually(system.nodes, lambda s: s["tts"]["ready"])
        action = await system.action("speak", text="after completed history")
        assert (await action.wait()).state == "SUCCEEDED"


async def test_cancel_then_start_with_unrelated_tts_process_offline():
    async with System.launch(duration=0.2) as system:
        tts = system._local_stack.processes[2]
        tts.terminate()
        await asyncio.to_thread(tts.wait, timeout=3)
        task = await system.start(step("move_named_pose", pose="B"))
        await eventually(system.snapshot, lambda s: s.active_action is not None)
        assert (await task.cancel()).accepted
        assert (await task.wait()).state == "CANCELLED"
        replacement = await system.start(step("move_named_pose", pose="C"))
        assert (await replacement.wait()).state == "SUCCEEDED"
        assert (await task.wait()).state == "CANCELLED"


async def test_cancel_reply_loss_and_duplicates_cannot_retarget_later_task():
    async with System.launch(duration=0.4) as system:
        task = await system.start(step("move_named_pose", pose="B"))
        await eventually(system.snapshot, lambda s: s.active_action is not None)
        original = system.agent.request
        replies = []

        async def lose_first(suffix, payload, **kwargs):
            result = await original(suffix, payload, **kwargs)
            if suffix == "request/task/cancel":
                replies.append(result)
                if len(replies) == 1:
                    raise TimeoutError("cancel reply lost after acceptance")
            return result

        system.agent.request = lose_first
        with pytest.raises(TimeoutError):
            await task.cancel()
        duplicates = await asyncio.gather(task.cancel(), task.cancel())
        assert duplicates[0] == duplicates[1]
        assert replies[0] == replies[1] == replies[2]
        assert (await task.wait()).state == "CANCELLED"
        newer = await system.start(step("move_named_pose", pose="C"))
        before = (await system.snapshot()).control_epoch
        assert await task.cancel() == duplicates[0]
        assert (await system.snapshot()).control_epoch == before
        assert (await newer.wait()).state == "SUCCEEDED"
        assert (await task.status()).state == "CANCELLED"
