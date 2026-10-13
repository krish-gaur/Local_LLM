"""Bounded source-grounded research plans executed by the existing AgentRuntime."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from localpilot.agent.planner import Planner, PlanningError
from localpilot.agent.types import AgentError, Json, Plan, PlanStep


@dataclass(frozen=True, slots=True)
class ResearchRequest:
    topic: str
    source_urls: tuple[str, ...]
    report_path: Path
    format: str = "markdown"


class ResearchPlanner(Planner):
    def __init__(self, request: ResearchRequest, *, max_pages: int = 10, max_actions: int = 30) -> None:
        self.request, self.max_pages, self.max_actions = request, max_pages, max_actions

    def plan(self, user_request: str) -> Plan:
        if not self.request.source_urls or len(self.request.source_urls) > self.max_pages:
            raise PlanningError(AgentError("invalid_sources", f"research requires 1..{self.max_pages} sources"))
        steps: list[PlanStep] = []
        source_args: list[Json] = []
        for url in self.request.source_urls:
            parsed = urlparse(url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise PlanningError(AgentError("invalid_url", f"unsupported source URL: {url}"))
            steps.append(PlanStep("browser.navigate", {"url": url}))
            steps.append(PlanStep("browser.get_page_content", {}))
            source_args.append({"url": url, "evidence": {"$ref": f"steps.{len(steps) - 1}.raw"}})
        steps.append(PlanStep("report.create", {"path": str(self.request.report_path),
            "topic": self.request.topic, "format": self.request.format, "sources": source_args},
            {"verified": True}))
        if len(steps) > self.max_actions:
            raise PlanningError(AgentError("browser_action_limit", "research plan exceeds browser action limit"))
        return Plan(tuple(steps))
