from typing import Iterable, Mapping, Sequence
from unittest import TestCase

from localpilot.models.base import ChatMessage, ModelAdapter, ModelInfo


class FakeAdapter(ModelAdapter):
    @property
    def metadata(self) -> Mapping[str, str]:
        return {"backend": "fake"}

    def health(self) -> tuple[bool, str]:
        return True, "ready"

    def discover(self) -> Sequence[ModelInfo]:
        return [ModelInfo("fake", "fake")]

    def stream_chat(self, messages: Sequence[ChatMessage]) -> Iterable[str]:
        yield "ok"


class BaseAdapterTests(TestCase):
    def test_chat_requires_a_message(self) -> None:
        with self.assertRaises(ValueError):
            FakeAdapter().chat([])

    def test_chat_collects_stream(self) -> None:
        self.assertEqual(FakeAdapter().chat([ChatMessage("user", "hello")]), "ok")
