"""Offline Piper synthesis with explicit, language-verified local voice models."""
from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import threading
import time

from .providers import ProviderHealth, SynthesizedAudio, TextToSpeechProvider, VoiceCancelled, VoiceError


class PiperProvider(TextToSpeechProvider):
    def __init__(self, executable: Path, model_path: Path, *, speaking_rate: float = 1.0,
                 required_language: str | None = None) -> None:
        self.executable, self.model_path = executable, model_path
        self.speaking_rate, self.required_language = speaking_rate, required_language

    def _resolved_executable(self) -> str | None:
        if self.executable.is_file(): return str(self.executable)
        return shutil.which(str(self.executable))

    def configured_language(self) -> str | None:
        metadata = Path(f"{self.model_path}.json")
        if not metadata.is_file(): return None
        try:
            value = json.loads(metadata.read_text(encoding="utf-8")); language = value.get("language", {})
            return str(language.get("code") or language.get("family") or "") or None
        except (OSError, UnicodeError, json.JSONDecodeError, AttributeError): return None

    def health(self) -> ProviderHealth:
        exe, model = self._resolved_executable() is not None, self.model_path.is_file(); missing = []
        if not exe: missing.append(f"Piper executable not found: {self.executable}")
        if not model: missing.append(f"voice model not found: {self.model_path}")
        language_ok = True
        if model and self.required_language:
            language = self.configured_language()
            language_ok = bool(language and language.lower().startswith(self.required_language.lower()))
            if not language_ok: missing.append(f"voice metadata does not verify {self.required_language} support")
        return ProviderHealth(exe and model and language_ok,
            "; ".join(missing) if missing else "Piper and verified voice model found",
            model_available=model and language_ok, dependency_available=exe)

    def synthesize(self, text: str, cancel: threading.Event) -> SynthesizedAudio:
        if not text.strip(): raise VoiceError("cannot synthesize empty text")
        if cancel.is_set(): raise VoiceCancelled("speech synthesis cancelled")
        health = self.health()
        if not health.available: raise VoiceError(health.detail)
        handle = tempfile.NamedTemporaryFile(prefix="jean-grey-", suffix=".wav", delete=False)
        handle.close(); output = Path(handle.name); executable = self._resolved_executable()
        if executable is None: raise VoiceError(f"Piper executable not found: {self.executable}")
        command = [executable, "--model", str(self.model_path), "--output_file", str(output)]
        if self.speaking_rate != 1.0: command.extend(["--length_scale", str(1.0 / self.speaking_rate)])
        try:
            process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                       stderr=subprocess.PIPE, text=True)
            assert process.stdin is not None
            process.stdin.write(text); process.stdin.close(); deadline = time.monotonic() + 120
            while process.poll() is None:
                if cancel.wait(0.02):
                    process.kill(); process.wait(); raise VoiceCancelled("speech synthesis cancelled")
                if time.monotonic() >= deadline:
                    process.kill(); process.wait(); raise VoiceError("Piper synthesis timed out")
            stderr = process.stderr.read() if process.stderr is not None else ""
            if process.returncode != 0 or not output.is_file() or output.stat().st_size == 0:
                raise VoiceError(f"Piper synthesis failed: {(stderr or 'no audio produced').strip()}")
            return SynthesizedAudio(output)
        except (OSError, VoiceCancelled, VoiceError): output.unlink(missing_ok=True); raise

    def close(self) -> None: pass


class MultilingualPiperProvider(TextToSpeechProvider):
    """Route Devanagari to a verified Hindi voice; never pretend the default voice supports it."""
    def __init__(self, default: PiperProvider, hindi: PiperProvider | None = None) -> None:
        self.default, self.hindi = default, hindi

    def health(self) -> ProviderHealth: return self.default.health()

    def hindi_health(self) -> ProviderHealth:
        if self.hindi is None:
            return ProviderHealth(False, "Hindi voice is not configured; Hindi remains text-only",
                                  model_available=False)
        return self.hindi.health()

    def synthesize(self, text: str, cancel: threading.Event) -> SynthesizedAudio:
        if re.search(r"[\u0900-\u097f]", text):
            health = self.hindi_health()
            if self.hindi is None or not health.available: raise VoiceError(health.detail)
            return self.hindi.synthesize(text, cancel)
        return self.default.synthesize(text, cancel)

    def close(self) -> None:
        self.default.close()
        if self.hindi is not None: self.hindi.close()
