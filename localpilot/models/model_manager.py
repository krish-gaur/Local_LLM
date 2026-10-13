"""Resource checks and backend construction. Model downloads are intentionally absent."""
from __future__ import annotations

from dataclasses import dataclass
import os
import sys
from typing import Literal

from localpilot.config import Settings
from .base import ModelAdapter
from .ollama_adapter import OllamaAdapter

Profile = Literal["lightweight", "12b", "training"]


@dataclass(frozen=True, slots=True)
class ResourceSnapshot:
    total_ram_bytes: int
    available_ram_bytes: int
    platform: str


@dataclass(frozen=True, slots=True)
class CompatibilityResult:
    compatible: bool
    profile: Profile
    required_available_bytes: int
    available_bytes: int
    reason: str


def memory_snapshot() -> ResourceSnapshot:
    """Read memory without requiring psutil; supports Windows and POSIX."""
    if sys.platform == "win32":
        import ctypes
        class MemoryStatus(ctypes.Structure):
            _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong),
                        ("total_phys", ctypes.c_ulonglong), ("avail_phys", ctypes.c_ulonglong),
                        ("total_page", ctypes.c_ulonglong), ("avail_page", ctypes.c_ulonglong),
                        ("total_virtual", ctypes.c_ulonglong), ("avail_virtual", ctypes.c_ulonglong),
                        ("avail_extended", ctypes.c_ulonglong)]
        status = MemoryStatus()
        status.length = ctypes.sizeof(status)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            raise OSError("GlobalMemoryStatusEx failed")
        return ResourceSnapshot(status.total_phys, status.avail_phys, sys.platform)
    page_size = os.sysconf("SC_PAGE_SIZE")
    total = page_size * os.sysconf("SC_PHYS_PAGES")
    available_pages = os.sysconf_names.get("SC_AVPHYS_PAGES")
    available = page_size * os.sysconf(available_pages) if available_pages else total
    return ResourceSnapshot(total, available, sys.platform)


def check_compatibility(profile: Profile, resources: ResourceSnapshot | None = None) -> CompatibilityResult:
    resources = resources or memory_snapshot()
    # Conservative runtime headroom, not model-file size. Exact needs vary by quant/context/backend.
    required = {"lightweight": 3 * 1024**3, "12b": 12 * 1024**3, "training": 32 * 1024**3}[profile]
    ok = resources.available_ram_bytes >= required
    reason = "resource preflight passed" if ok else (
        f"refused: {profile} requires at least {required / 1024**3:.0f} GiB available RAM "
        f"by the conservative default, found {resources.available_ram_bytes / 1024**3:.1f} GiB"
    )
    return CompatibilityResult(ok, profile, required, resources.available_ram_bytes, reason)


def create_adapter(settings: Settings) -> ModelAdapter:
    if settings.backend != "ollama":
        raise ValueError(f"backend '{settings.backend}' is not implemented in milestone 1")
    return OllamaAdapter(settings.ollama_url, settings.model, settings.context_window,
                         settings.request_timeout_seconds)
