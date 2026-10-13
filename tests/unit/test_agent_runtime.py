import tempfile
import threading
import time
from pathlib import Path
from unittest import TestCase

from localpilot.agent.executor import Executor, ToolRegistry
from localpilot.agent.permissions import PermissionPolicy
from localpilot.agent.planner import PlanningError, Planner, StaticPlanner, parse_plan
from localpilot.agent.recovery import RecoveryManager
from localpilot.agent.runtime import AgentRuntime, RuntimeLimits
from localpilot.agent.types import AgentError, InvalidTransitionError, Plan, PlanStep, Task, TaskState
from localpilot.agent.verifier import Verifier
from localpilot.tools.base import PermissionClass, Tool, ToolContext, ToolResult, validate_arguments
from localpilot.tools.mock import (DestructiveTool, NonRecoverableFailureTool, ReadFixtureTool,
    RecoverableFailureTool, SearchDocumentsTool, TimeoutTool, WriteReportTool)


class BadPlanner(Planner):
    def plan(self, request: str) -> Plan:
        raise PlanningError(AgentError("malformed_plan", "bad model output"))


class SlowTool(Tool):
    name, description, permission = "slow", "wait cooperatively", PermissionClass.READ_ONLY
    schema = {"type": "object", "properties": {}, "required": []}
    timeout_seconds = 2
    def execute(self, arguments, context: ToolContext) -> ToolResult:
        for _ in range(1000):
            context.raise_if_cancelled(); time.sleep(0.002)
        return ToolResult.success()


class LyingSuccessTool(Tool):
    name, description, permission = "lying", "returns success without postcondition", PermissionClass.READ_ONLY
    schema = {"type": "object", "properties": {}, "required": []}
    def execute(self, arguments, context): return ToolResult.success({"created": False})


