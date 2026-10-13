"""Interruptible WAV playback using optional sounddevice/soundfile packages."""
from __future__ import annotations

import threading

from .providers import AudioOutputProvider, ProviderHealth, SynthesizedAudio, VoiceCancelled, VoiceError


class SoundDeviceAudioOutput(AudioOutputProvider):
    def __init__(self) -> None:
        self._stop = threading.Event()

    @staticmethod
    def _modules():
        try:
            import sounddevice as sd
            import soundfile as sf
            return sd, sf
        except ImportError as exc:
            raise VoiceError("audio playback unavailable; install the 'voice' optional dependencies") from exc

    def health(self) -> ProviderHealth:
        try:
            sd, _sf = self._modules(); devices = sd.query_devices()
            found = any(int(device.get("max_output_channels", 0)) > 0 for device in devices)
            return ProviderHealth(found, "output device detected" if found else "no output device detected",
                                  device_detected=found, dependency_available=True)
        except Exception as exc:
            return ProviderHealth(False, str(exc), device_detected=False, dependency_available=False)

    def play(self, audio: SynthesizedAudio, cancel: threading.Event) -> None:
        sd, sf = self._modules(); self._stop.clear()
        try:
            data, sample_rate = sf.read(str(audio.path), dtype="float32")
            sd.play(data, sample_rate, blocking=False)
            while sd.get_stream().active:
                if cancel.wait(0.02) or self._stop.is_set():
                    sd.stop(); raise VoiceCancelled("audio playback interrupted")
        except VoiceCancelled:
            raise
        except Exception as exc:
            raise VoiceError(f"audio playback failed: {exc}") from exc
        finally:
            if audio.temporary: audio.path.unlink(missing_ok=True)

    def stop(self) -> None:
        self._stop.set()
        try:
            import sounddevice as sd
            sd.stop()
        except (ImportError, Exception):
            pass
