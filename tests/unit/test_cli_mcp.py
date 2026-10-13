import io
import tempfile
from pathlib import Path
from unittest import TestCase, mock

from localpilot.app.main import build_parser, run


class McpCliTests(TestCase):
    def test_help_architecture_exposes_mcp_and_browser_commands(self):
        parser = build_parser()
        self.assertEqual(parser.parse_args(["mcp", "--check"]).command, "mcp")
        self.assertEqual(parser.parse_args(["browser", "--check"]).command, "browser")

    def test_missing_configuration_is_clear_not_crash(self):
        with tempfile.TemporaryDirectory() as directory, \
             mock.patch("sys.stdout", new_callable=io.StringIO) as output:
            code = run(["mcp", "--check", "--config", str(Path(directory) / "missing.json")])
        self.assertEqual(code, 3); self.assertIn("configuration not found", output.getvalue())

    def test_disabled_browser_is_reported_without_startup(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "mcp.json"
            path.write_text('{"servers":{"playwright":{"enabled":false,"command":"not-run","browser":true,"allowed_tools":{}}}}')
            with mock.patch("sys.stdout", new_callable=io.StringIO) as output:
                code = run(["browser", "--check", "--config", str(path)])
        self.assertEqual(code, 3); self.assertIn('"detail": "server_disabled"', output.getvalue())

    def test_version_is_available_without_loading_integrations(self):
        with self.assertRaises(SystemExit) as raised, mock.patch("sys.stdout", new_callable=io.StringIO) as output:
            build_parser().parse_args(["--version"])
        self.assertEqual(raised.exception.code, 0); self.assertIn("Jean Grey 0.3.3", output.getvalue())

    def test_invalid_configuration_is_distinguished(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "mcp.json"; path.write_text("not json")
            with mock.patch("sys.stdout", new_callable=io.StringIO) as output:
                code = run(["mcp", "--check", "--config", str(path)])
        self.assertEqual(code, 3); self.assertIn('"configuration_status": "invalid"', output.getvalue())

    def test_browser_check_does_not_start_non_browser_server(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "mcp.json"
            path.write_text('{"servers":{"unrelated":{"enabled":true,"command":"must-not-run","browser":false,"allowed_tools":{}},"playwright":{"enabled":false,"command":"npx","browser":true,"allowed_tools":{}}}}')
            with mock.patch("sys.stdout", new_callable=io.StringIO) as output:
                code = run(["browser", "--check", "--config", str(path)])
        self.assertEqual(code, 3); self.assertIn("not_selected_for_browser_check", output.getvalue())

    def test_missing_sdk_is_reported_before_starting_server(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "mcp.json"
            path.write_text('{"servers":{"playwright":{"enabled":true,"command":"npx","browser":true,"allowed_tools":{}}}}')
            python = {"version": "3.11.0", "supported": True, "virtual_environment": True,
                      "mcp_sdk_available": False, "next_command": None, "requirement": "Python 3.11+"}
            with mock.patch("localpilot.diagnostics.python_prerequisites", return_value=python), \
                 mock.patch("sys.stdout", new_callable=io.StringIO) as output:
                code = run(["browser", "--check", "--config", str(path)])
        self.assertEqual(code, 3); self.assertIn("dependency_missing: mcp SDK", output.getvalue())
