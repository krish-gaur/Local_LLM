"""Registered-only tool execution with schema, permission, and timeout controls."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
import threading

from localpilot.agent.permissions import Decision, PermissionDecision, PermissionPolicy
from localpilot.agent.types import AgentError, Json
from localpilot.tools.base import Tool, ToolContext, ToolFailure, ToolResult, validate_arguments


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if not tool.name or tool.name in self._tools:
            raise ValueError(f"tool name is empty or already registered: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._tools))


class Executor:
    def __init__(self, registry: ToolRegistry, policy: PermissionPolicy):
        self.registry, self.policy = registry, policy
        self._active: set[threading.Event] = set()
        self._active_lock = threading.Lock()

    def cancel_active(self) -> None:
        with self._active_lock:
            for event in self._active:
                event.set()

    def permission(self, name: str, arguments: dict[str, Json], approved: bool = False) -> PermissionDecision:
        tool = self.registry.get(name)
        if tool is None:
            return PermissionDecision(Decision.DENY, f"unregistered tool: {name}")
        return self.policy.evaluate(tool, arguments, approved)

    def execute(self, name: str, arguments: dict[str, Json], cancellation: threading.Event,
                approved: bool = False) -> ToolResult:
        tool = self.registry.get(name)
        if tool is None:
            return ToolResult.failure("unregistered_tool", f"unregistered tool: {name}")
        errors = validate_arguments(tool.schema, arguments)
        if errors:
            return ToolResult.failure("invalid_arguments", "; ".join(errors))
        decision = self.policy.evaluate(tool, arguments, approved)
        if decision.decision != Decision.ALLOW:
            code = "approval_required" if decision.decision == Decision.REQUIRE_APPROVAL else "permission_denied"
            return ToolResult.failure(code, decision.reason)
        if cancellation.is_set():
            return ToolResult.failure("cancelled", "task was cancelled")
        operation_cancel = threading.Event()
        with self._active_lock:
            self._active.add(operation_cancel)
        pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"tool-{name}")
        future = pool.submit(tool.execute, arguments, ToolContext(operation_cancel))
        try:
            result = future.result(timeout=tool.timeout_seconds)
        except FutureTimeout:
            operation_cancel.set()  # cooperative propagation; Python cannot safely kill a blocked thread
            future.cancel()
            result = ToolResult.failure("tool_timeout", f"tool exceeded {tool.timeout_seconds}s", True)
        except ToolFailure as exc:
            result = ToolResult(False, error=exc.error)
        except Exception as exc:  # isolate tool defects from the runtime
            result = ToolResult.failure("tool_exception", f"tool raised {type(exc).__name__}")
        finally:
            with self._active_lock:
                self._active.discard(operation_cancel)
            pool.shutdown(wait=False, cancel_futures=True)
        return result
