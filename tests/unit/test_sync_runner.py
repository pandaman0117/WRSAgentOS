import asyncio
import threading
from types import SimpleNamespace

import pytest

from wrs_agent import launch
from wrs_agent.sync import Session


async def test_sync_entry_rejects_existing_event_loop_before_starting():
    with pytest.raises(RuntimeError, match="System.launch"):
        with launch():
            pytest.fail("synchronous entry must not start in an async caller")


def test_sync_startup_failure_closes_runner():
    with pytest.raises(ValueError, match="unsupported_backend"):
        with launch(backend="unsupported"):
            pytest.fail("invalid backend must not start")


def test_session_rejects_other_threads_and_calls_after_close():
    errors = []
    with asyncio.Runner() as runner:
        session = Session(runner, SimpleNamespace(status=lambda: pytest.fail("must not run")))

        def other_thread():
            try:
                session.status()
            except RuntimeError as exc:
                errors.append(str(exc))

        thread = threading.Thread(target=other_thread)
        thread.start()
        thread.join(timeout=1)
        assert not thread.is_alive()
        assert errors == ["Use this synchronous session from its owning thread."]
        session._closed = True
        with pytest.raises(RuntimeError, match="closed"):
            session.status()


@pytest.mark.parametrize("wait_timeout", [0.01, None])
async def test_watch_deadline_does_not_cancel_consumer_while_yielded(wait_timeout):
    from wrs_agent.handles import TaskHandle
    from wrs_agent.schemas import TaskStatus

    counter = 0

    async def status():
        nonlocal counter
        counter += 1
        return TaskStatus(task_id="a", state="RUNNING", reason=str(counter))

    handle = TaskHandle(None, "a")
    handle.status = status
    stream = handle.watch(timeout=wait_timeout)
    assert (await anext(stream)).state == "RUNNING"
    await asyncio.sleep(0.03)
    if wait_timeout is None:
        assert (await anext(stream)).state == "RUNNING"
    else:
        with pytest.raises(TimeoutError):
            await anext(stream)
    await stream.aclose()


def test_local_runtime_progress_requires_its_runner_to_be_driven():
    import time

    from wrs_agent.planner import ModelPlanner
    from wrs_agent.planner.providers.mock import MockClient
    from wrs_agent.runtime import Runtime
    from wrs_agent.schemas import GoalRequest

    with asyncio.Runner() as runner:
        model = MockClient('{"kind":"answer","text":"done"}', deferred=True)
        runtime = Runtime({}, {}, ModelPlanner(model))
        try:
            runner.run(runtime.goal(GoalRequest(request_id="local", goal="status")))
            runner.run(model.entered.wait())
            model.gate.set()
            # This Runtime lives in this process, unlike launch()'s Agent process.
            time.sleep(0.03)
            assert runtime.planning_state == "WAITING"

            async def finish():
                await runtime.planning

            runner.run(finish())
            assert runtime.planning_state == "ANSWER"
        finally:
            runner.run(runtime.close())
            runner.run(model.aclose())


@pytest.mark.parametrize("state", ["FAILED", "CANCELLED", "UNKNOWN"])
async def test_action_wait_returns_unsuccessful_terminal_status(state):
    from wrs_agent.nodes.actions import ActionHandle
    from wrs_agent.schemas import ActionStatus

    result = ActionStatus(action_id="a", state=state, reason="reported by node")

    async def status(action_id):
        assert action_id == "a"
        return result

    action = ActionHandle(SimpleNamespace(status=status), SimpleNamespace(action_id="a"), None)
    assert await action.wait() == result


async def test_action_wait_missing_status_raises_unknown():
    from wrs_agent.nodes.actions import ActionHandle

    async def status(action_id):
        return None

    action = ActionHandle(
        SimpleNamespace(status=status, node_id="tts"),
        SimpleNamespace(action_id="a", task_id="task"),
        None,
    )
    with pytest.raises(ValueError, match="execution_unknown") as caught:
        await action.wait()
    assert caught.value.error.node_id == "tts"
    assert caught.value.error.task_id == "task"
    assert caught.value.error.action_id == "a"
