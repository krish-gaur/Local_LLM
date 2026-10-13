import asyncio
import os
import sys
import tempfile
import threading
import types
from pathlib import Path
from unittest import TestCase, mock

from localpilot.agent.executor import Executor, ToolRegistry
from localpilot.agent.permissions import PermissionPolicy
from localpilot.mcp.backend import DiscoveredTool, McpBackendError, OfficialSdkBackend
from localpilot.mcp.client import McpClient, McpTool, normalize_result
from localpilot.mcp.config import McpConfigError, McpServerConfig, load_mcp_config
from localpilot.mcp.redaction import redact_mapping, redact_text
from localpilot.mcp.registry import McpManager
from localpilot.tools.base import PermissionClass, ToolContext

SCHEMA = {"type": "object", "properties": {"url": {"type": "string"}},
          "required": ["url"], "additionalProperties": False}


class FakeBackend:
    def __init__(self, tools=None, result=None, connect_error=None):
        self.tools = tools if tools is not None else [DiscoveredTool("navigate", "untrusted", SCHEMA)]
        self.result = result if result is not None else {"content": [{"text": "ok"}]}
        self.connect_error = connect_error; self.connected = False; self.closed = False; self.calls = []
    def connect(self):
        if self.connect_error: raise self.connect_error
        self.connected = True
    def list_tools(self): return self.tools
    def call_tool(self, name, arguments): self.calls.append((name, arguments)); return self.result
    def close(self): self.closed = True


def config(**kwargs):
    values = dict(name="test", enabled=True, command="mock", allowed_tools={"navigate": PermissionClass.READ_ONLY})
    values.update(kwargs); return McpServerConfig(**values)


class McpTests(TestCase):
    def test_official_sdk_lifecycle_uses_documented_api_and_same_context_task(self):
        task_ids = []
        class AsyncContext:
            async def __aenter__(self): task_ids.append(("stdio-enter", id(asyncio.current_task()))); return "read", "write"
            async def __aexit__(self, *_args): task_ids.append(("stdio-exit", id(asyncio.current_task())))
        class Session:
            def __init__(self, read, write): pass
            async def __aenter__(self): task_ids.append(("session-enter", id(asyncio.current_task()))); return self
            async def __aexit__(self, *_args): task_ids.append(("session-exit", id(asyncio.current_task())))
            async def initialize(self): pass
            async def list_tools(self): return types.SimpleNamespace(tools=[])
            async def call_tool(self, name, arguments): return {"content": "ok"}
        mcp_module = types.ModuleType("mcp"); mcp_module.ClientSession = Session
        mcp_module.StdioServerParameters = lambda **kwargs: kwargs
        client_module = types.ModuleType("mcp.client"); stdio_module = types.ModuleType("mcp.client.stdio")
        stdio_module.stdio_client = lambda params: AsyncContext()
        with mock.patch.dict(sys.modules, {"mcp": mcp_module, "mcp.client": client_module,
                                           "mcp.client.stdio": stdio_module}):
            backend = OfficialSdkBackend(config()); backend.connect(); self.assertEqual(backend.list_tools(), [])
            self.assertEqual(backend.call_tool("x", {}), {"content": "ok"}); backend.close()
        lifecycle_ids = [identifier for name, identifier in task_ids if "enter" in name or "exit" in name]
        self.assertEqual(len(set(lifecycle_ids)), 1)

    def test_config_allowlist_and_environment_indirection(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "mcp.json"
            path.write_text('{"servers":{"safe":{"enabled":true,"command":"server","args":[],"env_from":{"TOKEN":"TEST_TOKEN"},"allowed_tools":{"navigate":"read_only"}}}}')
            with mock.patch.dict(os.environ, {"TEST_TOKEN": "secret-value"}):
                loaded = load_mcp_config(path); environment = loaded.servers["safe"].environment()
        self.assertEqual(environment, {"TOKEN": "secret-value"})
        self.assertNotIn("secret-value", repr(loaded))

    def test_invalid_config_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.json"; path.write_text('{"servers":{"x":{"enabled":true,"command":"x","allowed_tools":{"bad":"invalid"}}}}')
            with self.assertRaises(McpConfigError): load_mcp_config(path)

    def test_connect_discover_register_and_valid_invoke(self):
        backend = FakeBackend(); client = McpClient(config(), backend); tools = client.connect()
        registry = ToolRegistry(); count = client.register_allowed(registry)
        self.assertEqual((len(tools), count), (1, 1))
        result = Executor(registry, PermissionPolicy(Path.cwd())).execute(
            "mcp.test.navigate", {"url": "https://example.test"}, threading.Event())
        self.assertTrue(result.ok); self.assertEqual(backend.calls[0][0], "navigate")
        client.close(); self.assertTrue(backend.closed)

    def test_unknown_disallowed_and_invalid_arguments_never_call_backend(self):
        backend = FakeBackend(); client = McpClient(config(), backend); client.connect()
        self.assertEqual(client.invoke("unknown", {}).error.code, "mcp_tool_denied")
        self.assertEqual(client.invoke("navigate", {}).error.code, "invalid_arguments")
        self.assertEqual(backend.calls, [])

    def test_malformed_schema_and_result(self):
        malformed = FakeBackend(tools=[DiscoveredTool("navigate", "", {"properties": {"x": {"anyOf": []}}})])
        with self.assertRaises(McpBackendError): McpClient(config(), malformed).connect()
        self.assertEqual(normalize_result(None).error.code, "malformed_mcp_result")
        self.assertEqual(normalize_result({}).error.code, "malformed_mcp_result")
        limited = normalize_result({"isError": True, "content": "rate limit; retry later"})
        self.assertTrue(limited.error.recoverable)

    def test_connection_failure_is_diagnostic_and_cleanup_occurs(self):
        backend = FakeBackend(connect_error=McpBackendError("unavailable"))
        manager = McpManager(type("Config", (), {"servers": {"test": config()}})(), lambda _cfg: backend)
        statuses = manager.connect_enabled(ToolRegistry())
        self.assertFalse(statuses[0].connected); self.assertIn("unavailable", statuses[0].detail)
        self.assertTrue(backend.closed)

    def test_explicit_reconnect_rediscovers_without_replaying_calls(self):
        first, second = FakeBackend(), FakeBackend()
        client = McpClient(config(), first); client.connect(); client.reconnect(second)
        self.assertTrue(first.closed); self.assertTrue(second.connected); self.assertEqual(second.calls, [])

    def test_timeout_and_cancellation_are_structured(self):
        backend = FakeBackend(); client = McpClient(config(), backend); client.connect()
        backend.call_tool = mock.Mock(side_effect=McpBackendError("request timeout"))
        result = client.invoke("navigate", {"url": "https://example.test"})
        self.assertTrue(result.error.recoverable)
        tool = McpTool(client, client.tools["navigate"], PermissionClass.READ_ONLY)
        cancelled = threading.Event(); cancelled.set()
        with self.assertRaises(Exception): tool.execute({"url": "https://example.test"}, ToolContext(cancelled))

    def test_secret_redaction(self):
        self.assertEqual(redact_mapping({"API_KEY": "abc", "MODE": "x"})["API_KEY"], "<redacted>")
        text = redact_text("token=abc Bearer xyz", ("abc",))
        self.assertNotIn("abc", text); self.assertNotIn("xyz", text)
