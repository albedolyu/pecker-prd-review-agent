"""Smoke-check Pecker's Langfuse control-plane integration.

Default mode is read-only: it checks credentials, SDK availability, auth,
prompt fetch, and score API presence. Use --write-score only when intentionally
writing a tiny smoke score into Langfuse.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Optional

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from api.sanitize import redact_text
from review.langfuse_prompt_provider import resolve_text_prompt, worker_prompt_name
from scripts.langfuse_seed_worker_prompts import DEFAULT_DIM_KEYS


ClientFactory = Callable[[], Any]
SMOKE_SESSION_ID = "pecker-langfuse-smoke"


def run_langfuse_smoke_check(
    *,
    dim_keys: Iterable[str] = DEFAULT_DIM_KEYS,
    client_factory: Optional[ClientFactory] = None,
    sdk_available: Optional[bool] = None,
    write_score: bool = False,
) -> Dict[str, Any]:
    configured = bool(os.environ.get("LANGFUSE_PUBLIC_KEY") and os.environ.get("LANGFUSE_SECRET_KEY"))
    sdk_ok = importlib.util.find_spec("langfuse") is not None if sdk_available is None else bool(sdk_available)
    result: Dict[str, Any] = {
        "ok": False,
        "configured": configured,
        "sdk_available": sdk_ok,
        "host": _langfuse_host_label(),
        "prompt_label": _prompt_label(),
        "auth": {"status": "pending"},
        "prompts": {"status": "pending", "checked": []},
        "score_api": {"status": "pending", "write_score": bool(write_score)},
    }

    if not configured:
        result["auth"] = {"status": "missing_credentials"}
        result["prompts"] = {"status": "skipped", "checked": []}
        result["score_api"] = {"status": "skipped", "write_score": bool(write_score)}
        return result
    if not sdk_ok:
        result["auth"] = {"status": "sdk_missing"}
        result["prompts"] = {"status": "skipped", "checked": []}
        result["score_api"] = {"status": "skipped", "write_score": bool(write_score)}
        return result

    try:
        client = (client_factory or _default_langfuse_client_factory)()
    except Exception as exc:  # noqa: BLE001
        result["auth"] = {"status": "client_error", "error": _safe_error(exc)}
        result["prompts"] = {"status": "skipped", "checked": []}
        result["score_api"] = {"status": "skipped", "write_score": bool(write_score)}
        return result

    result["auth"] = _check_auth(client)
    if result["auth"]["status"] != "ready":
        result["prompts"] = {"status": "skipped", "checked": []}
        result["score_api"] = {"status": "skipped", "write_score": bool(write_score)}
        return result

    result["prompts"] = _check_prompts(dim_keys, client)
    result["score_api"] = _check_score_api(client, write_score=write_score)
    result["ok"] = (
        result["auth"]["status"] == "ready"
        and result["prompts"]["status"] == "ready"
        and result["score_api"]["status"] in {"ready", "written"}
    )
    return result


def _check_auth(client: Any) -> Dict[str, Any]:
    auth_check = getattr(client, "auth_check", None)
    if not callable(auth_check):
        return {"status": "api_missing"}
    try:
        return {"status": "ready"} if auth_check() else {"status": "failed"}
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": _safe_error(exc)}


def _check_prompts(dim_keys: Iterable[str], client: Any) -> Dict[str, Any]:
    checked = []
    for dim_key in dim_keys:
        name = worker_prompt_name(str(dim_key))
        resolved = resolve_text_prompt(
            name,
            fallback_text="fallback {{dimension_name}}",
            variables={
                "codename": "smoke",
                "dimension_name": str(dim_key),
                "dimension_rules": "- smoke",
                "checklist_list": "- smoke",
                "tone_instructions_block": "",
            },
            client_factory=lambda: client,
        )
        metadata = dict(resolved.metadata or {})
        status = str(metadata.get("status") or "unknown")
        source = str(metadata.get("source") or "unknown")
        item = {
            "name": name,
            "status": status,
            "label": metadata.get("label"),
            "version": metadata.get("version"),
            "hash": metadata.get("hash"),
            "source": source,
        }
        if metadata.get("error"):
            item["error"] = redact_text(str(metadata["error"]))[:300]
        checked.append(item)
    ready = all(
        item["status"] == "ready"
        and item["source"] == "langfuse"
        and item.get("label")
        and item.get("hash")
        for item in checked
    )
    return {"status": "ready" if ready else "error", "checked": checked}


def _check_score_api(client: Any, *, write_score: bool) -> Dict[str, Any]:
    create_score = getattr(client, "create_score", None)
    current_trace_score = getattr(client, "score_current_trace", None)
    legacy_score = getattr(client, "score", None)
    score_fn = next(
        (fn for fn in (create_score, current_trace_score, legacy_score) if callable(fn)),
        None,
    )
    if score_fn is None:
        return {"status": "api_missing", "write_score": bool(write_score)}
    if not write_score:
        return {"status": "ready", "write_score": False}
    if not callable(create_score):
        return {"status": "trace_score_api_missing", "write_score": True}
    try:
        trace_id = _smoke_trace_id(client)
        trace_url = _smoke_trace_url(client, trace_id)
        create_score(
            name="pecker.smoke.score_api",
            value=1.0,
            session_id=SMOKE_SESSION_ID,
            trace_id=trace_id,
            data_type="NUMERIC",
            comment="Pecker Langfuse smoke check",
            metadata={"source": "langfuse_smoke_check"},
        )
        flush = getattr(client, "flush", None)
        if callable(flush):
            flush()
        result = {
            "status": "written",
            "write_score": True,
            "session_id": SMOKE_SESSION_ID,
            "trace_id": trace_id,
            "trace_linked": bool(trace_id),
        }
        if trace_url:
            result["trace_url"] = trace_url
        return result
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "write_score": True, "error": _safe_error(exc)}


def _default_langfuse_client_factory() -> Any:
    try:
        from langfuse import get_client
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("langfuse package is not available") from exc
    return get_client()


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
    except Exception:
        return
    load_dotenv(_REPO_ROOT / ".env", override=False)


def _langfuse_host_label() -> str:
    return os.environ.get("LANGFUSE_BASE_URL") or os.environ.get("LANGFUSE_HOST") or ""


def _prompt_label() -> str:
    return (
        os.environ.get("PECKER_LANGFUSE_PROMPT_LABEL")
        or os.environ.get("LANGFUSE_PROMPT_LABEL")
        or "production"
    )


def _smoke_trace_id(client: Any) -> str:
    create_trace_id = getattr(client, "create_trace_id", None)
    if callable(create_trace_id):
        try:
            trace_id = str(create_trace_id(seed=SMOKE_SESSION_ID) or "")
            if _is_trace_id(trace_id):
                return trace_id
        except Exception:  # noqa: BLE001
            pass
    return hashlib.sha256(SMOKE_SESSION_ID.encode()).hexdigest()[:32]


def _smoke_trace_url(client: Any, trace_id: str) -> str:
    get_trace_url = getattr(client, "get_trace_url", None)
    if not callable(get_trace_url):
        return ""
    try:
        url = str(get_trace_url(trace_id=trace_id) or "")
    except Exception:  # noqa: BLE001
        return ""
    return url[:500] if url.startswith(("https://", "http://")) else ""


def _is_trace_id(value: str) -> bool:
    text = str(value or "").strip().lower()
    return len(text) == 32 and all(char in "0123456789abcdef" for char in text)


def _safe_error(exc: Exception) -> str:
    redacted = redact_text(str(exc or ""))
    for key in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY"):
        value = os.environ.get(key, "")
        if value:
            redacted = redacted.replace(value, "[REDACTED_SECRET]")
    return redacted[:500]


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Smoke-check Pecker Langfuse configuration")
    parser.add_argument("--dim", action="append", dest="dims", help="Dimension key to check; repeatable")
    parser.add_argument("--write-score", action="store_true", help="Write a tiny smoke score to Langfuse")
    args = parser.parse_args(argv)

    _load_dotenv()
    result = run_langfuse_smoke_check(
        dim_keys=args.dims or DEFAULT_DIM_KEYS,
        write_score=args.write_score,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
