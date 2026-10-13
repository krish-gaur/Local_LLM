"""Opt-in real Playwright MCP tests. No mocks and no automatic downloads."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
import threading
from pathlib import Path
from unittest import TestCase, skipUnless

from localpilot.agent.executor import Executor, ToolRegistry
from localpilot.agent.permissions import PermissionPolicy
from localpilot.browser.tools import register_browser_tools
from localpilot.mcp.config import load_mcp_config
from localpilot.mcp.registry import McpManager

_RUN = os.getenv("JEAN_GREY_REAL_MCP_TEST") == "1"
_REASON = ("real Playwright MCP test not requested; on Windows run: "
           "$env:JEAN_GREY_REAL_MCP_TEST='1'; python -m unittest "
           "tests.integration.test_real_playwright_mcp -v")


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = b"<!doctype html><title>Jean Grey MCP smoke</title><h1>JG_REAL_BROWSER_SMOKE_7319</h1>"
        self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
    def log_message(self, *_args): pass


@skipUnless(_RUN, _REASON)
class RealPlaywrightMcpTests(TestCase):
    def _connect(self):
        config_path = Path(os.environ["JEAN_GREY_MCP_CONFIG"])
        config = load_mcp_config(config_path); registry = ToolRegistry(); manager = McpManager(config)
        try:
            statuses = manager.connect_enabled(registry)
            self.assertTrue(any(status.connected and status.discovered > 0 for status in statuses), statuses)
            discovered = set()
            for client in manager.clients.values():
                if client.connected and client.config.browser:
                    discovered.update(client.tools); register_browser_tools(client, registry)
            self.assertIn("browser_navigate", discovered); self.assertIn("browser_snapshot", discovered)
            return manager, registry
        except BaseException:
            manager.close(); raise

    def test_controlled_local_page_navigation_snapshot_url_and_close(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True); worker.start()
        url = f"http://127.0.0.1:{server.server_port}/smoke"
        manager = None
        try:
            manager, registry = self._connect()
            executor = Executor(registry, PermissionPolicy(Path.cwd())); cancel = threading.Event()
            navigation = executor.execute("browser.navigate", {"url": url}, cancel)
            snapshot = executor.execute("browser.get_page_content", {}, cancel)
            tabs = executor.execute("browser.list_tabs", {"action": "list"}, cancel)
            self.assertTrue(navigation.ok, navigation.error); self.assertTrue(snapshot.ok, snapshot.error)
            self.assertTrue(tabs.ok, tabs.error)
            self.assertIn("JG_REAL_BROWSER_SMOKE_7319", str(snapshot.data))
            self.assertIn(url, str(tabs.data))
        finally:
            if manager is not None:
                manager.close(); self.assertEqual(manager.clients, {})
            server.shutdown(); server.server_close(); worker.join(timeout=2)
            self.assertFalse(worker.is_alive())

    @skipUnless(os.getenv("JEAN_GREY_REAL_WEB_TEST") == "1",
                "optional real-web test not requested; set JEAN_GREY_REAL_WEB_TEST=1")
    def test_optional_real_web_page(self):
        url = os.getenv("JEAN_GREY_REAL_TEST_URL", "https://example.com/")
        manager, registry = self._connect()
        try:
            executor = Executor(registry, PermissionPolicy(Path.cwd())); cancel = threading.Event()
            navigation = executor.execute("browser.navigate", {"url": url}, cancel)
            snapshot = executor.execute("browser.get_page_content", {}, cancel)
            tabs = executor.execute("browser.list_tabs", {"action": "list"}, cancel)
            self.assertTrue(navigation.ok, navigation.error); self.assertTrue(snapshot.ok, snapshot.error)
            self.assertTrue(tabs.ok, tabs.error); self.assertTrue(str(snapshot.data).strip())
            self.assertIn(url, str(tabs.data))
        finally: manager.close()