class AgentRuntimeTests(TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.fixtures = self.root / "fixtures"; self.fixtures.mkdir()
        (self.fixtures / "alpha.txt").write_text("LocalPilot verified text", encoding="utf-8")
        self.registry = ToolRegistry()
        for tool in (ReadFixtureTool(self.fixtures), SearchDocumentsTool({"a": "agent recovery"}),
                     WriteReportTool(), RecoverableFailureTool(), TimeoutTool(), DestructiveTool(),
                     NonRecoverableFailureTool(), SlowTool(), LyingSuccessTool()):
            self.registry.register(tool)
        self.executor = Executor(self.registry, PermissionPolicy(self.root))

    def tearDown(self) -> None: self.temp.cleanup()

    def runtime(self, steps, **limit_args):
        limits = RuntimeLimits(**limit_args) if limit_args else RuntimeLimits()
        return AgentRuntime(StaticPlanner(Plan(tuple(steps))), self.executor,
                            recovery=RecoveryManager(2, 0), limits=limits)

    def test_successful_multi_step_task(self) -> None:
        report = self.root / "report.txt"
        task = self.runtime([
            PlanStep("read_fixture", {"name": "alpha.txt"}, {"name": "alpha.txt"}),
            PlanStep("write_report", {"path": str(report), "content": "done"}, {"exists": True}),
        ]).run("read and report")
        self.assertEqual(task.state, TaskState.COMPLETED)
        self.assertEqual(task.completed_steps, 2)
        self.assertEqual(report.read_text(), "done")

    def test_invalid_state_transition(self) -> None:
        with self.assertRaises(InvalidTransitionError): Task("x").transition(TaskState.COMPLETED, "no")

    def test_malformed_plan(self) -> None:
        with self.assertRaises(PlanningError): parse_plan('{"steps": [', 3)
        task = AgentRuntime(BadPlanner(), self.executor).run("x")
        self.assertEqual(task.state, TaskState.FAILED)

    def test_invalid_tool_arguments(self) -> None:
        task = self.runtime([PlanStep("read_fixture", {"wrong": "x"})]).run("x")
        self.assertIn("invalid_arguments", task.failure_reason or "")

    def test_unregistered_tool_rejected(self) -> None:
        task = self.runtime([PlanStep("not_registered", {})]).run("x")
        self.assertIn("permission_denied", task.failure_reason or "")
        self.assertEqual(task.completed_steps, 0)

    def test_write_outside_root_is_denied(self) -> None:
        task = self.runtime([PlanStep("write_report", {"path": "/outside/x", "content": "x"})]).run("x")
        self.assertEqual(task.state, TaskState.FAILED)
        self.assertIn("outside approved root", task.failure_reason or "")

    def test_sensitive_action_waits_for_approval(self) -> None:
        runtime = self.runtime([PlanStep("destructive_action", {"target": "fake"}, {"deleted": "fake"})])
        task = runtime.run("delete")
        self.assertEqual(task.state, TaskState.WAITING_FOR_APPROVAL)
        runtime.run_task(task, approvals={0})
        self.assertEqual(task.state, TaskState.COMPLETED)

    def test_retry_after_recoverable_failure(self) -> None:
        tool = self.registry.get("recoverable_failure")
        task = self.runtime([PlanStep("recoverable_failure", {}, {"recovered": True})]).run("recover")
        self.assertEqual(task.state, TaskState.COMPLETED)
        self.assertEqual(tool.calls, 2)  # type: ignore[union-attr]
        self.assertTrue(any(e.state == TaskState.RECOVERING for e in task.history))

    def test_no_retry_after_nonrecoverable_failure(self) -> None:
        tool = self.registry.get("fatal_failure")
        task = self.runtime([PlanStep("fatal_failure", {})]).run("fail")
        self.assertEqual(task.state, TaskState.FAILED)
        self.assertEqual(tool.calls, 1)  # type: ignore[union-attr]

    def test_timeout_handling_is_bounded(self) -> None:
        runtime = AgentRuntime(StaticPlanner(Plan((PlanStep("simulate_timeout", {"seconds": 0.2}),))),
            self.executor, recovery=RecoveryManager(1, 0))
        task = runtime.run("timeout")
        self.assertEqual(task.state, TaskState.FAILED)
        self.assertIn("tool_timeout", task.failure_reason or "")

    def test_cancellation_propagates_to_active_tool(self) -> None:
        runtime = self.runtime([PlanStep("slow", {})])
        task = runtime.create_task("slow task")
        thread = threading.Thread(target=runtime.run_task, args=(task,)); thread.start()
        deadline = time.time() + 1
        while task.state != TaskState.RUNNING and time.time() < deadline: time.sleep(0.001)
        runtime.cancel(task); thread.join(1)
        self.assertFalse(thread.is_alive())
        self.assertEqual(task.state, TaskState.CANCELLED)

    def test_repeated_call_loop_detection(self) -> None:
        step = PlanStep("read_fixture", {"name": "alpha.txt"}, {"name": "alpha.txt"})
        task = self.runtime([step, step, step], repeated_call_limit=2).run("loop")
        self.assertEqual(task.state, TaskState.FAILED)
        self.assertIn("loop_detected", task.failure_reason or "")
        self.assertEqual(task.completed_steps, 2)

    def test_maximum_step_enforcement(self) -> None:
        steps = [PlanStep("read_fixture", {"name": "alpha.txt"})] * 3
        task = self.runtime(steps, max_steps=2).run("too long")
        self.assertEqual(task.state, TaskState.FAILED)
        self.assertEqual(task.completed_steps, 0)

    def test_verification_rejects_success_response(self) -> None:
        task = self.runtime([PlanStep("lying", {}, {"created": True})]).run("verify")
        self.assertEqual(task.state, TaskState.FAILED)
        self.assertIn("verification_failed", task.failure_reason or "")

    def test_partial_completion_is_honest(self) -> None:
        task = self.runtime([PlanStep("read_fixture", {"name": "alpha.txt"}),
                             PlanStep("fatal_failure", {})]).run("partial")
        report = task.report()
        self.assertEqual(task.state, TaskState.FAILED)
        self.assertTrue(report["partial"])
        self.assertEqual(report["completed_steps"], 1)

    def test_public_argument_validator_rejects_unknown_and_wrong_type(self) -> None:
        schema = {"properties": {"x": {"type": "string"}}, "required": ["x"]}
        self.assertEqual(len(validate_arguments(schema, {"x": 1, "extra": True})), 2)
