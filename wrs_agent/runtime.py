"""Bounded DAG scheduling across explicitly bound nodes, with one Planner."""

import asyncio
from collections import deque
from copy import deepcopy
from dataclasses import dataclass, field

from wrs_agent.cache import PlanCache
from wrs_agent.errors import AgentError, error_info, from_exception
from wrs_agent.nodes.actions import ActionProvider
from wrs_agent.planner import PlanDecision, Planner, PlanRequest
from wrs_agent.schemas import (
    TERMINAL,
    ControlReceipt,
    ControlRequest,
    Plan,
    Step,
    TaskControl,
    TaskRequest,
    new_id,
)
from wrs_agent.skills import SKILLS, lookup_skills, require_contract, validate_skill


def validate_plan(plan, capabilities=None, bindings=None):
    plan = Plan.model_validate_json(plan.model_dump_json())
    for step in plan.steps:
        try:
            validate_skill(step.skill, step.version, step.args)
        except AgentError as exc:
            raise AgentError(
                from_exception(exc, node_id=(bindings or {}).get(step.skill), stage="preflight")
            ) from None
        if capabilities is not None:
            node = (bindings or {}).get(step.skill)
            if node is None:
                raise AgentError("provider_not_found", stage="preflight")
            cap = capabilities.get(node)
            if cap is None:
                raise AgentError("node_unavailable", node_id=node, stage="preflight")
            require_contract(step.skill, step.version, cap.skills, node_id=node, stage="preflight")
            if not set(SKILLS[step.skill].spec.required_capabilities).issubset(cap.skills):
                raise AgentError(
                    "unsupported_skill_on_current_node", node_id=node, stage="preflight"
                )
    return plan


@dataclass(frozen=True)
class _Task:
    """One execution definition; JSON also freezes nested arguments and dependencies."""

    task_id: str
    plan_json: str
    supersedes: str | None = None
    authorities: dict = field(default_factory=dict, compare=False)

    @classmethod
    def create(cls, plan, supersedes=None):
        return cls(new_id(), validate_plan(plan).model_dump_json(), supersedes)

    def plan(self):
        return Plan.model_validate_json(self.plan_json)


