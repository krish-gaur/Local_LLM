import tempfile
import threading
from pathlib import Path
from unittest import TestCase

from localpilot.voice.hands_free import ConversationState, HandsFreeConversation
from localpilot.voice.intent import parse_browser_search
from localpilot.voice.language import VoiceLanguage, detect_language
from localpilot.voice.providers import ProviderHealth, RecordedAudio, VoiceError
from localpilot.voice.session import AgentReply
from localpilot.voice.text_to_speech import PiperProvider
from localpilot.voice.transcript import Transcript
from localpilot.voice.wake_word import UnavailableWakeWordProvider, WakeWordProvider


class FakeWake(WakeWordProvider):
    def __init__(self, detected=True): self.detected, self.calls, self.closed = detected, 0, False
    def health(self): return ProviderHealth(True, "mock wake", model_available=True)
    def wait_for_wake(self, cancel, muted):
        self.calls += 1
        if muted.is_set(): return False
        return self.detected
    def close(self): self.closed = True


class FakeSTT:
    def __init__(self, transcript=Transcript("Chrome par BYD car search karo", "hi", .9)): self.value = transcript
    def transcribe_detailed(self, audio, cancel): return self.value


class FakeVoiceSession:
    def __init__(self, transcript=None):
        self.stt = FakeSTT(transcript or Transcript("Chrome par BYD car search karo", "hi", .9))
        self.speak_responses = True; self.spoken = []; self.stopped = False; self.calls = []
        self.agent_handler = self.handle
    def handle(self, text):
        self.calls.append(text); return AgentReply("Verified browser result", "COMPLETED")
    def speak_async(self, text): self.spoken.append(text)
    def wait_for_playback(self): pass
    def stop_playback(self): self.stopped = True
    def cancel(self): self.stopped = True


class HandsFreeTests(TestCase):
    def conversation(self, **kwargs):
        voice = kwargs.pop("voice", FakeVoiceSession())
        return HandsFreeConversation(kwargs.pop("wake", FakeWake()), voice, **kwargs), voice

    def test_mocked_wake_activation_acknowledges_and_listens(self):
        conversation, voice = self.conversation()
        self.assertTrue(conversation.wait_for_wake())
        self.assertEqual(conversation.state, ConversationState.LISTENING)
        self.assertIn("Haan, bolo", voice.spoken[0])
        self.assertFalse(conversation.wait_for_wake())  # repeated wake cannot duplicate a command

    def test_hindi_hinglish_transcript_routes_once_and_returns_to_listening(self):
        conversation, voice = self.conversation(); conversation.wait_for_wake()
        reply = conversation.handle_audio(RecordedAudio([1], 16000), lambda transcript: transcript.text)
        self.assertEqual(reply.status, "COMPLETED")
        self.assertEqual(voice.calls, ["Chrome par BYD car search karo"])
        self.assertEqual(conversation.state, ConversationState.LISTENING)
        self.assertEqual(detect_language("Chrome par sabse sasti car search karo"), VoiceLanguage.HINGLISH)
        self.assertEqual(detect_language("इसे हिंदी में समझाओ"), VoiceLanguage.HINDI)

    def test_uncertain_transcript_is_exposed_for_correction(self):
        transcript = Transcript("galat search", "hi", .4, uncertain=True)
        conversation, voice = self.conversation(voice=FakeVoiceSession(transcript)); conversation.wait_for_wake()
        seen = []
        conversation.handle_audio(RecordedAudio([1], 16000),
                                  lambda value: (seen.append(value.uncertain) or "Google par Python search karo"))
        self.assertEqual(seen, [True]); self.assertEqual(voice.calls, ["Google par Python search karo"])

    def test_duplicate_command_is_suppressed(self):
        conversation, voice = self.conversation(); conversation.wait_for_wake()
        conversation.handle_text("Google par Python course search karo")
        second = conversation.handle_text("Google par Python course search karo")
        self.assertIsNone(second); self.assertEqual(len(voice.calls), 1)

    def test_language_selection_and_stop_listening(self):
        conversation, _voice = self.conversation(); conversation.wait_for_wake()
        reply = conversation.handle_text("Ab English mein baat karo")
        self.assertEqual(conversation.preferred_language, VoiceLanguage.ENGLISH)
        self.assertIn("English", reply.text)
        conversation.handle_text("Jean Grey, stop listening")
        self.assertEqual(conversation.state, ConversationState.STOPPED)

    def test_cancel_and_barge_in_call_existing_cancellation(self):
        cancelled = []
        conversation, voice = self.conversation(task_cancel=lambda: cancelled.append(True)); conversation.wait_for_wake()
        reply = conversation.handle_text("Ruko, cancel karo")
        self.assertEqual(reply.status, "CANCELLED"); self.assertTrue(cancelled); self.assertTrue(voice.stopped)
        conversation.transition(ConversationState.TRANSCRIBING, "next")
        conversation.transition(ConversationState.PLANNING, "plan")
        conversation.transition(ConversationState.EXECUTING, "execute")
        conversation.interrupt()
        self.assertEqual(conversation.state, ConversationState.LISTENING); self.assertEqual(len(cancelled), 2)

    def test_wake_engine_unavailable_is_honest(self):
        provider = UnavailableWakeWordProvider("custom model missing")
        self.assertFalse(provider.health().available)
        with self.assertRaises(VoiceError): provider.wait_for_wake(threading.Event(), threading.Event())

    def test_microphone_failure_moves_to_error(self):
        class FailingWake(FakeWake):
            def wait_for_wake(self, cancel, muted): raise VoiceError("microphone unavailable")
        conversation, _voice = self.conversation(wake=FailingWake())
        self.assertFalse(conversation.wait_for_wake()); self.assertEqual(conversation.state, ConversationState.ERROR)

    def test_search_intent_supports_hinglish(self):
        intent = parse_browser_search("Chrome par BYD ki sabse sasti car search karo")
        self.assertIsNotNone(intent); self.assertIn("byd", intent.query)
        self.assertIsNone(parse_browser_search("Tell me a joke"))

    def test_hindi_voice_requires_verified_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); executable = root / "piper"; executable.write_text("")
            model = root / "hindi.onnx"; model.write_text("")
            provider = PiperProvider(executable, model, required_language="hi")
            self.assertFalse(provider.health().available)
            Path(f"{model}.json").write_text('{"language":{"code":"hi_IN"}}')
            self.assertTrue(provider.health().available)
