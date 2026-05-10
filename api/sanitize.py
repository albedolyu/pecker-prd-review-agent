"""Small sanitizers for PM-visible events and operational logs."""
from __future__ import annotations

import re
from typing import Any

_SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._-]{16,}"),
    re.compile(r"(?i)(authorization\s*[:=]\s*basic\s+)[^\s,;&]+"),
    re.compile(r"(?i)(set-cookie\s*[:=]\s*)[^;\r\n]+"),
    re.compile(r"(?i)(cookie\s*[:=]\s*)[^;\r\n]+"),
    re.compile(
        r"(?i)((?:[\"'])(?:api[_-]?key|(?:[a-z0-9]+[_-])?access[_-]key[_-]id|private[_-]?key|[a-z0-9]+[_-]secret[_-]access[_-]key|jwt|(?:access|refresh|id)?[_-]?token|[a-z0-9]+[_-]token|(?:client[_-]?)?secret(?:[_-]?key)?|password|authorization|cookie|set-cookie)(?:[\"']\s*:\s*[\"']))[^\"'\r\n]+"
    ),
    re.compile(r"(?i)(api[_-]?key\s*[:=]\s*)[^\s,;&]+"),
    re.compile(r"(?i)((?:[a-z0-9]+[_-])?access[_-]key[_-]id\s*[:=]\s*)[^\s,;&]+"),
    re.compile(r"(?i)(jwt\s*[:=]\s*)[^\s,;&]+"),
    re.compile(r"(?i)((?:access[_-]?token|token)\s*[:=]\s*)[^\s,;&]+"),
    re.compile(r"(?i)([a-z0-9]+[_-]secret[_-]access[_-]key\s*[:=]\s*)[^\s,;&]+"),
    re.compile(r"(?i)((?:client[_-]?secret|secret[_-]?key)\s*[:=]\s*)[^\s,;&]+"),
    re.compile(r"(?i)(private[_-]?key\s*[:=]\s*)[^\s,;&]+"),
    re.compile(r"(?i)(password\s*[:=]\s*)[^\s,;&]+"),
)
_SECRET_FIELD_RE = re.compile(
    r"(?i)^(?:api[_-]?key|[a-z0-9]+[_-]api[_-]?key|(?:[a-z0-9]+[_-])?access[_-]key[_-]id|private[_-]?key|[a-z0-9]+[_-]secret[_-]access[_-]key|jwt|(?:access|refresh|id)?[_-]?token|[a-z0-9]+(?:[_-][a-z0-9]+)*[_-]token|(?:client[_-]?)?secret(?:[_-]?key)?|password|authorization|proxy[_-]?authorization|cookie|set-cookie)$"
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
        return {
            key: "[REDACTED_SECRET]" if _SECRET_FIELD_RE.match(str(key)) else redact_sensitive(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_sensitive(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_sensitive(item) for item in value)
    return value
