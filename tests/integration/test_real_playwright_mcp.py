"""Opt-in real integration; never starts/downloads a server in normal test runs."""
import os
import threading
from pathlib import Path
from unittest import TestCase, skipUnless

from localpilot.agent.executor import Executor, ToolRegistry
from localpilot.agent.permissions import PermissionPolicy
from localpilot.browser.tools import register_browser_tools
from localpilot.mcp.config import load_mcp_config
from localpilot.mcp.registry import McpManager


@skipUnless(os.getenv("JEAN_GREY_REAL_MCP_TEST") == "1", "real Playwright MCP test not requested")
class RealPlaywrightMcpTests(TestCase):
    def test_navigation_and_snapshot(self):
        config_path = Path(os.environ["JEAN_GREY_MCP_CONFIG"])
        test_url = os.environ["JEAN_GREY_REAL_TEST_URL"]
        config = load_mcp_config(config_path); registry = ToolRegistry(); manager = McpManager(config)
        try:
            statuses = manager.connect_enabled(registry)
            self.assertTrue(any(status.connected for status in statuses))
            for client in manager.clients.values():
                if client.connected and client.config.browser: register_browser_tools(client, registry)
            executor = Executor(registry, PermissionPolicy(Path.cwd()))
            navigation = executor.execute("browser.navigate", {"url": test_url}, threading.Event())
            snapshot = executor.execute("browser.get_page_content", {}, threading.Event())
            self.assertTrue(navigation.ok, navigation.error)
            self.assertTrue(snapshot.ok, snapshot.error)
            self.assertTrue(snapshot.data["raw"])
        finally:
            manager.close()
