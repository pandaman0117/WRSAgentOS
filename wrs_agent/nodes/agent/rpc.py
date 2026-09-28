"""Runtime services return quickly; task execution runs independently."""

from wrs_agent.errors import AgentError
from wrs_agent.schemas import (
    Empty,
    GoalQuery,
    GoalRequest,
    InterruptRequest,
    TaskCancelRequest,
    TaskQuery,
    TaskRequest,
)


def register_runtime(transport, runtime):
    async def nodes(payload):
        Empty.model_validate(payload)
        return await runtime.registry.refresh() if runtime.registry else {}

    transport.register_handler("request/nodes", nodes)

    async def start(payload):
        return await runtime.start(TaskRequest.model_validate(payload))

    async def status(payload):
        if not payload:
            return runtime.snapshot()
        return runtime.task_status(TaskQuery.model_validate(payload).task_id)

    async def goal_status(payload):
        return runtime.goal_status(GoalQuery.model_validate(payload).request_id)

    def control_request(payload):
        if not payload.get("task_id"):
            raise AgentError("task_id_required")
        return TaskCancelRequest.model_validate(payload)

    async def cancel(payload):
        return await runtime.cancel(control_request(payload))

    async def interrupt(payload):
        return await runtime.interrupt(InterruptRequest.model_validate(payload))

    async def goal(payload):
        return await runtime.goal(GoalRequest.model_validate(payload))

    async def enqueue(payload):
        return await runtime.enqueue(TaskRequest.model_validate(payload))

    transport.register_handler("request/task/enqueue", enqueue)
    transport.register_handler("request/task/goal", goal)
    transport.register_handler("request/task/start", start)
    transport.register_handler("request/task/status", status)
    transport.register_handler("request/goal/status", goal_status)
    transport.register_handler("request/task/interrupt", interrupt, control=True)
    transport.register_handler("request/task/cancel", cancel, control=True)
