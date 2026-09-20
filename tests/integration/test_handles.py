"""Identity-bound handles over real Zenoh, including reconnect and process restart."""

import asyncio
import secrets

import pytest
from conftest import eventually

from wrs_agent import System, step
from wrs_agent.processes import LocalStack
from wrs_agent.schemas import Plan, new_id
from wrs_agent.transport import RemoteError

pytestmark = pytest.mark.zenoh


async def test_handles_replace_and_reconnect_without_cancelling_observation(monkeypatch):
    monkeypatch.setenv("WRS_AGENT_TOKEN", secrets.token_urlsafe(32))
    async with LocalStack(duration=0.4) as stack:
        owner = stack.system
        async with System.connect(stack.endpoint, env_id=stack.env_id) as client:
            first = await client.start(step("move_named_pose", pose="B"))
            with pytest.raises(RemoteError, match="explicit_hold_required"):
                await first.replace(step("move_named_pose", pose="C"))
            with pytest.raises(TimeoutError):
                await first.wait(timeout=0.01)
            stream = first.watch()
            await anext(stream)
            await stream.aclose()
            assert (await first.status()).state == "RUNNING"
        async with System.connect(stack.endpoint, env_id=stack.env_id) as client:
            same = client.task(first.id)
            assert (await same.wait()).state == "SUCCEEDED"
            held = await client.start(step("move_named_pose", pose="B"))
            await eventually(client.snapshot, lambda s: s.active_action is not None)
            assert (await held.hold()).accepted
            with pytest.raises(TimeoutError):
                await held.wait(timeout=0.02)  # HELD does not complete the task.
            newer = await held.replace(step("move_named_pose", pose="C"))
            assert newer.id != held.id
            assert (await newer.wait()).supersedes == held.id
            assert (await held.wait()).state == "CANCELLED"
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
        assert planned.state == "DONE" and planned.request_id == goal.request_id
        assert planned.task is not None
        assert (await planned.task.wait()).state == "SUCCEEDED"
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


async def test_hold_replace_with_unrelated_tts_process_offline():
    async with System.launch(duration=0.2) as system:
        tts = system._local_stack.processes[2]
        tts.terminate()
        await asyncio.to_thread(tts.wait, timeout=3)
        task = await system.start(step("move_named_pose", pose="B"))
        await eventually(system.snapshot, lambda s: s.active_action is not None)
        assert (await task.hold()).accepted
        replacement = await task.replace(step("move_named_pose", pose="C"))
        assert (await replacement.wait()).state == "SUCCEEDED"
        assert (await task.wait()).state == "CANCELLED"
