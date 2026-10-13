import os
import tempfile
import threading
from pathlib import Path
from unittest import TestCase, skipIf

from localpilot.agent.executor import Executor, ToolRegistry
from localpilot.agent.permissions import PermissionPolicy
from localpilot.agent.planner import StaticPlanner
from localpilot.agent.runtime import AgentRuntime
from localpilot.agent.types import Plan, PlanStep, TaskState
from localpilot.browser.reports import OverwriteResearchReportTool, ResearchReportTool
from localpilot.tools.base import ToolContext


def arguments(path, format_name="markdown"):
    return {"path": str(path), "topic": "topic", "format": format_name,
            "sources": [{"url": "https://source.test", "evidence": "observed"}]}


class ReportTests(TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name); self.tool = ResearchReportTool(self.root)
    def tearDown(self): self.temp.cleanup()

    def test_markdown_and_csv_creation_are_verified(self):
        markdown = self.tool.execute(arguments(self.root / "report.md"), ToolContext(threading.Event()))
        csv_result = self.tool.execute(arguments(self.root / "report.csv", "csv"), ToolContext(threading.Event()))
        self.assertTrue(markdown.ok and csv_result.ok)
        self.assertIn("https://source.test", (self.root / "report.md").read_text())
        self.assertIn("source_url,observed_evidence", (self.root / "report.csv").read_text())

    def test_traversal_absolute_outside_and_output_limits_are_denied(self):
        self.assertEqual(self.tool.execute(arguments(self.root / ".." / "outside.md"), ToolContext(threading.Event())).error.code, "path_denied")
        tiny = ResearchReportTool(self.root, max_output_bytes=10)
        self.assertEqual(tiny.execute(arguments(self.root / "tiny.md"), ToolContext(threading.Event())).error.code, "output_too_large")

    @skipIf(os.name == "nt", "symlink creation may require Windows developer mode")
    def test_symlink_escape_is_denied(self):
        outside = self.root.parent / "outside-reports"; outside.mkdir(exist_ok=True)
        link = self.root / "link"; link.symlink_to(outside, target_is_directory=True)
        result = self.tool.execute(arguments(link / "escape.md"), ToolContext(threading.Event()))
        self.assertEqual(result.error.code, "path_denied"); self.assertFalse((outside / "escape.md").exists())
        outside.rmdir()

    def test_existing_file_needs_sensitive_overwrite_approval(self):
        target = self.root / "report.md"; target.write_text("old")
        registry = ToolRegistry(); registry.register(self.tool); registry.register(OverwriteResearchReportTool(self.root))
        policy = PermissionPolicy(self.root)
        create = AgentRuntime(StaticPlanner(Plan((PlanStep("report.create", arguments(target)),))), Executor(registry, policy)).run("create")
        self.assertEqual(create.state, TaskState.FAILED); self.assertEqual(target.read_text(), "old")
        runtime = AgentRuntime(StaticPlanner(Plan((PlanStep("report.overwrite", arguments(target), {"verified": True}),))), Executor(registry, policy))
        overwrite = runtime.run("overwrite")
        self.assertEqual(overwrite.state, TaskState.WAITING_FOR_APPROVAL); self.assertEqual(target.read_text(), "old")
        runtime.run_task(overwrite, approvals={0})
        self.assertEqual(overwrite.state, TaskState.COMPLETED); self.assertIn("observed", target.read_text())

    def test_filesystem_failure_does_not_claim_success(self):
        directory_target = self.root / "report.md"; directory_target.mkdir()
        result = self.tool.execute(arguments(directory_target), ToolContext(threading.Event()))
        self.assertFalse(result.ok)
