"""Dependency-free Ollama adapter using its local HTTP API."""
from __future__ import annotations

import json
from typing import Iterable, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .base import ChatMessage, ModelAdapter, ModelInfo, ModelUnavailableError


class OllamaAdapter(ModelAdapter):
    def __init__(self, base_url: str, model: str, context_window: int = 2048, timeout: float = 120) -> None:
        if not base_url.startswith(("http://127.0.0.1", "http://localhost")):
            raise ValueError("Ollama URL must be loopback; remote endpoints use a separate opt-in adapter")
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.context_window = context_window
        self.timeout = timeout

    @property
    def metadata(self) -> Mapping[str, str]:
        return {"backend": "ollama", "model": self.model, "url": self.base_url}

    def _request(self, path: str, payload: dict[str, object] | None = None):
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = Request(
            f"{self.base_url}{path}", data=data,
            headers={"Content-Type": "application/json"},
            method="GET" if data is None else "POST",
        )
        try:
            return urlopen(request, timeout=self.timeout)  # noqa: S310 - loopback enforced above
        except (URLError, HTTPError, TimeoutError) as exc:
            raise ModelUnavailableError(f"Ollama request failed: {exc}") from exc

    def health(self) -> tuple[bool, str]:
        try:
            models = self.discover()
        except ModelUnavailableError as exc:
            return False, str(exc)
        if not any(item.name == self.model for item in models):
            return False, f"Ollama is running, but model '{self.model}' is not installed"
        return True, "ready"

    def discover(self) -> Sequence[ModelInfo]:
        with self._request("/api/tags") as response:
            body = json.loads(response.read().decode("utf-8"))
        return [
            ModelInfo(str(item["name"]), "ollama", int(item.get("size", 0)) or None)
            for item in body.get("models", [])
            if isinstance(item, dict) and item.get("name")
        ]

    def stream_chat(self, messages: Sequence[ChatMessage]) -> Iterable[str]:
        if not messages:
            raise ValueError("at least one message is required")
        payload: dict[str, object] = {
            "model": self.model,
            "messages": [{"role": message.role, "content": message.content} for message in messages],
            "stream": True,
            "options": {"num_ctx": self.context_window},
        }
        with self._request("/api/chat", payload) as response:
            for raw_line in response:
                if not raw_line.strip():
                    continue
                try:
                    event = json.loads(raw_line)
                    content = event.get("message", {}).get("content", "")
                except (json.JSONDecodeError, AttributeError) as exc:
                    raise ModelUnavailableError("Ollama returned malformed streaming data") from exc
                if content:
                    yield str(content)
                if event.get("error"):
                    raise ModelUnavailableError(str(event["error"]))
