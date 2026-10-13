"""Voice orchestration that delegates all task execution to the existing agent runtime."""
from __future__ import annotations

from dataclasses import dataclass
import threading
from typing import Callable

from .providers import (AudioInputProvider, AudioOutputProvider, RecordedAudio, SpeechToTextProvider,
                        TextToSpeechProvider, VoiceCancelled, VoiceError)


@dataclass(frozen=True, slots=True)
class AgentReply:
    text: str
    status: str
    requires_approval: bool = False


@dataclass(frozen=True, slots=True)
class VoiceTurn:
    transcript: str
    reply: AgentReply | None
    error: str | None = None


ReviewTranscript = Callable[[str], str | None]
AgentHandler = Callable[[str], AgentReply]


class VoiceSession:
    """One shared security boundary: voice text enters the same agent handler as typed text."""
    def __init__(self, audio_input: AudioInputProvider, stt: SpeechToTextProvider,
                 tts: TextToSpeechProvider, audio_output: AudioOutputProvider,
                 agent_handler: AgentHandler, *, speak_responses: bool = True) -> None:
        self.audio_input, self.stt, self.tts, self.audio_output = audio_input, stt, tts, audio_output
        self.agent_handler, self.speak_responses = agent_handler, speak_responses
        self.cancel_event = threading.Event()
        self._playback_thread: threading.Thread | None = None
        self._playback_cancel: threading.Event | None = None

    def process(self, audio: RecordedAudio, review: ReviewTranscript) -> VoiceTurn:
        if self.cancel_event.is_set(): return VoiceTurn("", None, "voice session cancelled")
        try:
            transcript = self.stt.transcribe(audio, self.cancel_event).strip()
            if not transcript:
                return VoiceTurn("", None, "empty transcript; task was not executed")
            reviewed = review(transcript)
            if reviewed is None:
                return VoiceTurn(transcript, None, "transcript was not confirmed")
            reviewed = reviewed.strip()
            if not reviewed:
                return VoiceTurn(transcript, None, "empty transcript; task was not executed")
            if self.cancel_event.is_set(): raise VoiceCancelled("voice session cancelled")
            reply = self.agent_handler(reviewed)
            if self.speak_responses:
                self.speak_async(reply.text)
            return VoiceTurn(reviewed, reply)
        except VoiceError as exc:
            return VoiceTurn("", None, str(exc))

    def process_text_fallback(self, text: str) -> VoiceTurn:
        """Keyboard fallback still uses exactly the same agent handler and permission layer."""
        cleaned = text.strip()
        if not cleaned: return VoiceTurn("", None, "empty task was not executed")
        if self.cancel_event.is_set(): return VoiceTurn(cleaned, None, "voice session cancelled")
        reply = self.agent_handler(cleaned)
        if self.speak_responses: self.speak_async(reply.text)
        return VoiceTurn(cleaned, reply)

    def speak_async(self, text: str) -> None:
        self.stop_playback(); playback_cancel = threading.Event()
        def worker() -> None:
            try:
                audio = self.tts.synthesize(text, playback_cancel)
                self.audio_output.play(audio, playback_cancel)
            except VoiceError:
                # Text is always retained; callers can inspect provider health separately.
                return
        self._playback_cancel = playback_cancel
        self._playback_thread = threading.Thread(target=worker, name="jean-grey-voice-output", daemon=True)
        self._playback_thread.start()

    def wait_for_playback(self) -> None:
        """Wait outside a UI event loop; Ctrl+C can still call cancel/stop."""
        thread = self._playback_thread
        if thread is not None:
            while thread.is_alive():
                thread.join(timeout=0.05)
        self._playback_thread = None
        self._playback_cancel = None

    def stop_playback(self) -> None:
        thread = self._playback_thread
        if thread is not None and thread.is_alive():
            if self._playback_cancel is not None: self._playback_cancel.set()
            self.audio_output.stop()
            thread.join(timeout=1)
        self._playback_thread = None
        self._playback_cancel = None

    def cancel(self) -> None:
        self.cancel_event.set(); self.stop_playback(); self.audio_output.stop()

    def close(self) -> None:
        self.cancel()
        for provider in (self.audio_input, self.stt, self.tts, self.audio_output):
            provider.close()
