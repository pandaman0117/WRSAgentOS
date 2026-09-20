"""Trusted recognized-text and replay entry; capture/ASR live in a separate adapter."""

import asyncio
from copy import deepcopy

from wrs_agent.errors import AgentError, from_exception
from wrs_agent.policy import decide_event, text_intent
from wrs_agent.schemas import ControlRequest, Empty, Interaction, TextInput, TextReceipt


def register_voice(bus, wrs, tts, agent_bus):
    processed = {}

    async def handle(payload, *, text=False):
        event = TextInput.model_validate(payload) if text else Interaction.model_validate(payload)
        event_id = event.input_id if text else event.event_id
        # ASR commonly revises one utterance ID. Partial hypotheses never consume an ID.
        if text and not event.is_final:
            return TextReceipt(
                input_id=event_id, disposition="ignore", reason="partial_transcript"
            ).model_dump()
        record = processed.get(event_id)
        if record is None:
            if len(processed) >= 4096:
                raise AgentError("event_capacity")
            record = {"event": event, "state": "UNKNOWN", "pending": None, "request": None}
            processed[event_id] = record
        elif record["event"] != event:
            raise AgentError("event_id_conflict")
        if record["state"] == "CONFIRMED":
            return deepcopy(record["result"])
        if record["pending"] is None or record["pending"].done():
            record["state"] = "PENDING"
            record["pending"] = asyncio.create_task(execute(event, record))
            record["pending"].add_done_callback(
                lambda task: task.exception() if not task.cancelled() else None
            )
        # Losing one caller must not cancel a shared in-flight control request.
        return await asyncio.shield(record["pending"])

    async def execute(event, record):
        try:
            result = await (
                dispatch_text(event, record)
                if isinstance(event, TextInput)
                else dispatch(event, record)
            )
        except BaseException:
            record["state"] = "UNKNOWN"
            raise
        record.update(
            state="UNKNOWN" if result.get("phase") == "UNKNOWN" else "CONFIRMED", result=result
        )
        return deepcopy(result)

    async def dispatch(event, record):
        disposition = decide_event(event)
        result = {"disposition": disposition}
        if disposition in {"hold", "cancel_tts"}:
            result.update(await stop_node(disposition, event.event_id, record))
        elif disposition == "answer":
            result["task"] = await agent_bus.request("request/task/status", {})
        elif disposition in {"update", "enqueue"}:
            # Structured replay carries an explicit plan, never inferred coordinates.
            if event.plan is None:
                result.update(disposition="clarify", reason="explicit_plan_required_in_replay")
            elif disposition == "enqueue":
                result["task"] = await agent_bus.request(
                    "request/task/enqueue",
                    {"request_id": event.event_id, "plan": event.plan.model_dump()},
                )
            else:
                if "target" not in record:
                    current = await agent_bus.request("request/task/status", {})
                    if current["task_id"] is None:
                        raise AgentError("no_task_to_replace")
                    record["target"] = current["task_id"]
                target = record["target"]
                await agent_bus.request(
                    "request/task/hold",
                    {"request_id": event.event_id + "-hold", "task_id": target},
                    control=True,
                )
                result["task"] = await agent_bus.request(
                    "request/task/replace",
                    {
                        "request_id": event.event_id,
                        "task_id": target,
                        "replacement": event.plan.model_dump(),
                    },
                    control=True,
                )
        bus.publish("events/interaction", {"event_id": event.event_id, **result})
        return result

    async def stop_node(disposition, event_id, record):
        node = wrs if disposition == "hold" else tts
        if record["request"] is None:
            world = await node.snapshot(control=True)
            if disposition == "cancel_tts" and world.active_action is None:
                return {"accepted": True, "phase": "STOPPED", "effect": "no_active_tts"}
            record["request"] = ControlRequest(
                interrupt_id=event_id,
                boot_id=world.boot_id,
                control_epoch=world.control_epoch,
                action_id=world.active_action if disposition == "cancel_tts" else None,
            )
        request = record["request"]
        receipt = await (
            node.control("hold", request) if disposition == "hold" else node.cancel(request)
        )
        return receipt.model_dump()

    async def stop_current(event, record):
        # Runtime's control worker never waits for Planner. It binds the target before awaiting.
        try:
            receipt = await agent_bus.request(
                "request/task/interrupt",
                {"request_id": event.input_id},
                control=True,
                timeout=0.5,
            )
        except Exception as exc:
            # Agent unavailable: still attempt robot stop, but do not claim the task stopped.
            try:
                await stop_node("hold", event.input_id, record)
            except Exception:
                pass
            return {
                "accepted": False,
                "phase": "UNKNOWN",
                "error": from_exception(exc, stage="control"),
            }
        if receipt.get("task_id") is not None:
            return receipt
        # No active task: invalidate pending planning and fence standalone robot actions.
        return await stop_node("hold", event.input_id, record)

    async def dispatch_text(event, record):
        disposition, reason = text_intent(event)
        fields = {"input_id": event.input_id, "disposition": disposition, "reason": reason}
        if disposition in {"ignore", "clarify"}:
            return TextReceipt(**fields).model_dump()
        if disposition == "query":
            overview = await agent_bus.request("request/task/status", {})
            fields.update(accepted=True, overview=overview, task_id=overview["task_id"])
        elif disposition == "goal":
            await agent_bus.request(
                "request/task/goal", {"request_id": event.input_id, "goal": event.text}
            )
            fields.update(accepted=True, request_id=event.input_id)
        else:
            receipt = await (
                stop_current(event, record)
                if disposition == "stop"
                else stop_node("cancel_tts", event.input_id, record)
            )
            phase = receipt["phase"] if receipt["accepted"] else "UNKNOWN"
            fields.update(
                accepted=receipt["accepted"],
                phase=phase,
                error=receipt.get("error"),
                task_id=receipt.get("task_id"),
            )
        result = TextReceipt(**fields).model_dump()
        # No transcripts or audio in the notification/log stream.
        bus.publish(
            "events/interaction",
            {
                "event_id": event.input_id,
                "disposition": disposition,
                "accepted": result["accepted"],
                "phase": result["phase"],
            },
        )
        return result

    async def text_event(payload, *, control=False):
        event = TextInput.model_validate(payload)
        is_control = text_intent(event)[0] in {"stop", "cancel_tts"}
        if is_control != control:
            raise AgentError(
                "use_voice_control_endpoint" if is_control else "control_intent_required"
            )
        return await handle(payload, text=True)

    async def control_text(payload):
        return await text_event(payload, control=True)

    async def close():
        pending = [
            r["pending"] for r in processed.values() if r["pending"] and not r["pending"].done()
        ]
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)

    async def health(payload):
        Empty.model_validate(payload)
        return {"backend": "recognized_text_and_replay", "processed": len(processed)}

    async def control_event(payload):
        event = Interaction.model_validate(payload)
        if event.kind not in {"stop", "barge_in"}:
            raise AgentError("control_intent_required")
        return await handle(payload)

    async def ordinary_event(payload):
        event = Interaction.model_validate(payload)
        if event.kind in {"stop", "barge_in"}:
            raise AgentError("use_voice_control_endpoint")
        return await handle(payload)

    bus.register_handler("request/voice/text", text_event)
    bus.register_handler("request/voice/control_text", control_text, control=True)
    bus.register_handler("request/voice/control", control_event, control=True)
    bus.register_handler("request/voice/event", ordinary_event)
    bus.register_handler("request/health", health)
    return close
