"""Lazy sounddevice microphone capture for push-to-talk sessions."""
from __future__ import annotations

import threading
import time

from .providers import AudioInputProvider, ProviderHealth, RecordedAudio, VoiceCancelled, VoiceError


class SoundDeviceAudioInput(AudioInputProvider):
    def __init__(self, sample_rate: int = 16_000, channels: int = 1) -> None:
        self.sample_rate, self.channels = sample_rate, channels

    @staticmethod
    def _modules():
        try:
            import numpy as np
            import sounddevice as sd
            return np, sd
        except ImportError as exc:
            raise VoiceError("audio input unavailable; install the 'voice' optional dependencies") from exc

    def health(self) -> ProviderHealth:
        try:
            _np, sd = self._modules()
            devices = sd.query_devices()
            detected = any(int(device.get("max_input_channels", 0)) > 0 for device in devices)
            return ProviderHealth(detected, "microphone detected" if detected else "no input device detected",
                                  device_detected=detected, dependency_available=True)
        except Exception as exc:
            return ProviderHealth(False, str(exc), device_detected=False, dependency_available=False)

    def capture_utterance(self, cancel: threading.Event, *, max_seconds: float = 15.0,
                          silence_seconds: float = 1.0, threshold: float = 0.01) -> RecordedAudio:
        """Capture one utterance with local amplitude-based endpoint detection."""
        np, sd = self._modules(); chunks = []; speech_started = False; silent_frames = 0
        block_seconds = 0.1; needed_silence = max(1, int(silence_seconds / block_seconds))
        max_frames = max(1, int(max_seconds / block_seconds))
        try:
            with sd.InputStream(samplerate=self.sample_rate, channels=self.channels, dtype="float32",
                                blocksize=int(self.sample_rate * block_seconds)) as stream:
                for _ in range(max_frames):
                    if cancel.is_set(): raise VoiceCancelled("recording cancelled")
                    data, _overflow = stream.read(int(self.sample_rate * block_seconds)); chunks.append(data.copy())
                    active = float(np.max(np.abs(data))) >= threshold
                    if active: speech_started = True; silent_frames = 0
                    elif speech_started:
                        silent_frames += 1
                        if silent_frames >= needed_silence: break
        except VoiceCancelled: raise
        except Exception as exc: raise VoiceError(f"microphone capture failed: {exc}") from exc
        if not speech_started: raise VoiceError("no speech was detected before the utterance timeout")
        return RecordedAudio(np.concatenate(chunks, axis=0).reshape(-1), self.sample_rate)

    def capture(self, stop: threading.Event, cancel: threading.Event) -> RecordedAudio:
        np, sd = self._modules()
        chunks = []
        def callback(indata, frames, timing, status):
            if status:
                # Nonfatal overflow status is surfaced only if no usable audio arrives.
                pass
            chunks.append(indata.copy())
        try:
            with sd.InputStream(samplerate=self.sample_rate, channels=self.channels,
                                dtype="float32", callback=callback):
                while not stop.wait(0.02):
                    if cancel.is_set():
                        raise VoiceCancelled("recording cancelled")
        except VoiceCancelled:
            raise
        except Exception as exc:
            raise VoiceError(f"microphone capture failed: {exc}") from exc
        if cancel.is_set():
            raise VoiceCancelled("recording cancelled")
        if not chunks:
            raise VoiceError("no audio was captured; check the microphone and try again")
        samples = np.concatenate(chunks, axis=0).reshape(-1)
        if samples.size == 0 or float(np.max(np.abs(samples))) < 0.0001:
            raise VoiceError("recording contained silence")
        return RecordedAudio(samples, self.sample_rate)
