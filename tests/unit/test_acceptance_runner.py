from pathlib import Path
from unittest import TestCase


class AcceptanceRunnerTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[2]
        cls.script = (cls.root / "scripts" / "acceptance.ps1").read_text(encoding="utf-8")

    def test_default_is_inspection_only_and_real_stages_are_flag_guarded(self):
        self.assertIn("[switch]$RunMcpSmoke", self.script)
        self.assertIn("[switch]$RunRealWeb", self.script)
        self.assertIn("[string]$ResearchTopic", self.script)
        self.assertIn("[switch]$RunVoiceDiagnostics", self.script)
        self.assertIn("if ($RunMcpSmoke)", self.script)
        self.assertIn("if ($RunRealWeb)", self.script)
        self.assertIn("if ($ResearchTopic)", self.script)
        self.assertIn("if ($RunVoiceDiagnostics)", self.script)
        self.assertIn('no -RunMcpSmoke flag; server was not started', self.script)
        self.assertIn('no -RunRealWeb flag; no external website accessed', self.script)
        self.assertIn("if ($RequestedStageFailed) { exit 1 }", self.script)
        self.assertIn("if ($fail -gt 0) { exit 3 }", self.script)

    def test_reuses_exact_real_test_and_rejects_skips(self):
        exact = ("tests.integration.test_real_playwright_mcp.RealPlaywrightMcpTests."
                 "test_controlled_local_page_navigation_snapshot_url_and_close")
        self.assertIn(exact, self.script)
        self.assertIn('$text -notmatch "skipped"', self.script)
        self.assertIn('"SKIPPED" "unittest skipped; this is not acceptance"', self.script)
        self.assertIn('JG_REAL_BROWSER_SMOKE_7319',
                      (self.root / "tests" / "integration" / "test_real_playwright_mcp.py").read_text())

    def test_reports_are_unique_ignored_and_no_unsafe_execution_is_added(self):
        self.assertIn("[guid]::NewGuid", self.script)
        self.assertIn('acceptance-results', (self.root / ".gitignore").read_text())
        self.assertNotIn("Invoke-Expression", self.script)
        self.assertNotIn("Get-ChildItem Env:", self.script)
        self.assertNotIn("--global", self.script)
        self.assertIn("No complete environment dump", self.script)

    def test_research_and_voice_are_bounded_existing_cli_calls(self):
        self.assertIn('@("browser","--config",$ConfigPath,"--topic",$ResearchTopic', self.script)
        self.assertIn('"--source-count","3","--report",$researchReport', self.script)
        self.assertIn('@("voice","--check","--wake-word","--language","hi","--speak-responses")', self.script)
        self.assertIn("microphone was not opened", self.script)
