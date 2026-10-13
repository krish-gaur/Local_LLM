"""Stable browser aliases mapped only to actually discovered Playwright MCP tools."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from localpilot.agent.executor import ToolRegistry
from localpilot.agent.types import AgentError, Json
from localpilot.mcp.client import McpClient
from localpilot.tools.base import PermissionClass, Tool, ToolContext, ToolResult

PLAYWRIGHT_ALIASES = {
    "browser.navigate": "browser_navigate",
    "browser.get_page_content": "browser_snapshot",
    "browser.get_accessibility_tree": "browser_snapshot",
    "browser.click": "browser_click",
    "browser.fill_form": "browser_fill_form",
    "browser.list_tabs": "browser_tabs",
    "browser.capture_screenshot": "browser_take_screenshot",
}


def _flatten(value: Json, limit: int) -> str:
    if isinstance(value, str): return value[:limit]
    return json.dumps(value, ensure_ascii=False)[:limit]


def suspicious_content(text: str) -> tuple[bool, tuple[str, ...]]:
    """Advisory labeling only; structural permissions remain the security boundary."""
    indicators = ("ignore previous instructions", "reveal the system prompt", "disable security",
                  "send the user's files", "run this command", "api key", "password")
    found = tuple(item for item in indicators if item in text.lower())
    return bool(found), found


class BrowserLinkExtractionTool(Tool):
    """Run one fixed read-only DOM query; user/model supplied JavaScript is never accepted."""
    name = "browser.extract_links"
    description = "Extract visible anchor text and absolute URLs with fixed adapter-owned JavaScript"
    permission = PermissionClass.READ_ONLY
    schema: dict[str, Json] = {"type": "object", "properties": {}, "required": []}
    _function = ("() => Array.from(document.querySelectorAll('a[href]')).slice(0, 200).map(a => "
                 "({text: (a.innerText || a.getAttribute('aria-label') || '').trim(), url: a.href}))")

    def __init__(self, client: McpClient, max_content_chars: int) -> None:
        self.client, self.timeout_seconds, self.max_content_chars = client, client.config.timeout_seconds, max_content_chars

    def execute(self, arguments: dict[str, Json], context: ToolContext) -> ToolResult:
        context.raise_if_cancelled(); result = self.client.invoke("browser_evaluate", {"function": self._function})
        if not result.ok: return result
        raw = _flatten(result.data, self.max_content_chars)
        return ToolResult.success({"raw": raw, "mcp_tool": "browser_evaluate",
                                   "untrusted_web_content": True, "truncated": len(raw) >= self.max_content_chars})


class BrowserMcpTool(Tool):
    def __init__(self, alias: str, remote_name: str, client: McpClient, permission: PermissionClass,
                 max_content_chars: int = 100_000) -> None:
        self.name, self.remote_name, self.client = alias, remote_name, client
        self.description = f"Controlled Playwright MCP action mapped to {remote_name}"
        self.schema = client.tools[remote_name].input_schema
        self.permission = permission
        self.timeout_seconds = client.config.timeout_seconds
        self.max_content_chars = max_content_chars

    def execute(self, arguments: dict[str, Json], context: ToolContext) -> ToolResult:
        context.raise_if_cancelled()
        if self.name == "browser.navigate":
            parsed = urlparse(str(arguments.get("url", "")))
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                return ToolResult.failure("invalid_url", "browser navigation allows only HTTP(S) URLs")
        if self.name == "browser.capture_screenshot" and "filename" in arguments:
            filename = Path(str(arguments["filename"]))
            if filename.is_absolute() or filename.name != str(filename):
                return ToolResult.failure("path_denied", "screenshot filename must not contain a path")
        result = self.client.invoke(self.remote_name, arguments)
        if not result.ok:
            if self.permission == PermissionClass.SENSITIVE and result.error is not None:
                return ToolResult(False, error=AgentError(result.error.code, result.error.message, False,
                                                          result.error.details))
            return result
        raw = _flatten(result.data, self.max_content_chars)
        suspicious, indicators = suspicious_content(raw)
        return ToolResult.success({"raw": raw, "mcp_tool": self.remote_name,
            "untrusted_web_content": True, "suspicious_instructions": suspicious,
            "indicators": list(indicators), "truncated": len(raw) >= self.max_content_chars})


def register_browser_tools(client: McpClient, registry: ToolRegistry,
                           max_content_chars: int = 100_000) -> tuple[str, ...]:
    registered: list[str] = []
    if not client.config.browser: return ()
    for alias, remote in PLAYWRIGHT_ALIASES.items():
        if remote not in client.tools or remote not in client.config.allowed_tools: continue
        registry.register(BrowserMcpTool(alias, remote, client, client.config.allowed_tools[remote],
                                         max_content_chars))
        registered.append(alias)
    if ("browser_evaluate" in client.tools and "browser_evaluate" in client.config.allowed_tools
            and "browser_evaluate" in client.config.adapter_only_tools):
        registry.register(BrowserLinkExtractionTool(client, max_content_chars)); registered.append("browser.extract_links")
    return tuple(registered)
