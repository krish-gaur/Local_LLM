"""Central policy that tools and model output cannot override."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from localpilot.agent.types import Json
from localpilot.tools.base import PermissionClass, Tool


class Decision(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_APPROVAL = "require_approval"


@dataclass(frozen=True, slots=True)
class PermissionDecision:
    decision: Decision
    reason: str


class PermissionPolicy:
    def __init__(self, approved_write_root: Path, *, allow_execution: bool = False) -> None:
        self.approved_write_root = approved_write_root.resolve()
        self.allow_execution = allow_execution

    def evaluate(self, tool: Tool, arguments: dict[str, Json], approved: bool = False) -> PermissionDecision:
        if tool.permission == PermissionClass.READ_ONLY:
            return PermissionDecision(Decision.ALLOW, "read-only tool")
        if tool.permission == PermissionClass.SENSITIVE:
            return PermissionDecision(Decision.ALLOW if approved else Decision.REQUIRE_APPROVAL,
                                      "explicit user approval required")
        if tool.permission == PermissionClass.EXECUTION:
            return PermissionDecision(Decision.ALLOW if self.allow_execution else Decision.DENY,
                                      "execution tools are disabled")
        path = arguments.get("path")
        if not isinstance(path, str):
            return PermissionDecision(Decision.DENY, "write tool requires a path")
        candidate = Path(path).resolve()
        try:
            candidate.relative_to(self.approved_write_root)
        except ValueError:
            return PermissionDecision(Decision.DENY, "write path is outside approved root")
        return PermissionDecision(Decision.ALLOW, "write path is contained in approved root")
