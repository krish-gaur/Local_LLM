"""Typed task, plan, history, and error records."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

Json = None | bool | int | float | str | list["Json"] | dict[str, "Json"]


class TaskState(str, Enum):
    CREATED = "CREATED"
    PLANNING = "PLANNING"
    READY = "READY"
    RUNNING = "RUNNING"
    VERIFYING = "VERIFYING"
    WAITING_FOR_APPROVAL = "WAITING_FOR_APPROVAL"
    RECOVERING = "RECOVERING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


TERMINAL_STATES = {TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED}
VALID_TRANSITIONS: dict[TaskState, set[TaskState]] = {
    TaskState.CREATED: {TaskState.PLANNING, TaskState.CANCELLED},
    TaskState.PLANNING: {TaskState.READY, TaskState.FAILED, TaskState.CANCELLED},
    TaskState.READY: {TaskState.RUNNING, TaskState.WAITING_FOR_APPROVAL, TaskState.FAILED, TaskState.CANCELLED},
    TaskState.RUNNING: {TaskState.VERIFYING, TaskState.RECOVERING, TaskState.FAILED, TaskState.CANCELLED},
    TaskState.VERIFYING: {TaskState.READY, TaskState.COMPLETED, TaskState.RECOVERING,
                          TaskState.FAILED, TaskState.CANCELLED},
    TaskState.WAITING_FOR_APPROVAL: {TaskState.READY, TaskState.RUNNING, TaskState.FAILED, TaskState.CANCELLED},
    TaskState.RECOVERING: {TaskState.RUNNING, TaskState.FAILED, TaskState.CANCELLED},
    TaskState.COMPLETED: set(), TaskState.FAILED: set(), TaskState.CANCELLED: set(),
}


class InvalidTransitionError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class AgentError:
    code: str
    message: str
    recoverable: bool = False
    details: dict[str, Json] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PlanStep:
    tool: str
    arguments: dict[str, Json]
    expected: dict[str, Json] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Plan:
    steps: tuple[PlanStep, ...]


@dataclass(frozen=True, slots=True)
class HistoryEvent:
    timestamp: datetime
    state: TaskState
    event: str
    step: int
    tool: str | None = None
    result: Json = None
    error: AgentError | None = None


@dataclass(slots=True)
class Task:
    request: str
    id: str = field(default_factory=lambda: str(uuid4()))
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    state: TaskState = TaskState.CREATED
    current_step: int = 0
    history: list[HistoryEvent] = field(default_factory=list)
    failure_reason: str | None = None
    completed_steps: int = 0

    def transition(self, target: TaskState, event: str, *, tool: str | None = None,
                   result: Json = None, error: AgentError | None = None) -> None:
        if target not in VALID_TRANSITIONS[self.state]:
            raise InvalidTransitionError(f"invalid task transition: {self.state.value} -> {target.value}")
        self.state = target
        self.history.append(HistoryEvent(datetime.now(timezone.utc), target, event,
                                         self.current_step, tool, result, error))

    def report(self) -> dict[str, Json]:
        return {"task_id": self.id, "status": self.state.value, "request": self.request,
                "completed_steps": self.completed_steps, "current_step": self.current_step,
                "partial": self.completed_steps > 0 and self.state != TaskState.COMPLETED,
                "failure_reason": self.failure_reason, "history_events": len(self.history)}
