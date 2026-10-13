"""Best-effort diagnostic redaction; secret values are never intentionally logged."""
from __future__ import annotations

import re
from typing import Mapping

_SECRET_KEY = re.compile(r"(?i)(token|secret|password|passwd|api[_-]?key|cookie|authorization)")


def redact_mapping(values: Mapping[str, str]) -> dict[str, str]:
    return {key: "<redacted>" if _SECRET_KEY.search(key) else value for key, value in values.items()}


def redact_text(text: str, known_secrets: tuple[str, ...] = ()) -> str:
    result = text
    for secret in known_secrets:
        if secret: result = result.replace(secret, "<redacted>")
    result = re.sub(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+", r"\1<redacted>", result)
    result = re.sub(r"(?i)((?:token|password|api[_-]?key)\s*[=:]\s*)\S+", r"\1<redacted>", result)
    return result
