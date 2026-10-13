"""Side-effect-free voice health and resource preflight."""
from __future__ import annotations

from dataclasses import asdict
from typing import Any

from localpilot.models.model_manager import memory_snapshot
from .providers import AudioInputProvider, AudioOutputProvider, SpeechToTextProvider, TextToSpeechProvider
from .wake_word import WakeWordProvider


def voice_health(audio_input: AudioInputProvider, stt: SpeechToTextProvider,
                 tts: TextToSpeechProvider, output: AudioOutputProvider,
                 *, offline: bool, wake_word: WakeWordProvider | None = None) -> dict[str, Any]:
    available = memory_snapshot().available_ram_bytes
    result = {
        "offline": offline,
        "audio_input": asdict(audio_input.health()),
        "speech_to_text": asdict(stt.health()),
        "text_to_speech": asdict(tts.health()),
        "audio_output": asdict(output.health()),
        "resource_preflight": {
            "available_ram_bytes": available,
            "recommended_minimum_bytes": 2 * 1024**3,
            "passed": available >= 2 * 1024**3,
            "detail": "Use a small/int8 STT model and unload providers when finished.",
        },
    }
    if wake_word is not None: result["wake_word"] = asdict(wake_word.health())
    hindi_health = getattr(tts, "hindi_health", None)
    if hindi_health is not None: result["hindi_text_to_speech"] = asdict(hindi_health())
    return result
