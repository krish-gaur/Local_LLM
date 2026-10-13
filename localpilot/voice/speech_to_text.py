"""Lazy faster-whisper provider; models are never downloaded by Jean Grey."""
from __future__ import annotations

from pathlib import Path
import threading

from .providers import ProviderHealth, RecordedAudio, SpeechToTextProvider, VoiceCancelled, VoiceError
from .transcript import Transcript


class FasterWhisperProvider(SpeechToTextProvider):
    def __init__(self, model_path: Path, *, compute_type: str = "int8", language: str | None = None) -> None:
        self.model_path = model_path
        self.compute_type, self.language = compute_type, language
        self._model = None

    def health(self) -> ProviderHealth:
        try:
            import faster_whisper  # noqa: F401
        except ImportError:
            return ProviderHealth(False, "faster-whisper is not installed", model_available=False,
                                  dependency_available=False)
        exists = self.model_path.is_dir()
        detail = "local transcription model found" if exists else f"model not found: {self.model_path}"
        return ProviderHealth(exists, detail, model_available=exists, dependency_available=True)

    def _load(self):
        if not self.model_path.is_dir():
            raise VoiceError(f"speech model not found: {self.model_path}; download it only with user approval")
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise VoiceError("faster-whisper is not installed; keyboard input remains available") from exc
        if self._model is None:
            try:
                self._model = WhisperModel(str(self.model_path), device="cpu", compute_type=self.compute_type,
                                           local_files_only=True)
            except Exception as exc:
                raise VoiceError(f"could not load local speech model: {exc}") from exc
        return self._model

    def transcribe_detailed(self, audio: RecordedAudio, cancel: threading.Event) -> Transcript:
        """Auto-detect a dominant language while preserving Hindi/English code-switched text."""
        if cancel.is_set(): raise VoiceCancelled("transcription cancelled")
        try:
            segments, info = self._load().transcribe(audio.samples, language=self.language,
                                                      vad_filter=True, beam_size=1)
            parts = []
            for segment in segments:
                if cancel.is_set(): raise VoiceCancelled("transcription cancelled")
                parts.append(str(segment.text).strip())
            text = " ".join(part for part in parts if part).strip()
            language = getattr(info, "language", self.language)
            probability = getattr(info, "language_probability", None)
        except VoiceCancelled:
            raise
        except VoiceError:
            raise
        except Exception as exc:
            raise VoiceError(f"speech recognition failed: {exc}") from exc
        if not text: raise VoiceError("no speech was recognized; the task was not executed")
        uncertain = probability is not None and float(probability) < 0.65
        return Transcript(text, str(language) if language else None,
                          float(probability) if probability is not None else None, uncertain)

    def transcribe(self, audio: RecordedAudio, cancel: threading.Event) -> str:
        return self.transcribe_detailed(audio, cancel).text

    def close(self) -> None:
        self._model = None
