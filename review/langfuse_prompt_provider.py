"""Optional Langfuse prompt management with local fallback.

Prompt management is read-only and non-critical: Langfuse may serve versioned
templates, while local code still owns fallback text and schema constraints.
"""
from __future__ import annotations

import hashlib
import importlib.util
import os
from dataclasses import dataclass
from typing import Any, Callable, Dict, Mapping, Optional

from api.sanitize import redact_text


ClientFactory = Callable[[], Any]


@dataclass(frozen=True)
class PromptResolution:
    text: str
    metadata: Dict[str, Any]


def worker_prompt_name(dim_key: str) -> str:
    prefix = os.environ.get("PECKER_LANGFUSE_PROMPT_PREFIX", "pecker").strip() or "pecker"
    return f"{prefix}.worker.{_safe_name(dim_key or 'unknown')}.system"


def resolve_text_prompt(
    name: str,
    *,
    fallback_text: str,
    variables: Optional[Mapping[str, Any]] = None,
    client_factory: Optional[ClientFactory] = None,
) -> PromptResolution:
    variables = dict(variables or {})
    fallback_text = str(fallback_text or "")
    base_metadata = {
        "name": str(name or ""),
        "hash": _hash_text(fallback_text),
    }
    readiness = prompt_management_status_snapshot()
    if readiness["status"] != "ready":
        return PromptResolution(
            text=fallback_text,
            metadata={
                **base_metadata,
                "source": "local_fallback",
                "status": readiness["status"],
                "enabled": False,
            },
        )

    try:
        client = (client_factory or _default_langfuse_client_factory)()
        prompt = client.get_prompt(name, **_get_prompt_kwargs(fallback_text))
        text = _compile_prompt(prompt, variables, fallback_text=fallback_text)
        is_fallback = bool(getattr(prompt, "is_fallback", False))
        return PromptResolution(
            text=text,
            metadata={
                **base_metadata,
                "source": "local_fallback" if is_fallback else "langfuse",
                "status": "fallback" if is_fallback else "ready",
                "enabled": True,
                "label": _prompt_label(),
                "version": _prompt_version_from(prompt),
                "hash": _hash_text(text),
            },
        )
    except Exception as exc:  # noqa: BLE001
        return PromptResolution(
            text=fallback_text,
            metadata={
                **base_metadata,
                "source": "local_fallback",
                "status": "error",
                "enabled": False,
                "error": _redact_langfuse_error(str(exc))[:500],
            },
        )


def prompt_management_status_snapshot() -> Dict[str, Any]:
    flag = os.environ.get("PECKER_LANGFUSE_PROMPTS_ENABLED", "auto").strip().lower()
    disabled = flag in {"0", "false", "no", "off", "disabled"}
    forced = flag in {"1", "true", "yes", "on", "enabled"}
    configured = bool(os.environ.get("LANGFUSE_PUBLIC_KEY") and os.environ.get("LANGFUSE_SECRET_KEY"))
    sdk_available = importlib.util.find_spec("langfuse") is not None
    prefix = os.environ.get("PECKER_LANGFUSE_PROMPT_PREFIX", "pecker").strip() or "pecker"
    version = os.environ.get("PECKER_LANGFUSE_PROMPT_VERSION", "").strip()

    if disabled:
        status = "disabled"
    elif forced and not configured:
        status = "missing_credentials"
    elif not configured:
        status = "disabled"
    elif not sdk_available:
        status = "sdk_missing"
    else:
        status = "ready"

    snapshot: Dict[str, Any] = {
        "configured": configured,
        "enabled": status == "ready",
        "status": status,
        "sdk_available": sdk_available,
        "prefix": prefix,
        "label": _prompt_label(),
    }
    if version:
        snapshot["version"] = version
    return snapshot


def _get_prompt_kwargs(fallback_text: str) -> Dict[str, Any]:
    kwargs: Dict[str, Any] = {
        "type": "text",
        "fallback": fallback_text,
        "cache_ttl_seconds": _env_int("PECKER_LANGFUSE_PROMPT_CACHE_TTL_SECONDS", 300),
        "fetch_timeout_seconds": _env_float("PECKER_LANGFUSE_PROMPT_FETCH_TIMEOUT_SECONDS", 10.0),
        "max_retries": _env_int("PECKER_LANGFUSE_PROMPT_MAX_RETRIES", 0),
    }
    version = os.environ.get("PECKER_LANGFUSE_PROMPT_VERSION", "").strip()
    if version:
        try:
            kwargs["version"] = int(version)
        except ValueError:
            kwargs["label"] = _prompt_label()
    else:
        kwargs["label"] = _prompt_label()
    return kwargs


def _compile_prompt(prompt: Any, variables: Mapping[str, Any], *, fallback_text: str) -> str:
    compiler = getattr(prompt, "compile", None)
    if callable(compiler):
        compiled = compiler(**variables)
        if isinstance(compiled, str):
            return compiled
    text = getattr(prompt, "prompt", None)
    if isinstance(text, str):
        return text
    return fallback_text


def _default_langfuse_client_factory() -> Any:
    try:
        from langfuse import get_client
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("langfuse package is not available") from exc
    return get_client()


def _prompt_label() -> str:
    return (
        os.environ.get("PECKER_LANGFUSE_PROMPT_LABEL", "")
        or os.environ.get("LANGFUSE_PROMPT_LABEL", "")
        or "production"
    ).strip()


def _prompt_version_from(prompt: Any) -> Optional[int]:
    version = getattr(prompt, "version", None)
    try:
        return int(version)
    except (TypeError, ValueError):
        return None


def _hash_text(text: str) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8", errors="replace")).hexdigest()[:12]


def _redact_langfuse_error(value: str) -> str:
    redacted = redact_text(str(value or ""))
    for name in (
        "LANGFUSE_PUBLIC_KEY",
        "LANGFUSE_SECRET_KEY",
        "LANGFUSE_BASE_URL",
        "LANGFUSE_HOST",
    ):
        secret = os.environ.get(name, "")
        if secret and len(secret) >= 4:
            redacted = redacted.replace(secret, "[REDACTED_SECRET]")
    return redacted


def _safe_name(value: str) -> str:
    text = str(value or "unknown").strip().lower()
    safe = "".join(ch if ch.isalnum() or ch in {"_", "-", "."} else "_" for ch in text)
    return safe[:80] or "unknown"


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default
