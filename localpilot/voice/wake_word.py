"""Local wake-word providers. No audio is persisted or sent to a network service."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
import queue
import threading

from .providers import ProviderHealth, VoiceCancelled, VoiceError


class WakeWordProvider(ABC):
    @abstractmethod
    def health(self) -> ProviderHealth: pass
    @abstractmethod
    def wait_for_wake(self, cancel: threading.Event, muted: threading.Event) -> bool: pass
    def close(self) -> None: pass


class UnavailableWakeWordProvider(WakeWordProvider):
    """Honest fallback marker; callers must offer push-to-talk."""
    def __init__(self, reason: str = "wake-word engine is not configured") -> None: self.reason = reason
    def health(self) -> ProviderHealth:
        return ProviderHealth(False, f"{self.reason}; push-to-talk fallback required",
                              model_available=False, dependency_available=False)
    def wait_for_wake(self, cancel: threading.Event, muted: threading.Event) -> bool:
        raise VoiceError(self.health().detail)


@dataclass(frozen=True, slots=True)
class WakeWordSettings:
    model_path: Path
    threshold: float = 0.65
    cooldown_seconds: float = 2.0
    sample_rate: int = 16_000
    frame_samples: int = 1280


class OpenWakeWordProvider(WakeWordProvider):
    """openWakeWord with an explicit custom local model for “Hello Jean Grey”."""
    def __init__(self, settings: WakeWordSettings) -> None:
        self.settings = settings
        self._model = None
        self._last_activation = 0.0

    def health(self) -> ProviderHealth:
        try:
            import openwakeword  # noqa: F401
            import sounddevice  # noqa: F401
        except ImportError:
            return ProviderHealth(False, "openwakeword/sounddevice is not installed; push-to-talk fallback required",
                                  model_available=self.settings.model_path.is_file(), dependency_available=False)
        exists = self.settings.model_path.is_file()
        return ProviderHealth(exists, "custom wake-word model found" if exists else
            f"custom wake-word model not found: {self.settings.model_path}; push-to-talk fallback required",
            model_available=exists, dependency_available=True)

    def _load(self):
        health = self.health()
        if not health.available: raise VoiceError(health.detail)
        if self._model is None:
            try:
                from openwakeword.model import Model
                self._model = Model(wakeword_models=[str(self.settings.model_path)], inference_framework="onnx")
            except Exception as exc: raise VoiceError(f"wake-word model failed to load: {exc}") from exc
        return self._model

    def wait_for_wake(self, cancel: threading.Event, muted: threading.Event) -> bool:
        import time
        try:
            import numpy as np
            import sounddevice as sd
        except ImportError as exc: raise VoiceError("wake-word audio dependencies are unavailable") from exc
        model = self._load(); frames: queue.Queue[object] = queue.Queue(maxsize=4)
        def callback(indata, _count, _timing, _status):
            if muted.is_set(): return
            try: frames.put_nowait(indata.copy())
            except queue.Full:
                try: frames.get_nowait(); frames.put_nowait(indata.copy())
                except queue.Empty: pass
        try:
            with sd.InputStream(samplerate=self.settings.sample_rate, channels=1, dtype="int16",
                                blocksize=self.settings.frame_samples, callback=callback):
                while not cancel.wait(0.02):
                    if muted.is_set(): continue
                    try: frame = frames.get_nowait()
                    except queue.Empty: continue
                    scores = model.predict(np.asarray(frame).reshape(-1))
                    score = max((float(value) for value in scores.values()), default=0.0)
                    now = time.monotonic()
                    if score >= self.settings.threshold and now - self._last_activation >= self.settings.cooldown_seconds:
                        self._last_activation = now; return True
        except Exception as exc:
            if cancel.is_set(): raise VoiceCancelled("wake listening cancelled") from exc
            raise VoiceError(f"wake-word microphone failure: {exc}") from exc
        raise VoiceCancelled("wake listening cancelled")

    def close(self) -> None: self._model = None
