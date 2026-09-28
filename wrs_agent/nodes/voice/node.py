"""Text intent routing, input deduplication, and a separate stop-control entry."""

import asyncio
from copy import deepcopy

from wrs_agent.errors import AgentError, from_exception
from wrs_agent.nodes.action_rpc import ActionClient
from wrs_agent.nodes.node import Node
from wrs_agent.policy import decide_event, text_intent
from wrs_agent.schemas import ControlRequest, Empty, Interaction, TextInput, TextReceipt


class VoiceNode(Node):
    """Route recognized or typed text to Agent tasks and node controls.

    ASR owns recognition; TTS owns playback. This node classifies text locally,
    deduplicates retries, and keeps stop requests independent of model planning.
    """

    node_type = "voice"
    features = ("interaction.replay",)
    requires = ("wrs", "tts", "agent")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._processed = {}
        self.wrs = self.tts = self.agent_bus = None

    async def setup(self):
        registry = self.discover()
        async def connect_peer(role):
            node_id = await registry.wait_for(self.peers.get(role), role=role, timeout=None)
            # Keep the verified channel while the other dependencies are still starting.
            return node_id, self.connect(node_id)

        (wrs_id, wrs), (tts_id, tts), (_, self.agent_bus) = await asyncio.gather(*(
            connect_peer(role) for role in self.requires
        ))
        self.wrs = ActionClient(wrs, node_id=wrs_id)
        self.tts = ActionClient(tts, node_id=tts_id)
        self.transport.register_handler("request/voice/text", self.text_event)
        self.transport.register_handler(
            "request/voice/control_text", self.control_text, control=True
        )
        self.transport.register_handler("request/voice/control", self.control_event, control=True)
        self.transport.register_handler("request/voice/event", self.ordinary_event)
        self.transport.register_handler("request/health", self.health)

    async def _handle(self, payload, *, text=False):
        event = TextInput.model_validate(payload) if text else Interaction.model_validate(payload)
        event_id = event.input_id if text else event.event_id
        # ASR commonly revises one utterance ID. Partial hypotheses never consume an ID.
        if text and not event.is_final:
            return TextReceipt(
                input_id=event_id, disposition="ignore", reason="partial_transcript"
            ).model_dump()
        record = self._processed.get(event_id)
        if record is None:
            if len(self._processed) >= 4096:
                raise AgentError("event_capacity")
            record = {"event": event, "state": "UNKNOWN", "pending": None, "request": None}
            self._processed[event_id] = record
        elif record["event"] != event:
            raise AgentError("event_id_conflict")
        if record["state"] == "CONFIRMED":
            return deepcopy(record["result"])
        if record["pending"] is None or record["pending"].done():
            record["state"] = "PENDING"
            record["pending"] = asyncio.create_task(self._execute(event, record))
            record["pending"].add_done_callback(
                lambda task: task.exception() if not task.cancelled() else None
            )
        # Losing one caller must not cancel a shared in-flight control request.
        return await asyncio.shield(record["pending"])

    async def _execute(self, event, record):
        try:
            result = await (
                self._dispatch_text(event, record)
                if isinstance(event, TextInput)
                else self._dispatch(event, record)
            )
        except BaseException:
            record["state"] = "UNKNOWN"
            raise
        record.update(
            state="UNKNOWN" if result.get("phase") == "UNKNOWN" else "CONFIRMED", result=result
        )
        return deepcopy(result)

    async def _dispatch(self, event, record):
        disposition = decide_event(event)
        result = {"disposition": disposition}
        if disposition in {"hold", "cancel_tts"}:
            result.update(await self._stop_node(disposition, event.event_id, record))
        elif disposition == "answer":
            result["task"] = await self.agent_bus.request("request/task/status", {})
        elif disposition == "update":
            result.update(disposition="clarify", reason="cancel_then_start_required")
        elif disposition == "enqueue":
            if event.plan is None:
                result.update(disposition="clarify", reason="explicit_plan_required_in_replay")
            else:
                result["task"] = await self.agent_bus.request(
                    "request/task/enqueue",
                    {"request_id": event.event_id, "plan": event.plan.model_dump()},
                )
        self.transport.publish("events/interaction", {"event_id": event.event_id, **result})
        return result

    async def _stop_node(self, disposition, event_id, record):
        node = self.wrs if disposition == "hold" else self.tts
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

    async def _stop_current(self, event, record):
        # Runtime's control worker never waits for Planner. It binds the target before awaiting.
        try:
            receipt = await self.agent_bus.request(
                "request/task/interrupt",
                {"request_id": event.input_id},
                control=True,
                timeout=0.5,
            )
        except Exception as exc:
            # Agent unavailable: still attempt robot stop, but do not claim the task stopped.
            try:
                await self._stop_node("hold", event.input_id, record)
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
        return await self._stop_node("hold", event.input_id, record)

    async def _dispatch_text(self, event, record):
        disposition, reason = text_intent(event)
        fields = {"input_id": event.input_id, "disposition": disposition, "reason": reason}
        if disposition in {"ignore", "clarify"}:
            return TextReceipt(**fields).model_dump()
        if disposition == "query":
            overview = await self.agent_bus.request("request/task/status", {})
            fields.update(accepted=True, overview=overview, task_id=overview["task_id"])
        elif disposition == "goal":
            await self.agent_bus.request(
                "request/task/goal", {"request_id": event.input_id, "goal": event.text}
            )
            fields.update(accepted=True, request_id=event.input_id)
        else:
            receipt = await (
                self._stop_current(event, record)
                if disposition == "stop"
                else self._stop_node("cancel_tts", event.input_id, record)
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
        self.transport.publish(
            "events/interaction",
            {
                "event_id": event.input_id,
                "disposition": disposition,
                "accepted": result["accepted"],
                "phase": result["phase"],
            },
        )
        return result

    async def text_event(self, payload, *, control=False):
        event = TextInput.model_validate(payload)
        is_control = text_intent(event)[0] in {"stop", "cancel_tts"}
        if is_control != control:
            raise AgentError(
                "use_voice_control_endpoint" if is_control else "control_intent_required"
            )
        return await self._handle(payload, text=True)

    async def control_text(self, payload):
        return await self.text_event(payload, control=True)

    async def teardown(self):
        pending = [
            r["pending"]
            for r in self._processed.values()
            if r["pending"] and not r["pending"].done()
        ]
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)

    async def health(self, payload):
        Empty.model_validate(payload)
        return {"backend": "recognized_text_and_replay", "processed": len(self._processed)}

    async def control_event(self, payload):
        event = Interaction.model_validate(payload)
        if event.kind not in {"stop", "barge_in"}:
            raise AgentError("control_intent_required")
        return await self._handle(payload)

    async def ordinary_event(self, payload):
        event = Interaction.model_validate(payload)
        if event.kind in {"stop", "barge_in"}:
            raise AgentError("use_voice_control_endpoint")
        return await self._handle(payload)
