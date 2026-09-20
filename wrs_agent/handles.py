"""Identity-only clients for Runtime's retained task and planning results."""

import asyncio
from dataclasses import dataclass

from wrs_agent.schemas import (
    TERMINAL,
    ErrorInfo,
    GoalStatus,
    Plan,
    TaskHoldReceipt,
    TaskStatus,
    new_id,
)


class TaskHandle:
    def __init__(self, system, task_id):
        self._system, self.id = system, task_id

    async def status(self):
        return TaskStatus.model_validate(
            await self._system.agent.request("request/task/status", {"task_id": self.id})
        )

    async def watch(self, *, timeout=10):  # noqa: ASYNC109 - bounded observation
        """Poll changes; timeout/closing the iterator never cancels remote work."""
        deadline = None if timeout is None else asyncio.get_running_loop().time() + timeout
        previous = None
        while True:
            # Do not keep a task-bound timeout active across a caller's yield.
            async with asyncio.timeout_at(deadline):
                state = await self.status()
            if state != previous:
                yield state
                previous = state
            if state.state in TERMINAL:
                return
            async with asyncio.timeout_at(deadline):
                await asyncio.sleep(0.02)

    async def wait(self, *, timeout=10):  # noqa: ASYNC109 - bounded observation
        async for state in self.watch(timeout=timeout):
            result = state
        return result

    async def hold(self):
        return TaskHoldReceipt.model_validate(
            await self._system.agent.request(
                "request/task/hold", {"request_id": new_id(), "task_id": self.id}, control=True
            )
        )

    async def replace(self, *steps):
        result = await self._system.agent.request(
            "request/task/replace",
            {
                "request_id": new_id(),
                "task_id": self.id,
                "replacement": Plan(steps=list(steps)).model_dump(),
            },
            control=True,
        )
        return self._system.task(result["task_id"])


@dataclass(frozen=True)
class GoalResult:
    request_id: str
    state: str
    reason: str
    task: TaskHandle | None
    error: ErrorInfo | None = None


class GoalHandle:
    def __init__(self, system, request_id):
        self._system, self.request_id = system, request_id

    async def status(self):
        status = GoalStatus.model_validate(
            await self._system.agent.request("request/goal/status", {"request_id": self.request_id})
        )
        return GoalResult(
            status.request_id,
            status.state,
            status.reason,
            self._system.task(status.task_id) if status.task_id else None,
            status.error,
        )

    async def wait(self, *, timeout=10):  # noqa: ASYNC109 - bounded observation
        """Wait for planning, not execution; DONE includes the accepted task handle."""
        async with asyncio.timeout(timeout):
            while True:
                result = await self.status()
                if result.state != "WAITING":
                    return result
                await asyncio.sleep(0.02)
