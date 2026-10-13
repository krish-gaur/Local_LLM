"""Validated, explicit MCP server allowlist configuration."""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
from typing import Any

from localpilot.tools.base import PermissionClass


class McpConfigError(ValueError): pass


@dataclass(frozen=True, slots=True)
class McpServerConfig:
    name: str
    enabled: bool
    command: str
    args: tuple[str, ...] = ()
    env_from: dict[str, str] = field(default_factory=dict)
    allowed_tools: dict[str, PermissionClass] = field(default_factory=dict)
    timeout_seconds: float = 30.0
    browser: bool = False

    def environment(self) -> dict[str, str]:
        result: dict[str, str] = {}
        for child_name, source_name in self.env_from.items():
            value = os.getenv(source_name)
            if value is None: raise McpConfigError(f"required environment variable is missing: {source_name}")
            result[child_name] = value
        return result


@dataclass(frozen=True, slots=True)
class McpConfig:
    servers: dict[str, McpServerConfig]


def load_mcp_config(path: Path, *, max_bytes: int = 256_000) -> McpConfig:
    if not path.is_file(): raise McpConfigError(f"MCP configuration not found: {path}")
    if path.stat().st_size > max_bytes: raise McpConfigError("MCP configuration is too large")
    try: raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc: raise McpConfigError(f"invalid MCP configuration: {exc}") from exc
    if not isinstance(raw, dict) or not isinstance(raw.get("servers"), dict):
        raise McpConfigError("MCP configuration must contain a servers object")
    servers: dict[str, McpServerConfig] = {}
    for name, value in raw["servers"].items():
        if not isinstance(name, str) or not name.replace("-", "_").isalnum() or not isinstance(value, dict):
            raise McpConfigError("invalid MCP server name or definition")
        allowed_raw = value.get("allowed_tools", {})
        if not isinstance(allowed_raw, dict): raise McpConfigError(f"server {name}: allowed_tools must be an object")
        try: allowed = {str(tool): PermissionClass(str(permission)) for tool, permission in allowed_raw.items()}
        except ValueError as exc: raise McpConfigError(f"server {name}: invalid tool permission") from exc
        command, args, env_from = value.get("command"), value.get("args", []), value.get("env_from", {})
        if not isinstance(command, str) or not command or not isinstance(args, list) or not all(isinstance(x, str) for x in args):
            raise McpConfigError(f"server {name}: command/args are invalid")
        if not isinstance(env_from, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in env_from.items()):
            raise McpConfigError(f"server {name}: env_from must map child names to environment names")
        timeout = float(value.get("timeout_seconds", 30))
        if not 1 <= timeout <= 300: raise McpConfigError(f"server {name}: timeout must be 1..300 seconds")
        servers[name] = McpServerConfig(name, bool(value.get("enabled", False)), command, tuple(args),
            dict(env_from), allowed, timeout, bool(value.get("browser", False)))
    return McpConfig(servers)
