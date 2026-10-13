"""Stateful, bounded, cancellable agent execution engine."""
from __future__ import annotations

from dataclasses import dataclass
import json
import threading
import time

from .executor import Executor
from .permissions import Decision
from .planner import Planner, PlanningError
from .recovery import RecoveryManager
from .types import AgentError, Plan, Task, TaskState, TERMINAL_STATES
from .verifier import Verifier


@dataclass(frozen=True, slots=True)
class RuntimeLimits:
    max_steps: int = 12
    repeated_call_limit: int = 2
    task_timeout_seconds: float = 60.0


class AgentRuntime:
    def __init__(self, planner: Planner, executor: Executor, verifier: Verifier | None = None,
                 recovery: RecoveryManager | None = None, limits: RuntimeLimits | None = None):
        self.planner, self.executor = planner, executor
        self.verifier = verifier or Verifier()
        self.recovery = recovery or RecoveryManager()
        self.limits = limits or RuntimeLimits()
        self._cancel: dict[str, threading.Event] = {}
        self._plans: dict[str, Plan] = {}
        self._outputs: dict[str, list[object]] = {}

    def create_task(self, request: str) -> Task:
        task = Task(request)
        self._cancel[task.id] = threading.Event()
        return task

    def cancel(self, task: Task) -> None:
        self._cancel.setdefault(task.id, threading.Event()).set()
        self.executor.cancel_active()
        if task.state not in TERMINAL_STATES:
            task.transition(TaskState.CANCELLED, "user cancellation requested")

    def run(self, request: str, approvals: set[int] | None = None) -> Task:
        task = self.create_task(request)
        return self.run_task(task, approvals=approvals)

    def run_task(self, task: Task, approvals: set[int] | None = None) -> Task:
        approvals = approvals or set()
        started = time.monotonic()
        cancellation = self._cancel.setdefault(task.id, threading.Event())
        if task.state == TaskState.CREATED:
            task.transition(TaskState.PLANNING, "planning started")
            try:
                plan = self.planner.plan(task.request)
                if not plan.steps or len(plan.steps) > self.limits.max_steps:
                    raise PlanningError(AgentError("invalid_plan_size",
                        f"plan exceeds maximum of {self.limits.max_steps} steps"))
                self._plans[task.id] = plan
                self._outputs[task.id] = []
                task.transition(TaskState.READY, "plan validated")
            except PlanningError as exc:
                return self._fail(task, exc.error)
        elif task.state == TaskState.WAITING_FOR_APPROVAL:
            plan = self._plans[task.id]
            task.transition(TaskState.READY, "approval response received")
        elif task.state in TERMINAL_STATES:
            return task
        else:
            return self._fail(task, AgentError("invalid_resume", f"cannot resume from {task.state.value}"))

        plan = self._plans[task.id]
        signatures: list[str] = []
        while task.current_step < len(plan.steps):
            if cancellation.is_set():
                if task.state not in TERMINAL_STATES:
                    task.transition(TaskState.CANCELLED, "cancelled before next tool")
                return task
            if time.monotonic() - started > self.limits.task_timeout_seconds:
                return self._fail(task, AgentError("task_timeout", "task execution deadline exceeded"))
            step = plan.steps[task.current_step]
            try:
                arguments = _resolve_references(step.arguments, self._outputs[task.id])
                assert isinstance(arguments, dict)
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                return self._fail(task, AgentError("invalid_result_reference", str(exc)), step.tool)
            signature = json.dumps([step.tool, arguments], sort_keys=True, separators=(",", ":"))
            signatures.append(signature)
            repeated = 0
            for prior in reversed(signatures):
                if prior != signature: break
                repeated += 1
            cycle = len(signatures) >= 4 and signatures[-2:] == signatures[-4:-2]
            if repeated > self.limits.repeated_call_limit or cycle:
                return self._fail(task, AgentError("loop_detected", "repeated tool-call loop detected"))

            decision = self.executor.permission(step.tool, arguments,
                                                approved=task.current_step in approvals)
            if decision.decision == Decision.REQUIRE_APPROVAL:
                task.transition(TaskState.WAITING_FOR_APPROVAL, decision.reason, tool=step.tool)
                return task
            if decision.decision == Decision.DENY:
                return self._fail(task, AgentError("permission_denied", decision.reason), step.tool)

            retries = 0
            while True:
                if task.state == TaskState.READY:
                    task.transition(TaskState.RUNNING, "tool execution started", tool=step.tool)
                elif task.state == TaskState.RECOVERING:
                    task.transition(TaskState.RUNNING, "retry started", tool=step.tool)
                result = self.executor.execute(step.tool, arguments, cancellation,
                                               approved=task.current_step in approvals)
                if cancellation.is_set():
                    if task.state not in TERMINAL_STATES:
                        task.transition(TaskState.CANCELLED, "cancelled during tool execution", tool=step.tool)
                    return task
                if not result.ok:
                    error = result.error or AgentError("unknown_tool_error", "tool failed")
                    if self.recovery.should_retry(error, retries):
                        retries += 1
                        task.transition(TaskState.RECOVERING, f"recoverable failure; retry {retries}",
                                        tool=step.tool, error=error)
                        time.sleep(self.recovery.delay(retries))
                        continue
                    return self._fail(task, error, step.tool)
                task.transition(TaskState.VERIFYING, "tool returned; verifying actual result",
                                tool=step.tool, result=result.data)
                tool = self.executor.registry.get(step.tool)
                assert tool is not None  # registered permission check already succeeded
                verified, reason = self.verifier.verify(tool, arguments, result, step.expected)
                if not verified:
                    error = AgentError("verification_failed", reason, False)
                    return self._fail(task, error, step.tool)
                self._outputs[task.id].append(result.data)
                task.completed_steps += 1
                task.current_step += 1
                if task.current_step == len(plan.steps):
                    task.transition(TaskState.COMPLETED, "all postconditions verified")
                    return task
                task.transition(TaskState.READY, "step verified; next step ready")
                break
        return task

    def _fail(self, task: Task, error: AgentError, tool: str | None = None) -> Task:
        task.failure_reason = f"{error.code}: {error.message}"
        if task.state not in TERMINAL_STATES:
            task.transition(TaskState.FAILED, "task failed", tool=tool, error=error)
        return task


def _resolve_references(value: object, outputs: list[object]) -> object:
    """Resolve explicit result references; untrusted text is never interpreted as a reference."""
    if isinstance(value, dict):
        if set(value) == {"$ref"}:
            reference = value["$ref"]
            if not isinstance(reference, str): raise ValueError("result reference must be a string")
            parts = reference.split(".")
            if len(parts) < 2 or parts[0] != "steps": raise ValueError(f"invalid result reference: {reference}")
            current: object = outputs[int(parts[1])]
            for part in parts[2:]:
                if isinstance(current, dict): current = current[part]
                elif isinstance(current, list): current = current[int(part)]
                else: raise TypeError(f"cannot traverse result reference: {reference}")
            return current
        return {key: _resolve_references(child, outputs) for key, child in value.items()}
    if isinstance(value, list): return [_resolve_references(child, outputs) for child in value]
    return value
