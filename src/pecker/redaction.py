from __future__ import annotations

import re

SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9_]{20,}"),
    re.compile(r"(?i)(api[_-]?key|token|secret|password)\s*[:=]\s*['\"]?[^'\"\s]+"),
]

PRIVATE_URL_PATTERNS = [
    re.compile(r"https?://10(?:\.\d{1,3}){3}[^\s]*"),
    re.compile(r"https?://192\.168(?:\.\d{1,3}){2}[^\s]*"),
    re.compile(r"https?://172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2}[^\s]*"),
]


def redact_text(text: str) -> str:
    redacted = text
    for pattern in SECRET_PATTERNS:
        redacted = pattern.sub("[REDACTED_SECRET]", redacted)
    for pattern in PRIVATE_URL_PATTERNS:
        redacted = pattern.sub("[REDACTED_PRIVATE_URL]", redacted)
    return redacted


def redact_mapping(value: dict[str, object]) -> dict[str, object]:
    safe: dict[str, object] = {}
    for key, item in value.items():
        if any(word in key.lower() for word in ("key", "token", "secret", "password")):
            safe[key] = "[REDACTED_SECRET]"
        elif isinstance(item, str):
            safe[key] = redact_text(item)
        else:
            safe[key] = item
    return safe
