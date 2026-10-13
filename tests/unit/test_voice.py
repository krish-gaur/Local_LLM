import sys
import tempfile
import threading
import time
import types
from pathlib import Path
from unittest import TestCase, mock

from localpilot.agent.executor import Executor, ToolRegistry
from localpilot.agent.permissions import PermissionPolicy
from localpilot.agent.planner import StaticPlanner
from localpilot.agent.runtime import AgentRuntime
from localpilot.agent.types import Plan, PlanStep, TaskState
from localpilot.tools.mock import DestructiveTool
from localpilot.voice.audio_input import SoundDeviceAudioInput
from localpilot.voice.audio_output import SoundDeviceAudioOutput
from localpilot.voice.providers import (AudioInputProvider, AudioOutputProvider, ProviderHealth,
    RecordedAudio, SpeechToTextProvider, SynthesizedAudio, TextToSpeechProvider, VoiceCancelled,
    VoiceError)
from localpilot.voice.session import AgentReply, VoiceSession
from localpilot.voice.speech_to_text import FasterWhisperProvider
from localpilot.voice.text_to_speech import PiperProvider


class FakeInput(AudioInputProvider):
    def __init__(self, available=True): self.available, self.closed = available, False
    def health(self): return ProviderHealth(self.available, "input", self.available)
    def capture(self, stop, cancel): return RecordedAudio([0.2], 16000)
    def close(self): self.closed = True


class FakeSTT(SpeechToTextProvider):
    def __init__(self, text="prepare report", error=None): self.text, self.error, self.closed = text, error, False
    def health(self): return ProviderHealth(True, "stt", model_available=True)
    def transcribe(self, audio, cancel):
        if self.error: raise self.error
        if cancel.is_set(): raise VoiceCancelled("cancelled")
        return self.text
    def close(self): self.closed = True


class FakeTTS(TextToSpeechProvider):
    def __init__(self, error=None): self.error, self.calls, self.closed = error, [], False
    def health(self): return ProviderHealth(True, "tts", model_available=True)
    def synthesize(self, text, cancel):
        self.calls.append(text)
        if self.error: raise self.error
        path = Path(tempfile.mkstemp(suffix=".wav")[1]); return SynthesizedAudio(path)
    def close(self): self.closed = True


class FakeOutput(AudioOutputProvider):
    def __init__(self, block=False): self.block, self.stopped, self.closed = block, False, False
    def health(self): return ProviderHealth(True, "output", True)
    def play(self, audio, cancel):
        while self.block and not cancel.wait(0.005): pass
        audio.path.unlink(missing_ok=True)
        if cancel.is_set(): raise VoiceCancelled("interrupted")
    def stop(self): self.stopped = True
    def close(self): self.closed = True; self.stop()


def session(stt=None, tts=None, output=None, handler=None, speak=False):
    return VoiceSession(FakeInput(), stt or FakeSTT(), tts or FakeTTS(), output or FakeOutput(),
        handler or (lambda text: AgentReply(f"verified: {text}", "COMPLETED")), speak_responses=speak)


