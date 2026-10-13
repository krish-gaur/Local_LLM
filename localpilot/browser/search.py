"""Bounded search-page plan using the existing browser tool registry and runtime."""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote_plus, urlparse

from localpilot.agent.planner import Planner, PlanningError
from localpilot.agent.types import AgentError, Plan, PlanStep


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
