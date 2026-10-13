"""Lifecycle owner for configured MCP clients."""
from __future__ import annotations

from collections.abc import Callable

from localpilot.agent.executor import ToolRegistry
from .backend import McpBackendError, OfficialSdkBackend
from .client import Backend, McpClient, McpStatus
from .config import McpConfig, McpServerConfig


class McpManager:
    def __init__(self, config: McpConfig,
                 backend_factory: Callable[[McpServerConfig], Backend] = OfficialSdkBackend) -> None:
        self.config, self.backend_factory = config, backend_factory
        self.clients: dict[str, McpClient] = {}

    def connect_enabled(self, registry: ToolRegistry) -> list[McpStatus]:
        statuses: list[McpStatus] = []
        for name, definition in self.config.servers.items():
            if not definition.enabled:
                statuses.append(McpStatus(name, False, False, 0, 0, "disabled")); continue
            client = McpClient(definition, self.backend_factory(definition)); self.clients[name] = client
            try:
                discovered = client.connect(); registered = client.register_allowed(registry)
                statuses.append(McpStatus(name, True, True, len(discovered), registered, "connected"))
            except Exception as exc:
                client.close()
                reason = str(exc) if isinstance(exc, McpBackendError) else type(exc).__name__
                statuses.append(McpStatus(name, True, False, 0, 0,
                                          f"server_connection_failed: {reason}"))
        return statuses

    def close(self) -> None:
        for client in self.clients.values(): client.close()
        self.clients.clear()

    def __enter__(self) -> "McpManager": return self
    def __exit__(self, *_args: object) -> None: self.close()
