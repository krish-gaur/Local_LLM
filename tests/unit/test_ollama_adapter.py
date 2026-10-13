import io
import json
from unittest import TestCase, mock

from localpilot.models.base import ChatMessage, ModelUnavailableError
from localpilot.models.ollama_adapter import OllamaAdapter


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


class OllamaAdapterTests(TestCase):
    def test_remote_url_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "loopback"):
            OllamaAdapter("https://example.com", "model")

    @mock.patch("localpilot.models.ollama_adapter.urlopen")
    def test_discovers_installed_models(self, request) -> None:
        request.return_value = FakeResponse(json.dumps({"models": [{"name": "tiny", "size": 42}]}).encode())
        models = OllamaAdapter("http://localhost:11434", "tiny").discover()
        self.assertEqual(models[0].name, "tiny")
        self.assertEqual(models[0].size_bytes, 42)

    @mock.patch("localpilot.models.ollama_adapter.urlopen")
    def test_streams_chat_fragments(self, request) -> None:
        request.return_value = FakeResponse(
            b'{"message":{"content":"hello "}}\n{"message":{"content":"world"},"done":true}\n'
        )
        adapter = OllamaAdapter("http://127.0.0.1:11434", "tiny")
        self.assertEqual(adapter.chat([ChatMessage("user", "hi")]), "hello world")
        sent = json.loads(request.call_args.args[0].data)
        self.assertEqual(sent["options"]["num_ctx"], 2048)

    @mock.patch("localpilot.models.ollama_adapter.urlopen")
    def test_malformed_stream_is_controlled_error(self, request) -> None:
        request.return_value = FakeResponse(b"not-json\n")
        with self.assertRaises(ModelUnavailableError):
            list(OllamaAdapter("http://localhost:11434", "tiny").stream_chat([ChatMessage("user", "x")]))
