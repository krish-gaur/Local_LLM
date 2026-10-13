"""Testable hands-free conversation state machine layered over the existing VoiceSession."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import hashlib
import threading
import time
from typing import Callable

from .language import (VoiceLanguage, acknowledgement, detect_language, is_cancel_command,
                       is_stop_listening_command, language_command)
from .providers import RecordedAudio, VoiceError
from .session import AgentReply, VoiceSession
from .transcript import Transcript
from .wake_word import WakeWordProvider


class ConversationState(str, Enum):
    IDLE = "IDLE"
    WAKE_DETECTED = "WAKE_DETECTED"
    LISTENING = "LISTENING"
    TRANSCRIBING = "TRANSCRIBING"
    PLANNING = "PLANNING"
    EXECUTING = "EXECUTING"
    SPEAKING = "SPEAKING"
    INTERRUPTED = "INTERRUPTED"
    ERROR = "ERROR"
    STOPPED = "STOPPED"


_TRANSITIONS = {
    ConversationState.IDLE: {ConversationState.WAKE_DETECTED, ConversationState.STOPPED, ConversationState.ERROR},
    ConversationState.WAKE_DETECTED: {ConversationState.LISTENING, ConversationState.SPEAKING, ConversationState.ERROR},
    ConversationState.LISTENING: {ConversationState.TRANSCRIBING, ConversationState.INTERRUPTED, ConversationState.STOPPED, ConversationState.ERROR},
    ConversationState.TRANSCRIBING: {ConversationState.PLANNING, ConversationState.LISTENING, ConversationState.INTERRUPTED, ConversationState.ERROR},
    ConversationState.PLANNING: {ConversationState.EXECUTING, ConversationState.LISTENING, ConversationState.INTERRUPTED, ConversationState.STOPPED},
    ConversationState.EXECUTING: {ConversationState.SPEAKING, ConversationState.LISTENING, ConversationState.INTERRUPTED, ConversationState.ERROR},
    ConversationState.SPEAKING: {ConversationState.LISTENING, ConversationState.INTERRUPTED, ConversationState.ERROR},
    ConversationState.INTERRUPTED: {ConversationState.LISTENING, ConversationState.STOPPED},
    ConversationState.ERROR: {ConversationState.IDLE, ConversationState.LISTENING, ConversationState.STOPPED},
    ConversationState.STOPPED: set(),
}


@dataclass(frozen=True, slots=True)
class ConversationEvent:
    state: ConversationState
    detail: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class ConversationTransitionError(ValueError): pass
Review = Callable[[Transcript], str | None]


class HandsFreeConversation:
    def __init__(self, wake_word: WakeWordProvider, voice_session: VoiceSession,
                 *, preferred_language: VoiceLanguage = VoiceLanguage.AUTO,
                 task_cancel: Callable[[], None] | None = None,
                 language_changed: Callable[[VoiceLanguage], None] | None = None,
                 duplicate_window_seconds: float = 5.0) -> None:
        self.wake_word, self.voice_session = wake_word, voice_session
        self.preferred_language = preferred_language
        self.task_cancel = task_cancel or (lambda: None)
        self.language_changed = language_changed or (lambda _language: None)
        self.duplicate_window_seconds = duplicate_window_seconds
        self.state = ConversationState.IDLE
        self.events: list[ConversationEvent] = [ConversationEvent(self.state, "conversation initialized")]
        self.cancel_event, self.muted = threading.Event(), threading.Event()
        self._last_command: tuple[str, float] | None = None
        self._lock = threading.RLock()

    def transition(self, target: ConversationState, detail: str) -> None:
        with self._lock:
            if target not in _TRANSITIONS[self.state]:
                raise ConversationTransitionError(f"invalid conversation transition: {self.state} -> {target}")
            self.state = target; self.events.append(ConversationEvent(target, detail))

    def wait_for_wake(self) -> bool:
        if self.state != ConversationState.IDLE: return False
        try: detected = self.wake_word.wait_for_wake(self.cancel_event, self.muted)
        except VoiceError as exc:
            self.transition(ConversationState.ERROR, str(exc)); return False
        if not detected: return False
        self.transition(ConversationState.WAKE_DETECTED, "wake word detected")
        language = self.preferred_language if self.preferred_language != VoiceLanguage.AUTO else VoiceLanguage.HINGLISH
        self.voice_session.speak_async(acknowledgement(language))
        self.transition(ConversationState.SPEAKING, "wake acknowledgement")
        self.voice_session.wait_for_playback()
        self.transition(ConversationState.LISTENING, "ready for command")
        return True

    def handle_audio(self, audio: RecordedAudio, review: Review) -> AgentReply | None:
        self.transition(ConversationState.TRANSCRIBING, "transcription started")
        try:
            detailed = getattr(self.voice_session.stt, "transcribe_detailed", None)
            transcript = detailed(audio, self.cancel_event) if detailed else Transcript(
                self.voice_session.stt.transcribe(audio, self.cancel_event))
            corrected = review(transcript)
            if corrected is None or not corrected.strip():
                self.transition(ConversationState.LISTENING, "transcript rejected"); return None
            return self.handle_text(corrected, transcript.language)
        except VoiceError as exc:
            self.transition(ConversationState.ERROR, str(exc)); self.transition(ConversationState.LISTENING, "recovered")
            return None

    def handle_text(self, text: str, model_language: str | None = None) -> AgentReply | None:
        cleaned = text.strip()
        if self.state == ConversationState.LISTENING:
            self.transition(ConversationState.TRANSCRIBING, "text fallback accepted")
        if self.state != ConversationState.TRANSCRIBING:
            raise ConversationTransitionError("commands are accepted only while transcribing")
        if is_stop_listening_command(cleaned):
            self.transition(ConversationState.PLANNING, "stop-listening command")
            self.transition(ConversationState.STOPPED, "user stopped listening"); return None
        if is_cancel_command(cleaned):
            self.transition(ConversationState.INTERRUPTED, "cancel command")
            self.task_cancel(); self.voice_session.stop_playback()
            self.transition(ConversationState.LISTENING, "ready after cancellation"); return AgentReply(
                "Theek hai, task cancel kar diya.", "CANCELLED")
        selected = language_command(cleaned)
        if selected is not None:
            self.preferred_language = selected; self.language_changed(selected)
            self.transition(ConversationState.PLANNING, "language preference changed")
            self.transition(ConversationState.LISTENING, f"language set to {selected.value}")
            text_reply = "Theek hai, ab Hindi mein baat karungi." if selected == VoiceLanguage.HINDI else "Okay, I will speak in English."
            return AgentReply(text_reply, "COMPLETED")
        digest = hashlib.sha256(cleaned.casefold().encode()).hexdigest(); now = time.monotonic()
        if self._last_command and self._last_command[0] == digest and now - self._last_command[1] < self.duplicate_window_seconds:
            self.transition(ConversationState.PLANNING, "duplicate command suppressed")
            self.transition(ConversationState.LISTENING, "ready after duplicate"); return None
        self._last_command = digest, now
        detected = detect_language(cleaned, model_language)
        language = self.preferred_language if self.preferred_language != VoiceLanguage.AUTO else detected
        self.transition(ConversationState.PLANNING, f"intent accepted; reply language={language.value}")
        self.transition(ConversationState.EXECUTING, "delegated to existing agent handler")
        try: reply = self.voice_session.agent_handler(cleaned)
        except Exception as exc:
            self.transition(ConversationState.ERROR, f"agent handler failed: {type(exc).__name__}")
            self.transition(ConversationState.LISTENING, "recovered after execution error"); return None
        self.transition(ConversationState.SPEAKING, f"verified task status={reply.status}")
        if self.voice_session.speak_responses: self.voice_session.speak_async(reply.text)
        self.voice_session.wait_for_playback()
        self.transition(ConversationState.LISTENING, "ready for follow-up")
        return reply

    def interrupt(self) -> None:
        with self._lock:
            if self.state in {ConversationState.EXECUTING, ConversationState.SPEAKING, ConversationState.LISTENING}:
                self.transition(ConversationState.INTERRUPTED, "barge-in/cancel")
                self.task_cancel(); self.voice_session.stop_playback()
                self.transition(ConversationState.LISTENING, "ready after interruption")

    def set_muted(self, muted: bool) -> None:
        if muted: self.muted.set()
        else: self.muted.clear()

    def stop(self) -> None:
        self.cancel_event.set(); self.voice_session.cancel(); self.wake_word.close()
        if self.state != ConversationState.STOPPED:
            if ConversationState.STOPPED in _TRANSITIONS[self.state]: self.transition(ConversationState.STOPPED, "conversation stopped")
            else: self.state = ConversationState.STOPPED; self.events.append(ConversationEvent(self.state, "forced safe stop"))
