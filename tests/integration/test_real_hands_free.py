"""Opt-in hardware test. The operator must speak the wake phrase and one utterance."""
import os
import threading
from unittest import TestCase, skipUnless

from localpilot.app.main import _voice_providers
from localpilot.config import Settings
from localpilot.voice.wake_word import OpenWakeWordProvider, WakeWordSettings


@skipUnless(os.getenv("JEAN_GREY_REAL_VOICE_TEST") == "1", "real wake/microphone/speech test not requested")
class RealHandsFreeTests(TestCase):
    def test_wake_capture_and_multilingual_transcription(self):
        settings = Settings.from_env(); audio_input, stt, tts, output = _voice_providers(settings)
        wake = OpenWakeWordProvider(WakeWordSettings(settings.wake_word_model_path,
                                                      settings.wake_word_threshold))
        cancel, muted = threading.Event(), threading.Event()
        try:
            self.assertTrue(wake.health().available, wake.health().detail)
            self.assertTrue(wake.wait_for_wake(cancel, muted))
            audio = audio_input.capture_utterance(cancel)
            transcript = stt.transcribe_detailed(audio, cancel)
            self.assertTrue(transcript.text.strip())
            # TTS/playback is intentionally checked only when the configured default voice is ready.
            if tts.health().available and output.health().available:
                spoken = tts.synthesize("I heard the test utterance.", cancel); output.play(spoken, cancel)
        finally:
            wake.close(); audio_input.close(); stt.close(); tts.close(); output.close()
