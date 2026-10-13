"""Bounded plan parsing and deterministic milestone-2 planner."""
from __future__ import annotations

from abc import ABC, abstractmethod
import json
from typing import Any

from .types import AgentError, Json, Plan, PlanStep


class PlanningError(ValueError):
    def __init__(self, error: AgentError):
        super().__init__(error.message)
        self.error = error


class Planner(ABC):
    @abstractmethod
    def plan(self, request: str) -> Plan:
        pass


def parse_plan(raw: str | dict[str, Any], max_steps: int) -> Plan:
    try:
        value = json.loads(raw) if isinstance(raw, str) else raw
    except json.JSONDecodeError as exc:
        raise PlanningError(AgentError("malformed_plan", "plan is not valid JSON")) from exc
    if not isinstance(value, dict) or not isinstance(value.get("steps"), list):
        raise PlanningError(AgentError("malformed_plan", "plan must contain a steps array"))
    raw_steps = value["steps"]
    if not raw_steps or len(raw_steps) > max_steps:
        raise PlanningError(AgentError("invalid_plan_size", f"plan must contain 1 to {max_steps} steps"))
    steps: list[PlanStep] = []
    for index, item in enumerate(raw_steps):
        if not isinstance(item, dict) or not isinstance(item.get("tool"), str):
            raise PlanningError(AgentError("malformed_plan", f"step {index} has no valid tool"))
        arguments, expected = item.get("arguments", {}), item.get("expected", {})
        if not isinstance(arguments, dict) or not isinstance(expected, dict):
            raise PlanningError(AgentError("malformed_plan", f"step {index} arguments/expected must be objects"))
        steps.append(PlanStep(item["tool"], arguments, expected))
    return Plan(tuple(steps))


class StaticPlanner(Planner):
    """Deterministic planner for tests and explicitly supplied plans."""
    def __init__(self, plan: Plan):
        self._plan = plan

    def plan(self, request: str) -> Plan:
        if not request.strip():
            raise PlanningError(AgentError("empty_request", "task request cannot be empty"))
        return self._plan


class ExamplePlanner(Planner):
    """Offline demo plan; it does not pretend to understand arbitrary requests."""
    def __init__(self, fixture: str, report: str):
        self.fixture, self.report = fixture, report

    def plan(self, request: str) -> Plan:
        return Plan((
            PlanStep("read_fixture", {"name": self.fixture}, {"contains": "Jean Grey"}),
            PlanStep("write_report", {"path": self.report, "content": request}, {"exists": True}),
        ))
