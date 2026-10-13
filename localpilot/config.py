"""Configuration loading with safe local-first defaults and legacy compatibility."""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path


def _env(name: str, default: str) -> str:
    """Prefer JEAN_GREY_* while retaining LOCALPILOT_* compatibility."""
    new = f"JEAN_GREY_{name}"
    legacy = f"LOCALPILOT_{name}"
    return os.environ[new] if new in os.environ else os.getenv(legacy, default)


def _default_data_dir() -> Path:
    current, legacy = Path.home() / ".jean-grey", Path.home() / ".localpilot"
    # Existing data remains in place and usable. New installations use the renamed directory.
    return legacy if legacy.exists() and not current.exists() else current


@dataclass(frozen=True, slots=True)
class Settings:
    backend: str = "ollama"
    model: str = "qwen2.5:1.5b"
    ollama_url: str = "http://127.0.0.1:11434"
    context_window: int = 2048
    offline: bool = True
    request_timeout_seconds: float = 120.0
    data_dir: Path = Path.home() / ".jean-grey"
    stt_model_size: str = "small"
    stt_model_path: Path = Path.home() / ".jean-grey" / "models" / "whisper-small"
    piper_executable: Path = Path("piper")
    piper_voice_path: Path = Path.home() / ".jean-grey" / "models" / "piper" / "voice.onnx"
    voice_rate: float = 1.0
    hands_free: bool = False
    mcp_config_path: Path = Path.home() / ".jean-grey" / "mcp.json"
    report_root: Path = Path.home() / ".jean-grey" / "reports"
    browser_max_pages: int = 10
    browser_max_actions: int = 30
    browser_max_content_chars: int = 100_000
    wake_word_model_path: Path = Path.home() / ".jean-grey" / "models" / "wake" / "hello-jean-grey.onnx"
    wake_word_threshold: float = 0.65
    preferred_voice_language: str = "auto"
    hindi_piper_voice_path: Path | None = None
    search_base_url: str = "https://www.google.com/search?q="

    @classmethod
    def from_env(cls) -> "Settings":
        offline = _env("OFFLINE", "true").strip().lower()
        if offline not in {"true", "false", "1", "0", "yes", "no"}:
            raise ValueError("JEAN_GREY_OFFLINE must be true or false")
        context = int(_env("CONTEXT_WINDOW", "2048"))
        if not 256 <= context <= 131072:
            raise ValueError("JEAN_GREY_CONTEXT_WINDOW must be between 256 and 131072")
        timeout = float(_env("REQUEST_TIMEOUT", "120"))
        if not 1 <= timeout <= 3600:
            raise ValueError("JEAN_GREY_REQUEST_TIMEOUT must be between 1 and 3600 seconds")
        data_dir = Path(_env("DATA_DIR", str(_default_data_dir()))).expanduser()
        stt_size = _env("STT_MODEL_SIZE", "small").strip().lower()
        if stt_size not in {"tiny", "base", "small", "medium", "large-v3"}:
            raise ValueError("JEAN_GREY_STT_MODEL_SIZE is not supported")
        rate = float(_env("VOICE_RATE", "1.0"))
        if not 0.5 <= rate <= 2.0: raise ValueError("JEAN_GREY_VOICE_RATE must be between 0.5 and 2.0")
        max_pages, max_actions = int(_env("BROWSER_MAX_PAGES", "10")), int(_env("BROWSER_MAX_ACTIONS", "30"))
        max_content = int(_env("BROWSER_MAX_CONTENT_CHARS", "100000"))
        if not 1 <= max_pages <= 10 or not 1 <= max_actions <= 30 or not 1000 <= max_content <= 500000:
            raise ValueError("browser limits are outside safe bounds")
        wake_threshold = float(_env("WAKE_WORD_THRESHOLD", "0.65"))
        if not 0.1 <= wake_threshold <= 0.99: raise ValueError("JEAN_GREY_WAKE_WORD_THRESHOLD must be 0.1..0.99")
        preferred_language = _env("VOICE_LANGUAGE", "auto").lower()
        if preferred_language not in {"auto", "hi", "en", "hinglish"}:
            raise ValueError("JEAN_GREY_VOICE_LANGUAGE is invalid")
        return cls(
            backend=_env("BACKEND", "ollama").strip().lower(), model=_env("MODEL", "qwen2.5:1.5b").strip(),
            ollama_url=_env("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/"), context_window=context,
            offline=offline in {"true", "1", "yes"}, request_timeout_seconds=timeout, data_dir=data_dir,
            stt_model_size=stt_size,
            stt_model_path=Path(_env("STT_MODEL_PATH", str(data_dir / "models" / f"whisper-{stt_size}"))).expanduser(),
            piper_executable=Path(_env("PIPER_EXECUTABLE", "piper")).expanduser(),
            piper_voice_path=Path(_env("PIPER_VOICE_PATH", str(data_dir / "models" / "piper" / "voice.onnx"))).expanduser(),
            voice_rate=rate, hands_free=_env("HANDS_FREE", "false").lower() in {"true", "1", "yes"},
            mcp_config_path=Path(_env("MCP_CONFIG", str(data_dir / "mcp.json"))).expanduser(),
            report_root=Path(_env("REPORT_ROOT", str(data_dir / "reports"))).expanduser(),
            browser_max_pages=max_pages, browser_max_actions=max_actions,
            browser_max_content_chars=max_content,
            wake_word_model_path=Path(_env("WAKE_WORD_MODEL_PATH", str(data_dir / "models" / "wake" / "hello-jean-grey.onnx"))).expanduser(),
            wake_word_threshold=wake_threshold, preferred_voice_language=preferred_language,
            hindi_piper_voice_path=(Path(_env("HINDI_PIPER_VOICE_PATH", "")).expanduser()
                                    if _env("HINDI_PIPER_VOICE_PATH", "") else None),
            search_base_url=_env("SEARCH_BASE_URL", "https://www.google.com/search?q="),
        )
