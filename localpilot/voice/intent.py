"""Small deterministic voice-command parser; it never grants permissions."""
from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True, slots=True)
class BrowserSearchIntent:
    query: str
    compare_count: int = 1


def parse_browser_search(text: str) -> BrowserSearchIntent | None:
    lowered = text.lower().strip()
    signals = ("search karo", "search kar", "google par", "chrome par", "खोज", "सर्च")
    if not any(signal in lowered or signal in text for signal in signals): return None
    query = lowered
    for phrase in ("jean grey", "hello jean grey", "chrome par", "google par", "search karo",
                   "search kar", "please", "खोजो", "सर्च करो"):
        query = query.replace(phrase, " ")
    query = re.sub(r"\s+", " ", query).strip(" .,")
    if not query: return None
    compare = 3 if any(phrase in lowered for phrase in ("teen website", "three website", "3 website", "compare")) else 1
    return BrowserSearchIntent(query, compare)
