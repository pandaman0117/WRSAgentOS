"""One action client and service binding; each node exposes only its supported controls."""

import asyncio
from typing import Protocol

from pydantic import ValidationError

from wrs_agent.errors import AgentError, error_info, from_exception
from wrs_agent.schemas import (
    TERMINAL,
    ActionContext,
    ActionReceipt,
    ActionRequest,
    ActionStatus,
    CapabilitySnapshot,
    ControlReceipt,
    ControlRequest,
    Empty,
    IdRequest,
    NodeSnapshot,
    new_id,
)


class ActionHandle:
    """A submitted action. wait() returns terminal status; inspect state/verification."""

    def __init__(self, client, request, receipt):
        self.client, self.request, self.receipt = client, request, receipt
        self.id = request.action_id
        self._cancel_request = None

    async def status(self):
        return await self.client.status(self.id)

    async def wait(self, *, timeout=10):  # noqa: ASYNC109 - bounded public wait
        async with asyncio.timeout(timeout):
            while True:
                state = await self.status()
                if state is None:
                    raise AgentError(
                        "execution_unknown",
                        node_id=self.client.node_id,
                        task_id=self.request.task_id,
                        action_id=self.id,
                        stage="observe",
                    )
                if state.state in TERMINAL:
                    return state
                await asyncio.sleep(0.02)

    async def cancel(self):
        """Request cancellation; receipt.phase distinguishes STOPPING from STOPPED."""
        if self._cancel_request is None:
            state = await self.client.snapshot(control=True)
            self._cancel_request = ControlRequest(
                interrupt_id=new_id(),
                boot_id=self.request.boot_id,
                control_epoch=state.control_epoch,
                action_id=self.id,
            )
        return await self.client.cancel(self._cancel_request)


class ActionProvider(Protocol):
    async def capabilities(self) -> CapabilitySnapshot: ...
    async def snapshot(self, *, control: bool = False) -> NodeSnapshot: ...
    async def context(self, *, control: bool = False) -> ActionContext: ...
    async def submit(self, skill, args, *, context, task_id, version=1) -> ActionHandle: ...
    async def status(self, action_id: str) -> ActionStatus | None: ...
    async def cancel(self, request: ControlRequest) -> ControlReceipt: ...
    async def control(self, kind: str, request: ControlRequest) -> ControlReceipt: ...


class ActionClient:
    def __init__(self, transport, *, node_id=None):
        self.transport, self.node_id = transport, node_id

    async def _query(self, suffix, payload, response, *, stage, optional=False, control=False):
        try:
            raw = await self.transport.request(suffix, payload, control=control)
        except Exception as exc:
            raise AgentError(from_exception(exc, node_id=self.node_id, stage=stage)) from None
        if raw is None and optional:
            return None
        try:
            return response.model_validate(raw)
        except ValueError:
            raise AgentError("invalid_reply", node_id=self.node_id, stage=stage) from None

    async def capabilities(self):
        return await self._query("request/capabilities", {}, CapabilitySnapshot, stage="discovery")

    async def snapshot(self, *, control=False):
        suffix = "request/control/snapshot" if control else "request/snapshot"
        return await self._query(suffix, {}, NodeSnapshot, stage="observe", control=control)

    async def context(self, *, control=False):
        return await self._query(
            "request/action/context", {}, ActionContext, stage="preflight", control=control
        )

    async def submit(self, skill, args, *, context, task_id, version=1):
        """Construct once; a missing reply is reconciled by ID, never blindly replayed."""
        try:
            request = ActionRequest(
                action_id=new_id(),
                task_id=task_id,
                task_revision=0,
                boot_id=context.boot_id,
                control_epoch=context.control_epoch,
                lease_id=context.lease_id,
                state_version=context.state_version,
                skill=skill,
                version=version,
                args=args,
            )
        except ValidationError:
            raise AgentError(
                "invalid_arguments", node_id=context.node_id, task_id=task_id, stage="preflight"
            ) from None
        try:
            receipt = await self._submit(request)
        except Exception as exc:
            failure = from_exception(
                exc,
                node_id=context.node_id,
                task_id=task_id,
                action_id=request.action_id,
                stage="submit",
            )
            if failure.code not in {
                "request_timeout",
                "query_error",
                "invalid_reply",
                "internal_error",
            }:
                raise AgentError(failure) from None
            # Reconcile by the original ID; never construct or send another action.
            try:
                status = await self.status(request.action_id)
            except Exception:
                status = None
            if status is None:
                raise AgentError(
                    "execution_unknown",
                    node_id=context.node_id,
                    task_id=task_id,
                    action_id=request.action_id,
                    stage="submit",
                ) from None
            receipt = ActionReceipt(accepted=True, status=status)
        if not receipt.accepted:
            raise AgentError(
                receipt.error
                or error_info(
                    receipt.reason,
                    node_id=context.node_id,
                    task_id=task_id,
                    action_id=request.action_id,
                    stage="submit",
                )
            )
        return ActionHandle(self, request, receipt)

    async def _submit(self, request):
        return await self._query(
            "request/action/submit", request.model_dump(), ActionReceipt, stage="submit"
        )

    async def status(self, action_id):
        return await self._query(
            "request/action/status",
            {"action_id": action_id},
            ActionStatus,
            stage="observe",
            optional=True,
        )

    async def control(self, kind, request):
        return await self._query(
            f"request/control/{kind}",
            request.model_dump(),
            ControlReceipt,
            stage="control",
            control=True,
        )

    async def cancel(self, request):
        return await self.control("cancel", request)


def register_actions(transport, executor):
    async def capabilities(payload):
        Empty.model_validate(payload)
        return executor.capabilities().model_dump()

    async def snapshot(payload):
        Empty.model_validate(payload)
        return executor.snapshot().model_dump()

    async def context(payload):
        Empty.model_validate(payload)
        return executor.context().model_dump()

    async def submit(payload):
        return (await executor.submit(ActionRequest.model_validate(payload))).model_dump()

    async def status(payload):
        request = IdRequest.model_validate(payload)
        result = executor.status(request.action_id)
        return result.model_dump() if result else None

    async def health(payload):
        Empty.model_validate(payload)
        return {
            "backend": executor.backend,
            "executions": executor.executions,
            "callbacks_off_loop": bool(transport.callback_threads - {transport.loop_thread}),
            "control_high_water": transport.control.high_water,
            "normal_high_water": transport.normal.high_water,
        }

    transport.register_handler("request/health", health)
    transport.register_handler("request/capabilities", capabilities)
    # Observation never grants authority; TTS has no hold/allow_actions service.
    transport.register_handler("request/action/context", context, control=True)
    transport.register_handler("request/snapshot", snapshot)
    transport.register_handler("request/control/snapshot", snapshot, control=True)
    transport.register_handler("request/action/submit", submit)
    transport.register_handler("request/action/status", status)
    controls = (
        ("hold", "cancel", "allow_actions")
        if executor.capabilities().robot_controls
        else ("cancel",)
    )
    for kind in controls:

        async def control(payload, kind=kind):
            return (
                await executor.control(kind, ControlRequest.model_validate(payload))
            ).model_dump()

        transport.register_handler(f"request/control/{kind}", control, control=True)
    executor.on_event = transport.publish
