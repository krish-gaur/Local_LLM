"""Official Python MCP SDK transport, loaded only when configured."""
from __future__ import annotations

import asyncio
from concurrent.futures import Future, TimeoutError as FutureTimeout
from dataclasses import dataclass
import threading
from typing import Any, Coroutine

from .config import McpServerConfig


class McpBackendError(RuntimeError): pass


@dataclass(frozen=True, slots=True)
class DiscoveredTool:
    name: str
    description: str
    input_schema: dict[str, Any]


class AsyncLoopRunner:
    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.loop.run_forever, name="jean-grey-mcp", daemon=True)
        self.thread.start()

    def submit(self, coroutine: Coroutine[Any, Any, Any]) -> Future[Any]:
        return asyncio.run_coroutine_threadsafe(coroutine, self.loop)

    def run(self, coroutine: Coroutine[Any, Any, Any], timeout: float) -> Any:
        future = self.submit(coroutine)
        try: return future.result(timeout)
        except FutureTimeout as exc:
            future.cancel(); raise McpBackendError(f"MCP request exceeded {timeout} seconds") from exc

    def close(self) -> None:
        self.loop.call_soon_threadsafe(self.loop.stop); self.thread.join(timeout=2); self.loop.close()


class OfficialSdkBackend:
    """stdio lifecycle using mcp.ClientSession and mcp.client.stdio.stdio_client."""
    def __init__(self, config: McpServerConfig) -> None:
        self.config, self.runner = config, AsyncLoopRunner()
        self._session = None
        self._ready: Future[None] = Future()
        self._stop: asyncio.Event | None = None
        self._serve_future: Future[Any] | None = None

    async def _serve(self) -> None:
        """Enter and exit SDK/AnyIO contexts in the same long-lived task."""
        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
            params = StdioServerParameters(command=self.config.command, args=list(self.config.args),
                                           env=self.config.environment() or None)
            self._stop = asyncio.Event()
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    self._session = session
                    await session.initialize()
                    self._ready.set_result(None)
                    await self._stop.wait()
        except BaseException as exc:
            if not self._ready.done(): self._ready.set_exception(exc)
            elif not isinstance(exc, asyncio.CancelledError): raise
        finally:
            self._session = None

    def connect(self) -> None:
        self._serve_future = self.runner.submit(self._serve())
        try: self._ready.result(self.config.timeout_seconds)
        except Exception as exc:
            self.close()
            if isinstance(exc, McpBackendError): raise
            if isinstance(exc, FutureTimeout): raise McpBackendError("MCP initialization timed out") from exc
            if isinstance(exc, ImportError): raise McpBackendError("official 'mcp' Python SDK is not installed") from exc
            raise McpBackendError(f"MCP initialization failed: {type(exc).__name__}") from exc

    async def _list(self) -> list[DiscoveredTool]:
        response = await self._session.list_tools()
        return [DiscoveredTool(tool.name, tool.description or "", dict(tool.inputSchema)) for tool in response.tools]

    def list_tools(self) -> list[DiscoveredTool]:
        if self._session is None: raise McpBackendError("MCP server is not connected")
        return self.runner.run(self._list(), self.config.timeout_seconds)

    async def _call(self, name: str, arguments: dict[str, Any]) -> Any:
        return await self._session.call_tool(name, arguments=arguments)

    def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        if self._session is None: raise McpBackendError("MCP server is not connected")
        return self.runner.run(self._call(name, arguments), self.config.timeout_seconds)

    def close(self) -> None:
        if self.runner.thread.is_alive():
            if self._stop is not None: self.runner.loop.call_soon_threadsafe(self._stop.set)
            if self._serve_future is not None:
                try: self._serve_future.result(min(self.config.timeout_seconds, 5))
                except Exception: self._serve_future.cancel()
            self.runner.close()
        self._session = self._stop = self._serve_future = None
