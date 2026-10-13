"""Multilingual transcript records shared across speech providers and conversations."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Transcript:
    text: str
    language: str | None = None
    language_probability: float | None = None
    uncertain: bool = False