class Runtime:
    def __init__(
        self,
        nodes: dict[str, ActionProvider],
        bindings: dict[str, str],
        planner: Planner | None = None,
        *,
        registry=None,
    ):
        self.nodes, self.bindings, self.planner = nodes, bindings, planner
        self.registry = registry
        self.task = None
        self.hold_accepted = False
        self.state, self.reason = "IDLE", ""
        self.error = None
        self.active_actions = {}
        self.results = {}
        self.workers = set()
        self.requests = {}
        self.control_waiters = {}
        self.tasks = {}
        self.task_definitions = {}
        self.goals = {}
        self.closed = False
        self.node_locks = {node: asyncio.Lock() for node in nodes}
        self.planner_calls = 0
        self.planning = None
        self.planning_request_id = None
        self.planning_state = "IDLE"
        self.queued = []
        self.cache = PlanCache()
        self.recoveries = 0
        self.recovered_task = None
        self.action_history = deque(maxlen=128)

    @property
    def task_id(self):
        return self.task.task_id if self.task else None

    def _active(self, task):
        return self.task is task and not self.closed and self.state in {"RUNNING", "RESUMING"}

    def _planning_current(self, request_id):
        return self.planning_request_id == request_id and not self.closed

    def _activate(self, task, state="RUNNING"):
        self._save_task()
        self._stale_planning()
        self.planning_request_id = None
        self.planning_state = "IDLE"
        self.task = task
        self.state, self.reason, self.results = state, "", {}
        self.error = None
        self.active_actions.clear()
        self.hold_accepted = False

    def _record_error(self, error):
        # Preserve the uncertain action when an independent branch subsequently fails.
        if self.error is None or self.error.code != "execution_unknown":
            self.error, self.reason = error, error.message

    def _capacity(self):
        if len(self.tasks) + len(self.goals) >= 4096:
            raise AgentError("result_capacity")

    def _remember_task(self, task):
        self._capacity()
        self.task_definitions[task.task_id] = task
        self.tasks[task.task_id] = {
            "task_id": task.task_id,
            "supersedes": task.supersedes,
            "state": "QUEUED",
            "reason": "",
            "error": None,
            "steps": {},
            "active_actions": {},
        }

    def _save_task(self):
        if self.task is not None and self.tasks[self.task_id]["state"] not in {
            "SUCCEEDED",
            "FAILED",
            "CANCELLED",
        }:
            self.tasks[self.task_id].update(
                state=self.state,
                reason=self.reason,
                error=self.error.model_dump() if self.error else None,
                steps=dict(self.results),
                active_actions=dict(self.active_actions),
            )

    def task_status(self, task_id):
        if task_id not in self.tasks:
            raise AgentError("task_not_found")
        self._save_task()
        return deepcopy(self.tasks[task_id])

    def goal_status(self, request_id):
        if request_id not in self.goals:
            raise AgentError("goal_not_found")
        return deepcopy(self.goals[request_id])

    def _stale_planning(self):
        record = self.goals.get(self.planning_request_id)
        if record and record["state"] == "WAITING":
            record.update(state="STALE", reason="execution_or_control_changed")

    def _clear_queue(self, reason="queue_cleared_by_control"):
        for task in self.queued:
            self.tasks[task.task_id].update(state="CANCELLED", reason=reason)
        self.queued.clear()

    def _settle_replaced(self, old, state, reason=""):
        record = self.tasks[old.task_id]
        record.update(
            state=state,
            reason=reason,
            active_actions={},
            error=(
                error_info("control_unconfirmed", task_id=old.task_id, stage="control").model_dump()
                if state == "UNKNOWN"
                else None
            ),
        )
        for step in old.plan().steps:
            if record["steps"].get(step.step_id) != "SUCCEEDED":
                record["steps"][step.step_id] = state

    def snapshot(self):
        actions = dict(self.active_actions)
        return {
            "nodes": self.registry.snapshot() if self.registry else {},
            "task_id": self.task_id,
            "revision": 0,  # Deprecated wire field; task IDs identify executions.
            "supersedes": self.task.supersedes if self.task else None,
            "state": self.state,
            "action_id": next(iter(actions.values()), None),
            "active_actions": actions,
            "steps": dict(self.results),
            "reason": self.reason,
            "error": self.error.model_dump() if self.error else None,
            "planning": self.planning_state,
            "planning_request_id": self.planning_request_id,
            "planner_calls": self.planner_calls,
            "queued": len(self.queued),
            "cache_hit": self.cache.last_hit,
            "cache_hits": self.cache.hits,
            "cache_misses": self.cache.misses,
            "cache_reject_reason": self.cache.reject_reason,
            "semantic_shadow": self.cache.shadow_candidate,
            "recoveries": self.recoveries,
            "action_history": list(self.action_history),
        }

    def _spawn(self, coroutine):
        task = asyncio.create_task(coroutine)
        self.workers.add(task)
        task.add_done_callback(self.workers.discard)
        return task

    def _duplicate(self, key, data):
        if key not in self.requests:
            if len(self.requests) >= 4096:
                raise AgentError("request_capacity")
            return None
        original, result = self.requests[key]
        if data != original:
            raise AgentError("request_id_conflict")
        return result

    async def start(self, request: TaskRequest):
        duplicate = self._duplicate(request.request_id, request.model_dump())
        if duplicate is not None:
            return duplicate
        if self.closed or self.state not in {"IDLE", "SUCCEEDED", "FAILED", "CANCELLED"}:
            raise AgentError("task_busy_or_held")
        task = _Task.create(request.plan)
        self._remember_task(task)
        self._activate(task)
        result = self.snapshot()
        self.requests[request.request_id] = (request.model_dump(), result)
        self._spawn(self._execute(task))
        return result

    async def enqueue(self, request: TaskRequest):
        data = {"kind": "enqueue", **request.model_dump()}
        duplicate = self._duplicate(request.request_id, data)
        if duplicate is not None:
            return duplicate
        plan = validate_plan(request.plan)
        if len(self.queued) >= 16:
            raise AgentError("task_queue_full")
        if self.state != "RUNNING":
            raise AgentError("enqueue_requires_active_task")
        task = _Task.create(plan)
        self._remember_task(task)
        self.queued.append(task)
        result = {"accepted": True, "task_id": task.task_id, "queued": len(self.queued)}
        self.requests[request.request_id] = (data, result)
        return result

    async def goal(self, request):
        data = {"kind": "goal", **request.model_dump()}
        duplicate = self._duplicate(request.request_id, data)
        if duplicate is not None:
            return duplicate
        if self.planner is None or (self.planning and not self.planning.done()):
            raise AgentError("planner_unavailable_or_busy")
        if self.closed or self.state not in {"IDLE", "SUCCEEDED", "FAILED", "CANCELLED", "RUNNING"}:
            raise AgentError("task_held")
        self._capacity()
        self.goals[request.request_id] = {
            "request_id": request.request_id,
            "state": "WAITING",
            "reason": "",
            "task_id": None,
            "error": None,
        }
        self._save_task()
        # Planning requests have an ID; a Task exists only after an executable plan is valid.
        was_running = self.state == "RUNNING"
        if not was_running:
            self.reason = ""
        self.planning_request_id = request.request_id
        self.planning_state = "WAITING"
        result = {"accepted": True, "request_id": request.request_id, "revision": 0}
        self.requests[request.request_id] = (data, result)
        self.planning = self._spawn(self._plan(request.goal, request.request_id, was_running))
        return result

    async def _state(self, node, *, control=False):
        return await node.snapshot(control=control)

    async def _capabilities(self, names=None):
        required = names is not None
        names = self.nodes if names is None else names
        if self.registry:
            await self.registry.refresh(names)
        result = {}
        for name in names:
            try:
                if self.registry:
                    if not required and not self.registry.snapshot()[name]["ready"]:
                        continue
                    result[name] = await self.registry.capabilities(name, self.nodes[name])
                else:
                    result[name] = await self.nodes[name].capabilities()
            except Exception as exc:
                raise AgentError(from_exception(exc, node_id=name, stage="preflight")) from None
        return result

    async def _plan_valid(self, request_id, worlds):
        for name, old in worlds.items():
            if not self._planning_current(request_id):
                return False
            current = await self._state(self.nodes[name], control=True)
            if not self._planning_current(request_id):
                return False
            if (
                current.boot_id != old.boot_id
                or current.control_epoch != old.control_epoch
                or current.admission != "OPEN"
                or current.state_version != old.state_version
            ):
                self.planning_state = "STALE"
                return False
        return self._planning_current(request_id)

    async def _plan(self, goal, request_id, was_running):
        worlds = {}
        try:
            capabilities = await self._capabilities()
            worlds = {
                name: await self._state(self.nodes[name], control=True) for name in capabilities
            }
            if not self._planning_current(request_id):
                return
            request = PlanRequest(
                user_goal=goal,
                world={n: w.model_dump(exclude={"lease_id"}) for n, w in worlds.items()},
                skills=[
                    spec.model_dump() for spec in lookup_skills(goal, capabilities, self.bindings)
                ],
            )
            cached = self.cache.lookup(goal, worlds, capabilities, self.bindings)
            if cached is None:
                self.planner_calls += 1
                decision = await self.planner.plan(request)
            else:
                decision = PlanDecision(kind="execute", plan=cached)
            if not await self._plan_valid(request_id, worlds):
                return
            if decision.kind != "execute":
                self.planning_state = decision.kind.upper()
                self.goals[request_id]["reason"] = decision.text
                if not was_running:
                    self.reason = decision.text
                return
            if was_running:
                self.planning_state = "REQUIRES_CONFIRMATION"
                return
            validated = validate_plan(decision.plan, capabilities, self.bindings)
            task = _Task.create(validated)
            self._remember_task(task)
            self.goals[request_id].update(state="DONE", task_id=task.task_id)
            self._activate(task)
            self.planning_state = "DONE"
            await self._execute(task)
            if self.task is task and not self.closed:
                if self.state == "SUCCEEDED":
                    self.cache.remember(goal, validated, worlds, capabilities, self.bindings)
                else:
                    self.cache.invalidate(goal, self.reason or self.state)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if not self._planning_current(request_id):
                return
            # A late provider error after a physical stop is obsolete too.
            try:
                valid = await self._plan_valid(request_id, worlds)
            except Exception:
                valid = False
            if not self._planning_current(request_id):
                return
            if not valid:
                self.planning_state = "STALE"
                return
            self.planning_state = "FAILED"
            failure = from_exception(exc, stage="planning")
            self.goals[request_id].update(reason=failure.message, error=failure.model_dump())
            self.cache.invalidate(goal, failure.code)
            if not was_running:
                self.state, self.reason = "FAILED", failure.message

        finally:
            record = self.goals[request_id]
            if record["state"] == "WAITING":
                record.update(
                    state=self.planning_state if self._planning_current(request_id) else "STALE",
                    reason=record["reason"]
                    or (self.reason if self._planning_current(request_id) else "planning_obsolete"),
                )

    async def _execute(self, task):
        if not self._active(task):
            return
        plan = task.plan()
        try:
            capabilities = await self._capabilities(self._participants(task))
            validate_plan(plan, capabilities, self.bindings)
            if self.registry:
                for step in plan.steps:
                    self.registry.node_for(step.skill, step.version)
            # Capture every participant before ANY branch can dispatch.
            for name in self._participants(task):
                try:
                    world = await self._state(self.nodes[name], control=True)
                except Exception as exc:
                    raise AgentError(from_exception(exc, node_id=name, stage="preflight")) from None
                if self.registry:
                    self.registry.check_instance(name, world.boot_id)
                if world.admission != "OPEN":
                    raise AgentError("node_not_ready", node_id=name, stage="preflight")
                task.authorities[name] = (world.boot_id, world.control_epoch)
        except Exception as exc:
            if self._active(task):
                self.state = "FAILED"
                self._record_error(from_exception(exc, task_id=task.task_id, stage="preflight"))
                self._clear_queue("preceding_task_did_not_succeed")
            return
        done = {step.step_id: asyncio.Event() for step in plan.steps}
        outcomes = {}

        async def step_job(step):
            try:
                for dep in step.depends_on:
                    await done[dep].wait()
                    if outcomes.get(dep) != "SUCCEEDED":
                        outcomes[step.step_id] = "BLOCKED"
                        return
                node_name = self.bindings[step.skill]
                async with self.node_locks[node_name]:
                    if not self._active(task):
                        outcomes[step.step_id] = "STALE"
                        return
                    outcomes[step.step_id] = await self._run_step(step, node_name, task)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                failure = from_exception(
                    exc,
                    node_id=self.bindings.get(step.skill),
                    task_id=task.task_id,
                    stage="preflight",
                )
                outcomes[step.step_id] = (
                    "UNKNOWN" if failure.code == "execution_unknown" else "FAILED"
                )
                if self._active(task):
                    self._record_error(failure)
                if self._active(task) and outcomes[step.step_id] == "UNKNOWN":
                    try:
                        await self._fence(self.bindings[step.skill], task)
                    except Exception:
                        pass  # The original action remains UNKNOWN; don't lose its ID/cause.
            finally:
                if self._active(task):
                    self.results.update(outcomes)
                done[step.step_id].set()

        # At most 12 jobs from the validated contract; no task per progress event.
        jobs = [
            asyncio.create_task(step_job(step))
            for step in sorted(plan.steps, key=lambda s: s.category != "interactive")
        ]
        try:
            await asyncio.gather(*jobs)
        finally:
            for job in jobs:
                if not job.done():
                    job.cancel()
            await asyncio.gather(*jobs, return_exceptions=True)
        if not self._active(task):
            return
        values = set(outcomes.values())
        self.state = (
            "UNKNOWN"
            if "UNKNOWN" in values
            else "FAILED"
            if "FAILED" in values
            else "CANCELLED"
            if values != {"SUCCEEDED"}
            else "SUCCEEDED"
        )
        if self.state == "SUCCEEDED":
            self.reason, self.error = "", None
        if self.state != "SUCCEEDED":
            self._clear_queue("preceding_task_did_not_succeed")
        if self.state == "SUCCEEDED" and self.queued and not self.closed:
            queued = self.queued.pop(0)
            self._activate(queued)
            self._spawn(self._execute(queued))

    async def _run_step(self, step, node_name, task):
        outcome, status, original = await self._attempt(
            step, node_name, task, task.authorities[node_name]
        )
        if (
            outcome != "FAILED"
            or status.verification != "FAIL"
            or status.reason not in {"localization_failed", "grasp_failed"}
            or "observe_once" not in SKILLS[step.skill].spec.recovery
            or self.recovered_task == task.task_id
            or not self._active(task)
            or self.closed
        ):
            return outcome
        node = self.nodes[node_name]
        authority = (original.boot_id, original.control_epoch)
        current = await node.snapshot()
        if not self._recoverable_state(step, current, authority, task):
            return outcome
        capabilities = await node.capabilities()
        if (
            capabilities.skills.get("observe") != SKILLS["observe"].spec.version
            or capabilities.skills.get(step.skill) != step.version
        ):
            return outcome
        if not self._active(task):
            return "STALE"
        self.recovered_task = task.task_id
        self.recoveries += 1
        observe = Step(
            step_id="recovery-" + new_id(), skill="observe", version=SKILLS["observe"].spec.version
        )
        observed, _, _ = await self._attempt(observe, node_name, task, authority)
        if observed != "SUCCEEDED":
            return observed
        current = await node.snapshot()
        if not self._recoverable_state(step, current, authority, task):
            return "BLOCKED"
        # Exactly one new action, with a fresh ID and receiver-issued authorization.
        return (await self._attempt(step, node_name, task, authority))[0]

    def _recoverable_state(self, step, world, authority, task):
        return (
            self._active(task)
            and not self.closed
            and (world.boot_id, world.control_epoch) == authority
            and world.admission == "OPEN"
            and world.stop_confirmed
            and world.active_action is None
            and world.data.held_object is None
            and world.data.objects.get(step.args.get("object")) not in {None, "gripper"}
            and (world.data.kinematics is None or world.data.kinematics.valid)
        )

    async def _attempt(self, step, node_name, task, authority=None):
        node = self.nodes[node_name]
        if self.registry:
            await self.registry.refresh([node_name])
            if self.registry.node_for(step.skill, step.version) != node_name:
                raise AgentError("node_binding_changed")
        world = await node.context()
        if self.registry:
            self.registry.check_instance(node_name, world.boot_id)
        if not self._active(task):
            return "STALE", None, world
        if authority is not None and (world.boot_id, world.control_epoch) != authority:
            return "STALE", None, world
        if world.admission != "OPEN":
            return "BLOCKED", None, world
        try:
            handle = await node.submit(
                step.skill,
                step.args,
                context=world,
                task_id=task.task_id,
                version=step.version,
            )
        except AgentError as exc:
            raise AgentError(
                from_exception(exc, node_id=node_name, task_id=task.task_id, stage="submit")
            ) from None
        except Exception:
            raise AgentError(
                "execution_unknown", node_id=node_name, task_id=task.task_id, stage="submit"
            ) from None
        action, status = handle.request, handle.receipt.status
        if not self._active(task):
            return "STALE", None, world
        self.active_actions[step.step_id] = action.action_id
        try:
            if not self._active(task):
                return "STALE", None, world
            self.action_history.append(
                {
                    "action_id": action.action_id,
                    "skill": action.skill,
                    "task_id": task.task_id,
                    "revision": 0,
                }
            )
            async with asyncio.timeout(SKILLS[step.skill].spec.timeout):
                while status is not None and status.state not in TERMINAL:
                    if not self._active(task):
                        return "STALE", None, world
                    await asyncio.sleep(0.01)
                    status = await node.status(action.action_id)
            if not self._active(task):
                return "STALE", None, world
            if status is None or status.state == "UNKNOWN":
                raise AgentError(
                    "execution_unknown",
                    node_id=node_name,
                    task_id=task.task_id,
                    action_id=action.action_id,
                    stage="observe",
                )
            if status.state == "SUCCEEDED" and status.verification != "PASS":
                raise AgentError(
                    "execution_unknown",
                    node_id=node_name,
                    task_id=task.task_id,
                    action_id=action.action_id,
                    stage="observe",
                )
            if status.state == "FAILED":
                self._record_error(
                    status.error
                    or error_info(
                        "action_failed",
                        node_id=node_name,
                        task_id=task.task_id,
                        action_id=action.action_id,
                        stage="observe",
                    )
                )
            return status.state, status, world
        except Exception:
            if not self._active(task):
                return "STALE", None, world
            raise AgentError(
                "execution_unknown",
                node_id=node_name,
                task_id=task.task_id,
                action_id=action.action_id,
                stage="observe",
            ) from None
        finally:
            if self.active_actions.get(step.step_id) == action.action_id:
                self.active_actions.pop(step.step_id)

    def _participants(self, task):
        names = set()
        for step in task.plan().steps:
            name = self.bindings.get(step.skill)
            if name not in self.nodes:
                raise AgentError(
                    "provider_not_found", node_id=name, task_id=task.task_id, stage="preflight"
                )
            names.add(name)
        return names

    def _pending_predecessors(self, task):
        predecessors = []
        while task.supersedes:
            task = self.task_definitions[task.supersedes]
            if self.tasks[task.task_id]["state"] in {"SUCCEEDED", "FAILED", "CANCELLED"}:
                break
            predecessors.append(task)
        return predecessors

    def _control_participants(self, task):
        names = self._participants(task)
        for old in self._pending_predecessors(task):
            names.update(self._participants(old))
        return names

    async def _robot_controls(self, node_name):
        if self.registry:
            return self.registry.definitions[node_name]["type"] == "wrs"
        return (await self.nodes[node_name].capabilities()).robot_controls

    async def _fence(self, node_name, task=None):
        node = self.nodes[node_name]
        robot = await self._robot_controls(node_name)
        for _ in range(3):
            world = await self._state(node, control=True)
            if task is not None:
                if self.task is not task:
                    raise AgentError("stale_task")
                bound = task.authorities.get(node_name)
                if bound is None:
                    for old in self._pending_predecessors(task):
                        bound = old.authorities.get(node_name)
                        if bound:
                            break
                if bound and world.boot_id != bound[0]:
                    raise AgentError("node_instance_changed", node_id=node_name, stage="control")
            if not robot and world.active_action is None:
                return ControlReceipt(
                    accepted=world.stop_confirmed,
                    control_epoch=world.control_epoch,
                    phase="STOPPED" if world.stop_confirmed else "UNKNOWN",
                )
            request = ControlRequest(
                interrupt_id=new_id(),
                boot_id=world.boot_id,
                control_epoch=world.control_epoch,
                action_id=world.active_action if not robot else None,
            )
            result = await (node.control("hold", request) if robot else node.cancel(request))
            if result.accepted:
                return result
            if result.reason != "stale_control":
                raise AgentError(
                    result.error or error_info(result.reason, node_id=node_name, stage="control")
                )
        raise AgentError("concurrent_control_change")

    def _control_target(self, request):
        if self.closed or request.task_id != self.task_id or self.task is None:
            raise AgentError("stale_task")
        return self.task

    async def hold(self, request: TaskControl):
        data = {"kind": "hold", **request.model_dump()}
        duplicate = self._duplicate(request.request_id, data)
        if duplicate is not None:
            return await asyncio.shield(self.control_waiters[request.request_id])
        task = self._control_target(request)
        if request.replacement is not None:
            raise AgentError("hold_does_not_accept_replacement")
        if self.state not in {"RUNNING", "RESUMING", "HELD", "UNKNOWN"}:
            raise AgentError("task_not_active")
        return await self._begin_hold(task, request.request_id, data)

    async def _begin_hold(self, task, request_id, data):
        self._stale_planning()
        self.planning_request_id = None
        if self.planning_state == "WAITING":
            self.planning_state = "STALE"
        self.state = "HELD"
        self.hold_accepted = False
        self._clear_queue()
        result = {"task_id": task.task_id, "revision": 0, "state": "HELD", "phase": "PENDING"}
        self.requests[request_id] = (data, result)
        pending = self._spawn(self._finish_hold(task, result))
        self.control_waiters[request_id] = pending
        return await asyncio.shield(pending)

    async def interrupt(self, request):
        """Bind and stop the current task/planning once; retries never target later work."""
        data = {"kind": "interrupt", **request.model_dump()}
        duplicate = self._duplicate(request.request_id, data)
        if duplicate is not None:
            waiter = self.control_waiters.get(request.request_id)
            return await asyncio.shield(waiter) if waiter else deepcopy(duplicate)
        if self.closed:
            raise AgentError("runtime_closed", stage="control")
        self._stale_planning()
        self.planning_request_id = None
        if self.planning_state == "WAITING":
            self.planning_state = "STALE"
        self._clear_queue()
        if self.task and self.state in {"RUNNING", "RESUMING", "HELD", "UNKNOWN"}:
            return await self._begin_hold(self.task, request.request_id, data)
        result = {"accepted": True, "phase": "STOPPED", "task_id": None}
        self.requests[request.request_id] = (data, result)
        return deepcopy(result)

    async def _finish_hold(self, task, result):
        receipts = await asyncio.gather(
            *(self._fence(name, task) for name in self._control_participants(task)),
            return_exceptions=True,
        )
        accepted = all(not isinstance(r, Exception) and r.accepted for r in receipts)
        phase = (
            "UNKNOWN"
            if not accepted
            or any(not isinstance(r, Exception) and r.phase == "UNKNOWN" for r in receipts)
            else "STOPPING"
            if any(r.phase == "STOPPING" for r in receipts)
            else "STOPPED"
        )
        if self.task is task:
            self.hold_accepted = accepted and phase != "UNKNOWN"
        if self.task is task and phase == "UNKNOWN":
            self.state = "UNKNOWN"
            failure = next(
                (
                    from_exception(r, task_id=task.task_id, stage="control")
                    if isinstance(r, Exception)
                    else r.error
                    for r in receipts
                    if isinstance(r, Exception) or r.error is not None
                ),
                None,
            ) or error_info("control_unconfirmed", task_id=task.task_id, stage="control")
            self._record_error(failure)
            result.update(state="UNKNOWN", error=failure.model_dump())
        result.update(accepted=accepted, phase=phase)
        return result

    async def replace(self, request: TaskControl):
        data = {"kind": "replace", **request.model_dump()}
        duplicate = self._duplicate(request.request_id, data)
        if duplicate is not None:
            return duplicate
        old = self._control_target(request)
        if request.replacement is None:
            raise AgentError("replacement_required")
        task = _Task.create(request.replacement, supersedes=old.task_id)
        if self.state != "HELD":
            raise AgentError("explicit_hold_required_before_replacement")
        if not self.hold_accepted:
            raise AgentError("hold_pending_or_unconfirmed")
        self._remember_task(task)
        self._activate(task, "RESUMING")
        result = self.snapshot()
        self.requests[request.request_id] = (data, result)
        self._spawn(self._resume_and_execute(task, old))
        return result

    async def _resume_and_execute(self, task, old):
        plan = task.plan()
        try:
            stopped = {}
            # Confirm and settle each old identity even if the replacement is held again.
            for previous in reversed(self._pending_predecessors(task)):
                try:
                    for node_name in self._participants(previous):
                        stopped[node_name] = await self._wait_stopped(node_name, previous)
                except Exception:
                    self._settle_replaced(previous, "UNKNOWN", "stop_unconfirmed")
                    raise
                self._settle_replaced(previous, "CANCELLED", "replaced_after_confirmed_stop")
            if not self._active(task):
                return
            for node_name in self._participants(task):
                if node_name not in stopped:
                    stopped[node_name] = await self._wait_stopped(node_name)
            for node_name in {self.bindings[s.skill] for s in plan.steps}:
                node, world = self.nodes[node_name], stopped[node_name]
                robot = await self._robot_controls(node_name)
                if not self._active(task):
                    return
                if not robot:
                    if world.admission != "OPEN":
                        raise AgentError("node_not_ready")
                    continue
                if world.admission == "OPEN":
                    continue
                result = await node.control(
                    "resume",
                    ControlRequest(
                        interrupt_id=new_id(),
                        boot_id=world.boot_id,
                        control_epoch=world.control_epoch,
                        state_version=world.state_version,
                    ),
                )
                if not result.accepted:
                    raise AgentError(
                        result.error
                        or error_info(result.reason, node_id=node_name, stage="control")
                    )
            if not self._active(task):
                return
            self.state, self.results = "RUNNING", {}
            await self._execute(task)
        except Exception as exc:
            if self._active(task):
                self.state = "UNKNOWN"
                self._record_error(from_exception(exc, task_id=task.task_id, stage="control"))
                if self.tasks[old.task_id]["state"] == "HELD":
                    self._settle_replaced(old, "UNKNOWN", "stop_unconfirmed")

    async def _wait_stopped(self, node_name, previous=None):
        async with asyncio.timeout(3):
            while True:
                world = await self._state(self.nodes[node_name], control=True)
                bound = previous.authorities.get(node_name) if previous else None
                if bound and world.boot_id != bound[0]:
                    raise AgentError("node_instance_changed", node_id=node_name, stage="control")
                if world.admission == "UNKNOWN":
                    raise AgentError("control_unconfirmed", node_id=node_name, stage="control")
                if world.stop_confirmed and world.active_action is None:
                    return world
                await asyncio.sleep(0.01)

    async def close(self):
        self.closed = True
        self._stale_planning()
        self.planning_request_id = None
        self.state = "HELD"
        self._clear_queue()
        await asyncio.gather(*(self._fence(name) for name in self.nodes), return_exceptions=True)
        if self.planning and not self.planning.done():
            self.planning.cancel()
        await asyncio.gather(*list(self.workers), return_exceptions=True)
