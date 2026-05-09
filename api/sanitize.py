"""Small sanitizers for PM-visible events and operational logs."""
from __future__ import annotations

import re
from typing import Any

_SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._-]{16,}"),
    re.compile(r"(?i)(api[_-]?key\s*[:=]\s*)[^\s,;]+"),
    re.compile(r"(?i)(password\s*[:=]\s*)[^\s,;]+"),
)


def redact_text(value: str) -> str:
    redacted = value
    redacted = _SECRET_PATTERNS[0].sub("[REDACTED_SECRET]", redacted)
    for pattern in _SECRET_PATTERNS[1:]:
        redacted = pattern.sub(lambda match: f"{match.group(1)}[REDACTED_SECRET]", redacted)
    return redacted


def redact_sensitive(value: Any) -> Any:
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        return {key: redact_sensitive(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_sensitive(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_sensitive(item) for item in value)
    return value
