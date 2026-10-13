"""MCP discovery/invocation facade integrated with Jean Grey's typed tools."""
from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Protocol

from localpilot.agent.executor import ToolRegistry
from localpilot.agent.types import Json
from localpilot.tools.base import (PermissionClass, Tool, ToolContext, ToolResult,
                                   validate_arguments, validate_schema)
from .backend import DiscoveredTool, McpBackendError, OfficialSdkBackend
from .config import McpServerConfig
from .redaction import redact_text


class Backend(Protocol):
    def connect(self) -> None: ...
    def list_tools(self) -> list[DiscoveredTool]: ...
    def call_tool(self, name: str, arguments: dict[str, Any]) -> Any: ...
    def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class McpStatus:
    name: str
    enabled: bool
    connected: bool
    discovered: int
    registered: int
    detail: str


def _json_safe(value: Any, *, max_chars: int = 200_000) -> Json:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value[:max_chars] if isinstance(value, str) else value
    if isinstance(value, list): return [_json_safe(item, max_chars=max_chars) for item in value[:1000]]
    if isinstance(value, dict): return {str(k): _json_safe(v, max_chars=max_chars) for k, v in list(value.items())[:1000]}
    if hasattr(value, "model_dump"): return _json_safe(value.model_dump(exclude_none=True), max_chars=max_chars)
    if hasattr(value, "text"): return str(value.text)[:max_chars]
    return str(value)[:max_chars]


def normalize_result(response: Any, max_chars: int = 200_000) -> ToolResult:
    try:
        if response is None: return ToolResult.failure("malformed_mcp_result", "MCP returned no result")
        is_error = bool(getattr(response, "isError", False))
        structured = getattr(response, "structuredContent", None)
        content = getattr(response, "content", None)
        if isinstance(response, dict):
            is_error = bool(response.get("isError", response.get("is_error", False)))
            structured = response.get("structuredContent", response.get("structured_content"))
            content = response.get("content")
        data: Json = _json_safe(structured if structured is not None else content, max_chars=max_chars)
        if is_error: return ToolResult.failure("mcp_tool_error", redact_text(str(data)), _recoverable(str(data)))
        if data is None: return ToolResult.failure("malformed_mcp_result", "MCP result contained no content")
        encoded = json.dumps(data, ensure_ascii=False)
        if len(encoded) > max_chars: return ToolResult.success({"content": encoded[:max_chars], "truncated": True})
        return ToolResult.success(data)
    except Exception as exc:
        return ToolResult.failure("malformed_mcp_result", f"could not normalize MCP result: {type(exc).__name__}")


def _recoverable(message: str) -> bool:
    text = message.lower()
    return any(word in text for word in ("timeout", "temporar", "rate limit", "closed", "disconnect", "stale"))


class McpTool(Tool):
    def __init__(self, client: "McpClient", remote: DiscoveredTool, permission: PermissionClass) -> None:
        self.client, self.remote_name = client, remote.name
        self.name = f"mcp.{client.config.name}.{remote.name}"
        self.description = f"UNTRUSTED MCP METADATA: {remote.description[:1000]}"
        self.schema = remote.input_schema
        self.permission = permission
        self.timeout_seconds = client.config.timeout_seconds

    def execute(self, arguments: dict[str, Json], context: ToolContext) -> ToolResult:
        context.raise_if_cancelled()
        result = self.client.invoke(self.remote_name, arguments)
        context.raise_if_cancelled()
        return result


class McpClient:
    def __init__(self, config: McpServerConfig, backend: Backend | None = None) -> None:
        self.config = config
        self.backend: Backend = backend or OfficialSdkBackend(config)
        self.tools: dict[str, DiscoveredTool] = {}
        self.connected = False

    def connect(self) -> list[DiscoveredTool]:
        if not self.config.enabled: raise McpBackendError(f"MCP server is disabled: {self.config.name}")
        self.backend.connect()
        discovered = self.backend.list_tools()
        names: set[str] = set()
        for tool in discovered:
            if tool.name in names: raise McpBackendError(f"duplicate MCP tool: {tool.name}")
            names.add(tool.name)
            if validate_schema(tool.input_schema):
                raise McpBackendError(f"unsupported schema for MCP tool: {tool.name}")
        self.tools = {tool.name: tool for tool in discovered}
        self.connected = True
        return discovered

    def register_allowed(self, registry: ToolRegistry) -> int:
        if not self.connected: raise McpBackendError("MCP server is not connected")
        count = 0
        for name, permission in self.config.allowed_tools.items():
            remote = self.tools.get(name)
            if remote is None: continue
            registry.register(McpTool(self, remote, permission)); count += 1
        return count

    def invoke(self, name: str, arguments: dict[str, Json]) -> ToolResult:
        if name not in self.config.allowed_tools: return ToolResult.failure("mcp_tool_denied", "MCP tool is not allowlisted")
        tool = self.tools.get(name)
        if tool is None: return ToolResult.failure("mcp_tool_unavailable", "MCP tool was not discovered")
        errors = validate_arguments(tool.input_schema, arguments)
        if errors: return ToolResult.failure("invalid_arguments", "; ".join(errors))
        try: return normalize_result(self.backend.call_tool(name, arguments))
        except McpBackendError as exc:
            message = redact_text(str(exc), tuple(self.config.environment().values()))
            return ToolResult.failure("mcp_connection_error", message, _recoverable(message))
        except Exception as exc:
            return ToolResult.failure("mcp_connection_error", f"MCP call failed: {type(exc).__name__}", True)

    def reconnect(self, backend: Backend | None = None) -> list[DiscoveredTool]:
        """Explicit reconnect; calls are never replayed automatically to avoid duplicate side effects."""
        self.close()
        self.backend = backend or OfficialSdkBackend(self.config)
        return self.connect()

    def close(self) -> None:
        self.backend.close(); self.connected = False
