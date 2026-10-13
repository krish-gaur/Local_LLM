"""Provider-neutral voice contracts. Optional engines are imported only when used."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
import threading
from typing import Any


class VoiceError(RuntimeError):
    """A safe, user-displayable voice subsystem failure."""


class VoiceCancelled(VoiceError):
    pass


@dataclass(frozen=True, slots=True)
class ProviderHealth:
    available: bool
    detail: str
    device_detected: bool | None = None
    model_available: bool | None = None
    dependency_available: bool | None = None


@dataclass(frozen=True, slots=True)
class RecordedAudio:
    samples: Any
    sample_rate: int


@dataclass(frozen=True, slots=True)
class SynthesizedAudio:
    path: Path
    temporary: bool = True


class AudioInputProvider(ABC):
    @abstractmethod
    def health(self) -> ProviderHealth: pass
    @abstractmethod
    def capture(self, stop: threading.Event, cancel: threading.Event) -> RecordedAudio: pass
    def close(self) -> None: pass


class SpeechToTextProvider(ABC):
    @abstractmethod
    def health(self) -> ProviderHealth: pass
    @abstractmethod
    def transcribe(self, audio: RecordedAudio, cancel: threading.Event) -> str: pass
    def close(self) -> None: pass


class TextToSpeechProvider(ABC):
    @abstractmethod
    def health(self) -> ProviderHealth: pass
    @abstractmethod
    def synthesize(self, text: str, cancel: threading.Event) -> SynthesizedAudio: pass
    def close(self) -> None: pass


class AudioOutputProvider(ABC):
    @abstractmethod
    def health(self) -> ProviderHealth: pass
    @abstractmethod
    def play(self, audio: SynthesizedAudio, cancel: threading.Event) -> None: pass
    @abstractmethod
    def stop(self) -> None: pass
    def close(self) -> None: self.stop()
