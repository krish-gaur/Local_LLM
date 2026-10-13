"""Backend-independent local language-model contracts."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Iterable, Literal, Mapping, Sequence

Role = Literal["system", "user", "assistant"]


@dataclass(frozen=True, slots=True)
class ChatMessage:
    role: Role
    content: str


@dataclass(frozen=True, slots=True)
class ModelInfo:
    name: str
    backend: str
    size_bytes: int | None = None


class ModelError(RuntimeError):
    """A model backend failed in a controlled, user-displayable way."""


class ModelUnavailableError(ModelError):
    """The configured model service or model is unavailable."""


class ModelAdapter(ABC):
    @abstractmethod
    def health(self) -> tuple[bool, str]:
        """Return backend readiness without downloading or loading a model."""

    @abstractmethod
    def discover(self) -> Sequence[ModelInfo]:
        """List models already installed locally."""

    @abstractmethod
    def stream_chat(self, messages: Sequence[ChatMessage]) -> Iterable[str]:
        """Yield response fragments."""

    def chat(self, messages: Sequence[ChatMessage]) -> str:
        if not messages:
            raise ValueError("at least one message is required")
        return "".join(self.stream_chat(messages))

    @property
    @abstractmethod
    def metadata(self) -> Mapping[str, str]:
        """Return non-secret backend metadata."""
