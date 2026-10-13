"""Bounded retry policy."""
from __future__ import annotations

from dataclasses import dataclass

from localpilot.agent.types import AgentError


@dataclass(frozen=True, slots=True)
class RecoveryManager:
    max_retries: int = 2
    base_backoff_seconds: float = 0.01

    def should_retry(self, error: AgentError | None, retries: int) -> bool:
        return error is not None and error.recoverable and retries < self.max_retries

    def delay(self, retries: int) -> float:
        return self.base_backoff_seconds * (2 ** max(0, retries - 1))