class VoiceTests(TestCase):
    def test_missing_audio_dependencies_are_reported(self):
        provider = SoundDeviceAudioInput()
        with mock.patch.object(provider, "_modules", side_effect=VoiceError("dependencies missing")):
            health = provider.health()
        self.assertFalse(health.available); self.assertIn("missing", health.detail)

    def test_missing_microphone_and_output_are_reported(self):
        no_devices = (mock.Mock(), mock.Mock())
        no_devices[1].query_devices.return_value = [{"max_input_channels": 0}]
        input_provider = SoundDeviceAudioInput()
        with mock.patch.object(input_provider, "_modules", return_value=no_devices):
            self.assertFalse(input_provider.health().device_detected)
        output_provider = SoundDeviceAudioOutput(); fake_sd = mock.Mock(); fake_sd.query_devices.return_value = [{"max_output_channels": 0}]
        with mock.patch.object(output_provider, "_modules", return_value=(fake_sd, mock.Mock())):
            self.assertFalse(output_provider.health().device_detected)

    def test_missing_local_models_do_not_download(self):
        with tempfile.TemporaryDirectory() as directory:
            stt = FasterWhisperProvider(Path(directory) / "missing")
            piper = PiperProvider(Path(directory) / "piper.exe", Path(directory) / "voice.onnx")
            self.assertFalse(stt.health().available); self.assertFalse(piper.health().available)

    def test_multilingual_stt_preserves_detected_language_and_uncertainty(self):
        class Model:
            def transcribe(self, samples, **kwargs):
                return [types.SimpleNamespace(text="नमस्ते Jean Grey")], types.SimpleNamespace(
                    language="hi", language_probability=0.5)
        provider = FasterWhisperProvider(Path("unused")); provider._model = Model()
        with mock.patch.object(provider, "_load", return_value=provider._model):
            transcript = provider.transcribe_detailed(RecordedAudio([1], 16000), threading.Event())
        self.assertEqual(transcript.language, "hi"); self.assertTrue(transcript.uncertain)
        self.assertIn("Jean Grey", transcript.text)

    def test_stt_enforces_local_files_only(self):
        captured = {}
        class WhisperModel:
            def __init__(self, path, **kwargs): captured.update(kwargs)
        module = types.SimpleNamespace(WhisperModel=WhisperModel)
        with tempfile.TemporaryDirectory() as directory, \
             mock.patch.dict(sys.modules, {"faster_whisper": module}):
            FasterWhisperProvider(Path(directory))._load()
        self.assertTrue(captured["local_files_only"])
        self.assertEqual(captured["device"], "cpu")

    def test_recognition_error_and_empty_transcript_do_not_execute(self):
        calls = []
        failed = session(stt=FakeSTT(error=VoiceError("recognition failed")), handler=lambda x: calls.append(x))
        self.assertIn("recognition failed", failed.process(RecordedAudio([], 1), lambda x: x).error or "")
        empty = session(stt=FakeSTT("   "), handler=lambda x: calls.append(x))
        self.assertIn("empty", empty.process(RecordedAudio([], 1), lambda x: x).error or "")
        self.assertEqual(calls, [])

    def test_transcript_review_can_edit_or_reject(self):
        seen = []
        active = session(handler=lambda text: (seen.append(text) or AgentReply("ok", "COMPLETED")))
        turn = active.process(RecordedAudio([], 1), lambda _text: "edited task")
        self.assertEqual(turn.transcript, "edited task"); self.assertEqual(seen, ["edited task"])
        rejected = active.process(RecordedAudio([], 1), lambda _text: None)
        self.assertIsNone(rejected.reply); self.assertEqual(len(seen), 1)

    def test_tts_failure_keeps_text_result(self):
        active = session(tts=FakeTTS(VoiceError("tts failed")), speak=True)
        turn = active.process_text_fallback("typed")
        active._playback_thread.join(1)  # type: ignore[union-attr]
        self.assertEqual(turn.reply.text, "verified: typed")

    def test_playback_interruption(self):
        output = FakeOutput(block=True); active = session(output=output, speak=True)
        active.process_text_fallback("speak"); time.sleep(0.02); active.stop_playback()
        self.assertTrue(output.stopped)
        self.assertIsNone(active._playback_thread)

    def test_cancellation_prevents_agent_execution(self):
        calls = []; active = session(handler=lambda text: calls.append(text))
        active.cancel(); turn = active.process(RecordedAudio([], 1), lambda x: x)
        self.assertIn("cancelled", turn.error or ""); self.assertEqual(calls, [])

    def test_voice_routes_to_existing_agent_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            registry = ToolRegistry(); registry.register(DestructiveTool())
            runtime = AgentRuntime(StaticPlanner(Plan((PlanStep("destructive_action", {"target": "x"}),))),
                                   Executor(registry, PermissionPolicy(Path(directory))))
            def handler(text):
                task = runtime.run(text)
                return AgentReply(task.state.value, task.state.value,
                                  task.state == TaskState.WAITING_FOR_APPROVAL)
            turn = session(handler=handler).process(RecordedAudio([], 1), lambda text: text)
            self.assertEqual(turn.reply.status, "WAITING_FOR_APPROVAL")
            self.assertTrue(turn.reply.requires_approval)

    def test_resource_cleanup(self):
        input_provider, stt, tts, output = FakeInput(), FakeSTT(), FakeTTS(), FakeOutput()
        active = VoiceSession(input_provider, stt, tts, output, lambda x: AgentReply("x", "COMPLETED"))
        active.close()
        self.assertTrue(all((input_provider.closed, stt.closed, tts.closed, output.closed)))

    def test_text_fallback_uses_same_handler(self):
        seen = []; active = session(handler=lambda text: (seen.append(text) or AgentReply("ok", "COMPLETED")))
        self.assertEqual(active.process_text_fallback(" keyboard ").reply.status, "COMPLETED")
        self.assertEqual(seen, ["keyboard"])
        self.assertIsNone(active.process_text_fallback(" ").reply)
