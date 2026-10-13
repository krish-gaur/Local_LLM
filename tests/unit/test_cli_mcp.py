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
        self.assertEqual(code, 3); self.assertIn('"detail": "disabled"', output.getvalue())
