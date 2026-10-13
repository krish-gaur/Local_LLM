"""Deterministic tools proving the runtime without external services."""
from __future__ import annotations

from pathlib import Path
import time

from localpilot.agent.types import Json
from .base import PermissionClass, Tool, ToolContext, ToolResult

OBJECT = "object"


class ReadFixtureTool(Tool):
    name, description, permission = "read_fixture", "Read an approved test fixture", PermissionClass.READ_ONLY
    schema = {"type": OBJECT, "properties": {"name": {"type": "string"}}, "required": ["name"]}
    def __init__(self, root: Path): self.root = root.resolve()
    def execute(self, arguments: dict[str, Json], context: ToolContext) -> ToolResult:
        context.raise_if_cancelled()
        path = (self.root / str(arguments["name"])).resolve()
        try: path.relative_to(self.root)
        except ValueError: return ToolResult.failure("path_denied", "fixture path escaped root")
        if not path.is_file(): return ToolResult.failure("not_found", "fixture not found")
        return ToolResult.success({"content": path.read_text(encoding="utf-8"), "name": path.name})


class SearchDocumentsTool(Tool):
    name, description, permission = "search_documents", "Search approved local documents", PermissionClass.READ_ONLY
    schema = {"type": OBJECT, "properties": {"query": {"type": "string"}}, "required": ["query"]}
    def __init__(self, documents: dict[str, str]): self.documents = documents
    def execute(self, arguments: dict[str, Json], context: ToolContext) -> ToolResult:
        context.raise_if_cancelled(); query = str(arguments["query"]).lower()
        matches = [{"name": name, "content": text} for name, text in self.documents.items() if query in text.lower()]
        return ToolResult.success({"matches": matches, "count": len(matches)})


class WriteReportTool(Tool):
    name, description, permission = "write_report", "Write a report in the approved directory", PermissionClass.WRITE
    schema = {"type": OBJECT, "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}
    def execute(self, arguments: dict[str, Json], context: ToolContext) -> ToolResult:
        context.raise_if_cancelled(); path = Path(str(arguments["path"])); path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(arguments["content"]), encoding="utf-8")
        return ToolResult.success({"path": str(path.resolve()), "exists": path.is_file(), "bytes": path.stat().st_size})


class RecoverableFailureTool(Tool):
    name, description, permission = "recoverable_failure", "Fail recoverably a configured number of times", PermissionClass.READ_ONLY
    schema = {"type": OBJECT, "properties": {}, "required": []}
    def __init__(self, failures: int = 1): self.failures, self.calls = failures, 0
    def execute(self, arguments: dict[str, Json], context: ToolContext) -> ToolResult:
        self.calls += 1
        if self.calls <= self.failures: return ToolResult.failure("temporary_failure", "simulated transient failure", True)
        return ToolResult.success({"recovered": True, "calls": self.calls})


class TimeoutTool(Tool):
    name, description, permission = "simulate_timeout", "Cooperatively simulate timeout", PermissionClass.READ_ONLY
    schema = {"type": OBJECT, "properties": {"seconds": {"type": "number"}}, "required": ["seconds"]}
    timeout_seconds = 0.02
    def execute(self, arguments: dict[str, Json], context: ToolContext) -> ToolResult:
        end = time.monotonic() + float(arguments["seconds"])
        while time.monotonic() < end:
            context.raise_if_cancelled(); time.sleep(0.002)
        return ToolResult.success({"finished": True})


class DestructiveTool(Tool):
    name, description, permission = "destructive_action", "Simulate destructive action", PermissionClass.SENSITIVE
    schema = {"type": OBJECT, "properties": {"target": {"type": "string"}}, "required": ["target"]}
    def execute(self, arguments: dict[str, Json], context: ToolContext) -> ToolResult:
        return ToolResult.success({"deleted": str(arguments["target"])})


class NonRecoverableFailureTool(Tool):
    name, description, permission = "fatal_failure", "Fail permanently", PermissionClass.READ_ONLY
    schema = {"type": OBJECT, "properties": {}, "required": []}
    def __init__(self): self.calls = 0
    def execute(self, arguments: dict[str, Json], context: ToolContext) -> ToolResult:
        self.calls += 1; return ToolResult.failure("fatal", "simulated permanent failure", False)
