"""Opt-in public-web research acceptance test; never runs in normal CI."""
import os
from pathlib import Path
from uuid import uuid4
from unittest import TestCase, skipUnless

from localpilot.app.main import execute_verified_browser_research
from localpilot.config import Settings
from localpilot.agent.types import TaskState


@skipUnless(os.getenv("JEAN_GREY_REAL_RESEARCH_TEST") == "1", "real multi-page browser research not requested")
class RealVerifiedResearchTests(TestCase):
    def test_search_three_sources_and_verified_report(self):
        settings = Settings.from_env()
        query = os.getenv("JEAN_GREY_REAL_RESEARCH_QUERY", "cheapest BYD car available in India")
        report = settings.report_root / f"real-browser-research-{uuid4().hex}.md"
        task, statuses = execute_verified_browser_research(
            settings, settings.mcp_config_path, query, "India", report, source_count=3)
        self.assertTrue(any(status.connected for status in statuses), statuses)
        self.assertEqual(task.state, TaskState.COMPLETED, task.failure_reason)
        comparison = next(event.result for event in reversed(task.history)
                          if event.tool == "research.compare_sources" and isinstance(event.result, dict))
        self.assertEqual(len(comparison["source_urls"]), 3)
        for url in comparison["source_urls"]: self.assertTrue(url.startswith(("http://", "https://")))
        report_result = next(event.result for event in reversed(task.history)
                             if event.tool == "report.create" and isinstance(event.result, dict))
        self.assertTrue(report_result["verified"])
        self.assertEqual(Path(report_result["path"]).read_text(encoding="utf-8"), report.read_text(encoding="utf-8"))
        # A non-verified conclusion is a valid honest research result when public evidence conflicts.
        self.assertIn("verified_conclusion", comparison)
