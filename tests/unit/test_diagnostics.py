import json
import tempfile
from pathlib import Path
from unittest import TestCase, mock

from localpilot.diagnostics import (browser_prerequisite, configured_browser,
                                    playwright_mcp_prerequisite, project_install_status)


class DiagnosticTests(TestCase):
    def test_configured_browser_argument(self):
        self.assertEqual(configured_browser(("--browser", "msedge", "--isolated")), "msedge")
        self.assertIsNone(configured_browser(("--isolated",)))

    def test_missing_browser_has_exact_manual_next_command(self):
        with mock.patch("localpilot.diagnostics.executable", return_value=None), \
             mock.patch("localpilot.diagnostics.os.name", "posix"):
            result = browser_prerequisite("msedge")
        self.assertFalse(result["available"]); self.assertEqual(result["status"], "browser_unavailable")
        self.assertEqual(result["next_command"], "winget install Microsoft.Edge")

    def test_playwright_package_version_must_match_pin(self):
        with tempfile.TemporaryDirectory() as directory:
            package = Path(directory) / "node_modules" / "@playwright" / "mcp" / "package.json"
            package.parent.mkdir(parents=True); package.write_text('{"version":"0.0.82"}')
            status = playwright_mcp_prerequisite(("@playwright/mcp@0.0.83",), Path(directory))
        self.assertTrue(status["project_local_available"]); self.assertFalse(status["version_match"])

    def test_editable_install_detection_does_not_install(self):
        fake = mock.Mock(version="0.3.2")
        fake.read_text.return_value = json.dumps({"dir_info": {"editable": True}})
        with tempfile.TemporaryDirectory() as directory, \
             mock.patch("importlib.metadata.distribution", return_value=fake):
            status = project_install_status(Path(directory))
        self.assertTrue(status["package"]["installed"]); self.assertTrue(status["package"]["editable"])
