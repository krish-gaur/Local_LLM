"""Bounded search-page plan using the existing browser tool registry and runtime."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote_plus, urlparse

from localpilot.agent.planner import Planner, PlanningError
from localpilot.agent.types import AgentError, Json, Plan, PlanStep


@dataclass(frozen=True, slots=True)
class SearchRequest:
    query: str
    search_base_url: str = "https://www.google.com/search?q="


class SearchPlanner(Planner):
    def __init__(self, request: SearchRequest) -> None: self.request = request

    def plan(self, user_request: str) -> Plan:
        if not self.request.query.strip() or len(self.request.query) > 500:
            raise PlanningError(AgentError("invalid_search", "search query must contain 1..500 characters"))
        parsed = urlparse(self.request.search_base_url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise PlanningError(AgentError("invalid_search_provider", "search provider must be HTTPS"))
        url = f"{self.request.search_base_url}{quote_plus(self.request.query)}"
        return Plan((PlanStep("browser.navigate", {"url": url}),
                     PlanStep("browser.get_page_content", {}, {"untrusted_web_content": True})))


@dataclass(frozen=True, slots=True)
class VerifiedResearchRequest:
    query: str
    market: str
    as_of_date: str
    report_path: Path | None = None
    source_count: int = 3
    search_base_url: str = "https://www.google.com/search?q="


class VerifiedResearchPlanner(Planner):
    """Search, inspect bounded source pages, compare evidence, then optionally verify a report."""
    def __init__(self, request: VerifiedResearchRequest) -> None: self.request = request

    def plan(self, user_request: str) -> Plan:
        if not 2 <= self.request.source_count <= 3:
            raise PlanningError(AgentError("invalid_source_count", "verified research supports 2..3 sources"))
        if not self.request.query.strip() or len(self.request.query) > 500:
            raise PlanningError(AgentError("invalid_search", "search query must contain 1..500 characters"))
        parsed = urlparse(self.request.search_base_url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise PlanningError(AgentError("invalid_search_provider", "search provider must be HTTPS"))
        search_url = f"{self.request.search_base_url}{quote_plus(self.request.query)}"
        steps: list[PlanStep] = [
            PlanStep("browser.navigate", {"url": search_url}),
            PlanStep("browser.get_page_content", {}, {"untrusted_web_content": True}),
            PlanStep("browser.extract_links", {}, {"untrusted_web_content": True}),
            PlanStep("research.extract_links", {"snapshot": {"$ref": "steps.2.raw"},
                "query": self.request.query, "max_results": self.request.source_count,
                "search_host": parsed.netloc.lower().removeprefix("www.")},
                {"count": self.request.source_count}),
        ]
        sources: list[Json] = []
        for index in range(self.request.source_count):
            steps.append(PlanStep("browser.navigate", {"url": {"$ref": f"steps.3.links.{index}"}}))
            steps.append(PlanStep("browser.get_page_content", {}, {"untrusted_web_content": True}))
            sources.append({"url": {"$ref": f"steps.3.links.{index}"},
                            "content": {"$ref": f"steps.{len(steps) - 1}.raw"}})
        compare_index = len(steps)
        steps.append(PlanStep("research.compare_sources", {"query": self.request.query,
            "market": self.request.market, "as_of_date": self.request.as_of_date, "sources": sources}))
        if self.request.report_path is not None:
            steps.append(PlanStep("report.create", {"path": str(self.request.report_path),
                "topic": self.request.query, "format": "markdown",
                "summary": {"$ref": f"steps.{compare_index}.conclusion"},
                "sources": {"$ref": f"steps.{compare_index}.report_sources"}}, {"verified": True}))
        return Plan(tuple(steps))
