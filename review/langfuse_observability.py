"""Optional Langfuse tracing for the LangGraph review flow.

The review path must keep working when Langfuse is not configured. This module
keeps SDK imports lazy and sends only operational summaries, never raw PRD
content, wiki pages, worker findings, or secrets.
"""
from __future__ import annotations

import hashlib
import importlib
import importlib.util
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterable, Optional

from api.sanitize import redact_prd_content, redact_sensitive, redact_text


ClientFactory = Callable[[], Any]

_TRUE_VALUES = {"1", "true", "yes", "on"}
_RAW_PAYLOAD_KEYS = {
    "prd_content",
    "prd_body",
    "prd_text",
    "raw_materials",
    "supplemental_materials_raw",
    "wiki_pages",
    "user_notes",
    "messages",
    "prompt",
    "items",
    "merged_items",
    "workers",
    "last_workers",
    "round_worker_results",
    "rounds_merged",
}
_MAX_STRING_CHARS = 500
_MAX_LIST_ITEMS = 20
_MAX_DEPTH = 5


def start_langgraph_review_trace(
    *,
    workspace: Optional[str],
    thread_id: Optional[str],
    prd_content: str,
    wiki_pages: Dict[str, str],
    voting_rounds: int,
    dimensions: Iterable[str],
    client_factory: Optional[ClientFactory] = None,
    trace_name: str = "pecker.langgraph.review",
) -> "LangGraphLangfuseTrace":
    return LangGraphLangfuseTrace(
        trace_name=trace_name,
        workspace=workspace or "",
        thread_id=thread_id or "",
        prd_content=prd_content or "",
        wiki_pages=wiki_pages or {},
        voting_rounds=max(1, int(voting_rounds or 1)),
        dimensions=list(dimensions or []),
        client_factory=client_factory,
    )


def record_review_confirmation_scores(
    *,
    review_result: Dict[str, Any],
    decisions: Dict[str, Dict[str, Any]],
    client_factory: Optional[ClientFactory] = None,
    max_item_scores: int = 200,
) -> Dict[str, Any]:
    """Record PM confirm decisions as optional Langfuse scores.

    Only compact metadata is sent: item ids, rule ids, dimensions, severities,
    decision types, and safe reason categories. Raw findings and PRD content are
    intentionally excluded.
    """
    readiness = _langfuse_status_snapshot()
    configured = bool(readiness.get("configured"))
    trace_snapshot = _score_trace_snapshot(review_result)
    disabled_snapshot = {
        "enabled": False,
        "configured": configured,
        "status": str(readiness.get("status") or "disabled"),
        "scored_items": 0,
        "scores_sent": 0,
    }
    if not readiness.get("enabled"):
        return disabled_snapshot

    items = review_result.get("items") if isinstance(review_result, dict) else []
    item_map = {
        str(item.get("id") or ""): item
        for item in items or []
        if isinstance(item, dict) and item.get("id")
    }
    score_payloads = _confirmation_item_score_payloads(
        review_result=review_result,
        decisions=decisions,
        item_map=item_map,
        max_item_scores=max_item_scores,
    )
    if not score_payloads:
        return {
            "enabled": True,
            "configured": True,
            "status": "no_decisions",
            "scored_items": 0,
            "scores_sent": 0,
        }

    try:
        client = (client_factory or _default_langfuse_client_factory)()
        if not _client_can_create_score(client):
            return {
                "enabled": False,
                "configured": True,
                "status": "score_api_missing",
                "scored_items": 0,
                "scores_sent": 0,
            }

        accepted_count = 0
        score_requests = []
        for payload in score_payloads:
            value = payload["value"]
            if value >= 1.0:
                accepted_count += 1
            score_requests.append(payload["score"])

        aggregate_acceptance_rate = round(accepted_count / len(score_payloads), 3)
        aggregate_score = _confirmation_aggregate_score(
            review_result=review_result,
            scored_items=len(score_payloads),
            aggregate_acceptance_rate=aggregate_acceptance_rate,
        )
        score_requests.append(aggregate_score)
        scores_sent = _create_langfuse_scores(client, score_requests)

        return {
            "enabled": True,
            "configured": True,
            "status": "recorded",
            "scored_items": len(score_payloads),
            "scores_sent": scores_sent,
            **trace_snapshot,
            "aggregate_acceptance_rate": aggregate_acceptance_rate,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "enabled": False,
            "configured": True,
            "status": "error",
            "scored_items": 0,
            "scores_sent": 0,
            "error": _redact_env_secrets(str(exc))[:500],
        }


def record_evidence_verification_scores(
    *,
    review_result: Dict[str, Any],
    verified_items: list[Dict[str, Any]],
    summary: Optional[Dict[str, Any]] = None,
    client_factory: Optional[ClientFactory] = None,
    max_item_scores: int = 200,
) -> Dict[str, Any]:
    """Record evidence verification quality as optional Langfuse scores."""
    readiness = _langfuse_status_snapshot()
    configured = bool(readiness.get("configured"))
    trace_snapshot = _score_trace_snapshot(review_result)
    disabled_snapshot = {
        "enabled": False,
        "configured": configured,
        "status": str(readiness.get("status") or "disabled"),
        "scored_items": 0,
        "scores_sent": 0,
    }
    if not readiness.get("enabled"):
        return disabled_snapshot

    score_payloads = _evidence_item_score_payloads(
        review_result=review_result,
        verified_items=verified_items,
        max_item_scores=max_item_scores,
    )
    if not score_payloads:
        return {
            "enabled": True,
            "configured": True,
            "status": "no_items",
            "scored_items": 0,
            "scores_sent": 0,
        }

    reliability = _evidence_reliability(summary, score_payloads)
    caveat = _safe_summary_int(summary, "caveat")
    retracted = _safe_summary_int(summary, "retracted")
    try:
        client = (client_factory or _default_langfuse_client_factory)()
        if not _client_can_create_score(client):
            return {
                "enabled": False,
                "configured": True,
                "status": "score_api_missing",
                "scored_items": 0,
                "scores_sent": 0,
            }

        score_requests = [payload["score"] for payload in score_payloads]
        aggregate_score = _evidence_aggregate_score(
            review_result=review_result,
            scored_items=len(score_payloads),
            summary=summary or {},
            reliability=reliability,
            caveat=caveat,
            retracted=retracted,
        )
        score_requests.append(aggregate_score)
        scores_sent = _create_langfuse_scores(client, score_requests)

        return {
            "enabled": True,
            "configured": True,
            "status": "recorded",
            "scored_items": len(score_payloads),
            "scores_sent": scores_sent,
            **trace_snapshot,
            "reliability": reliability,
            "caveat": caveat,
            "retracted": retracted,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "enabled": False,
            "configured": True,
            "status": "error",
            "scored_items": 0,
            "scores_sent": 0,
            "error": _redact_env_secrets(str(exc))[:500],
        }


class LangGraphLangfuseTrace:
    def __init__(
        self,
        *,
        trace_name: str,
        workspace: str,
        thread_id: str,
        prd_content: str,
        wiki_pages: Dict[str, str],
        voting_rounds: int,
        dimensions: list[str],
        client_factory: Optional[ClientFactory],
    ):
        self.trace_name = trace_name or "pecker.langgraph.review"
        self.workspace = workspace
        self.thread_id = thread_id
        self.prd_content = prd_content
        self.wiki_pages = wiki_pages
        self.voting_rounds = voting_rounds
        self.dimensions = dimensions
        self.session_id = _safe_langfuse_attribute(thread_id, 200)
        self.trace_id = ""
        self.trace_url = ""
        self.client_factory = client_factory or _default_langfuse_client_factory
        self.configured = _langfuse_credentials_present()
        self.enabled = False
        self.status = "disabled"
        self.error = ""
        self._client: Any = None
        self._trace_attributes_cm: Any = None
        self._root_cm: Any = None
        self._root_observation: Any = None
        self._finished = False

    def __enter__(self) -> "LangGraphLangfuseTrace":
        if not self.configured or not _langfuse_enabled():
            return self
        try:
            self._client = self.client_factory()
            self._prepare_trace_link()
            self._open_trace_attributes()
            self._root_cm = self._start_observation(
                name=self.trace_name,
                input={
                    "prd_chars": len(self.prd_content),
                    "prd_sha256": _hash_text(self.prd_content),
                    "wiki_pages_count": len(self.wiki_pages),
                    "voting_rounds": self.voting_rounds,
                    "dimensions": self.dimensions,
                },
                metadata=self._base_metadata(),
            )
            self._root_observation = self._root_cm.__enter__()
            self.enabled = True
            self.status = "started"
        except Exception as exc:  # noqa: BLE001
            self._mark_error(exc)
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc is not None:
            self.finish(status="error", output={"error": str(exc)[:200]})
        self._close_root(exc_type, exc, tb)
        self._close_trace_attributes(exc_type, exc, tb)
        self._flush()
        return False

    def span(
        self,
        name: str,
        *,
        input: Any = None,  # noqa: A002 - Langfuse SDK uses this name.
        metadata: Any = None,
        as_type: str = "span",
    ) -> "_ObservationContext":
        if not self.enabled:
            return _NoopObservationContext()
        try:
            return self._start_observation(
                name=name,
                input=input,
                metadata=metadata,
                as_type=as_type,
            )
        except Exception as exc:  # noqa: BLE001
            self._mark_error(exc, keep_enabled=True)
            return _NoopObservationContext()

    def update_observation(
        self,
        observation: Any,
        *,
        output: Any = None,
        metadata: Any = None,
    ) -> None:
        if not self.enabled or observation is None:
            return
        try:
            update_payload: Dict[str, Any] = {}
            if output is not None:
                update_payload["output"] = _safe_payload(output, prd_body=self.prd_content)
            if metadata is not None:
                update_payload["metadata"] = _safe_payload(metadata, prd_body=self.prd_content)
            if update_payload and hasattr(observation, "update"):
                observation.update(**update_payload)
        except Exception as exc:  # noqa: BLE001
            self._mark_error(exc, keep_enabled=True)

    def finish(self, *, status: str = "done", output: Any = None) -> None:
        self.status = status or "done"
        self._finished = True
        if not self.enabled or self._root_observation is None:
            return
        self.update_observation(
            self._root_observation,
            output={
                "status": self.status,
                "result": output or {},
            },
        )

    def snapshot(self) -> Dict[str, Any]:
        if not self.configured:
            return {"enabled": False, "configured": False, "status": "disabled"}
        payload: Dict[str, Any] = {
            "enabled": bool(self.enabled),
            "configured": True,
            "status": self.status,
            "backend": "langfuse",
        }
        if self.session_id:
            payload["session_id"] = self.session_id
        if self.trace_id:
            payload["trace_id"] = self.trace_id
        if self.trace_url:
            payload["trace_url"] = self.trace_url
        if self.error:
            payload["error"] = self.error
        return payload

    def _base_metadata(self) -> Dict[str, Any]:
        return _safe_payload(
            {
                "workspace": self.workspace,
                "thread_id": self.thread_id,
                "session_id": self.session_id,
                "trace_id": self.trace_id,
                "trace_url": self.trace_url,
                "orchestrator": "langgraph",
                "environment": os.environ.get("LANGFUSE_TRACING_ENVIRONMENT")
                or os.environ.get("PECKER_ENV")
                or "",
                "wiki_page_keys": sorted(str(key) for key in self.wiki_pages.keys())[:50],
            },
            prd_body=self.prd_content,
        )

    def _start_observation(
        self,
        *,
        name: str,
        input: Any = None,  # noqa: A002 - Langfuse SDK uses this name.
        metadata: Any = None,
        as_type: str = "span",
    ) -> "_ObservationContext":
        if self._client is None:
            return _NoopObservationContext()
        trace_context = {"trace_id": self.trace_id} if self.trace_id else None
        return self._client.start_as_current_observation(
            name=name,
            as_type=as_type,
            trace_context=trace_context,
            input=_safe_payload(input, prd_body=self.prd_content),
            metadata=_safe_payload(metadata, prd_body=self.prd_content),
        )

    def _prepare_trace_link(self) -> None:
        seed = self.session_id or self.thread_id or self.trace_name
        trace_id = ""
        create_trace_id = getattr(self._client, "create_trace_id", None)
        if callable(create_trace_id):
            try:
                trace_id = str(create_trace_id(seed=seed) or "")
            except Exception:  # noqa: BLE001
                trace_id = ""
        self.trace_id = _safe_trace_id(trace_id or _fallback_trace_id(seed))

        get_trace_url = getattr(self._client, "get_trace_url", None)
        if callable(get_trace_url) and self.trace_id:
            try:
                self.trace_url = _safe_langfuse_attribute(
                    get_trace_url(trace_id=self.trace_id),
                    500,
                )
            except Exception:  # noqa: BLE001
                self.trace_url = ""

    def _open_trace_attributes(self) -> None:
        propagate = _load_trace_attribute_propagator()
        if propagate is None:
            return
        kwargs = _trace_attribute_kwargs(
            session_id=self.session_id,
            workspace=self.workspace,
            trace_name=self.trace_name,
            trace_id=self.trace_id,
            trace_url=self.trace_url,
        )
        if not kwargs:
            return
        try:
            self._trace_attributes_cm = propagate(**kwargs)
            enter = getattr(self._trace_attributes_cm, "__enter__", None)
            if callable(enter):
                enter()
        except Exception as exc:  # noqa: BLE001
            self._trace_attributes_cm = None
            self._mark_error(exc, keep_enabled=True)

    def _close_trace_attributes(self, exc_type, exc, tb) -> None:
        if self._trace_attributes_cm is None:
            return
        try:
            self._trace_attributes_cm.__exit__(exc_type, exc, tb)
        except Exception as close_exc:  # noqa: BLE001
            self._mark_error(close_exc, keep_enabled=True)
        finally:
            self._trace_attributes_cm = None

    def _close_root(self, exc_type, exc, tb) -> None:
        if self._root_cm is None:
            return
        try:
            self._root_cm.__exit__(exc_type, exc, tb)
        except Exception as close_exc:  # noqa: BLE001
            self._mark_error(close_exc, keep_enabled=True)
        finally:
            self._root_cm = None

    def _flush(self) -> None:
        if self._client is None:
            return
        try:
            flush = getattr(self._client, "flush", None)
            if callable(flush):
                flush()
        except Exception as exc:  # noqa: BLE001
            self._mark_error(exc, keep_enabled=True)

    def _mark_error(self, exc: Exception, *, keep_enabled: bool = False) -> None:
        self.error = _redact_env_secrets(str(exc))[:500]
        self.status = "error"
        if not keep_enabled:
            self.enabled = False


class _NoopObservationContext:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def update(self, **_kwargs) -> None:
        return None


_ObservationContext = Any


def _default_langfuse_client_factory() -> Any:
    module = importlib.import_module("langfuse")
    get_client = getattr(module, "get_client")
    return get_client()


def _langfuse_enabled() -> bool:
    return os.environ.get("PECKER_LANGFUSE_ENABLED", "").strip().lower() in _TRUE_VALUES


def _langfuse_credentials_present() -> bool:
    return bool(os.environ.get("LANGFUSE_PUBLIC_KEY") and os.environ.get("LANGFUSE_SECRET_KEY"))


def _safe_payload(value: Any, *, prd_body: str = "", depth: int = 0) -> Any:
    if value is None:
        return {}
    if depth > _MAX_DEPTH:
        return _summary_for_value(value)
    if isinstance(value, dict):
        safe: Dict[str, Any] = {}
        for key, item in value.items():
            safe_key = redact_text(str(key))
            if _normal_key(safe_key) in _RAW_PAYLOAD_KEYS:
                safe[safe_key] = _summary_for_value(item)
            else:
                safe[safe_key] = _safe_payload(item, prd_body=prd_body, depth=depth + 1)
        return redact_sensitive(safe)
    if isinstance(value, (list, tuple)):
        items = list(value)
        safe_items = [
            _safe_payload(item, prd_body=prd_body, depth=depth + 1)
            for item in items[:_MAX_LIST_ITEMS]
        ]
        if len(items) > _MAX_LIST_ITEMS:
            safe_items.append({"truncated": len(items) - _MAX_LIST_ITEMS})
        return safe_items
    if isinstance(value, str):
        text = redact_prd_content(value, prd_body) if prd_body else value
        text = redact_text(str(text))
        if len(text) > _MAX_STRING_CHARS:
            return f"{text[:_MAX_STRING_CHARS]}...[truncated {len(text) - _MAX_STRING_CHARS} chars]"
        return text
    return redact_sensitive(value)


def _summary_for_value(value: Any) -> Dict[str, Any]:
    summary: Dict[str, Any] = {"redacted": True}
    if isinstance(value, str):
        summary["chars"] = len(value)
        summary["sha256"] = _hash_text(value)
    elif isinstance(value, dict):
        summary["keys"] = sorted(redact_text(str(key)) for key in value.keys())[:50]
        summary["count"] = len(value)
    elif isinstance(value, (list, tuple)):
        summary["count"] = len(value)
    elif value is not None:
        summary["type"] = type(value).__name__
    return summary


def _normal_key(key: str) -> str:
    return key.strip().lower().replace("-", "_")


def _hash_text(value: str) -> str:
    return hashlib.sha256((value or "").encode("utf-8")).hexdigest()[:16]


def _fallback_trace_id(seed: str) -> str:
    return hashlib.sha256((seed or "pecker.langgraph.review").encode("utf-8")).hexdigest()[:32]


def _safe_trace_id(value: Any) -> str:
    text = str(value or "").strip().lower()
    if len(text) == 32 and all(char in "0123456789abcdef" for char in text):
        return text
    return ""


def _redact_env_secrets(text: str) -> str:
    redacted = redact_text(text)
    for key in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY"):
        secret = os.environ.get(key)
        if secret:
            redacted = redacted.replace(secret, "[REDACTED_SECRET]")
    return redacted


def _load_trace_attribute_propagator() -> Optional[Callable[..., Any]]:
    try:
        langfuse_module = importlib.import_module("langfuse")
    except Exception:  # noqa: BLE001
        return None
    propagator = getattr(langfuse_module, "propagate_attributes", None)
    return propagator if callable(propagator) else None


def _trace_attribute_kwargs(
    *,
    session_id: str,
    workspace: str,
    trace_name: str,
    trace_id: str = "",
    trace_url: str = "",
) -> Dict[str, Any]:
    if not session_id:
        return {}
    metadata = {
        key: value
        for key, value in {
            "workspace": _safe_langfuse_attribute(workspace, 200),
            "trace_id": _safe_trace_id(trace_id),
            "trace_url": _safe_langfuse_attribute(trace_url, 200),
            "orchestrator": "langgraph",
            "environment": _safe_langfuse_attribute(
                os.environ.get("LANGFUSE_TRACING_ENVIRONMENT")
                or os.environ.get("PECKER_ENV")
                or "",
                80,
            ),
        }.items()
        if value
    }
    return {
        "session_id": session_id,
        "trace_name": _safe_langfuse_attribute(trace_name, 160) or "pecker.langgraph.review",
        "metadata": metadata,
        "tags": ["pecker", "langgraph"],
    }


def _langfuse_status_snapshot() -> Dict[str, Any]:
    configured = _langfuse_credentials_present()
    sdk_available = importlib.util.find_spec("langfuse") is not None
    if not configured:
        status = "disabled"
    elif not _langfuse_enabled():
        status = "disabled"
    elif not sdk_available:
        status = "sdk_missing"
    else:
        status = "ready"
    return {
        "configured": configured,
        "enabled": status == "ready",
        "status": status,
        "sdk_available": sdk_available,
    }


def _confirmation_item_score_payloads(
    *,
    review_result: Dict[str, Any],
    decisions: Dict[str, Dict[str, Any]],
    item_map: Dict[str, Dict[str, Any]],
    max_item_scores: int,
) -> list[Dict[str, Any]]:
    payloads: list[Dict[str, Any]] = []
    session_id = _score_session_id(review_result)
    trace_id = _score_trace_id(review_result)
    for item_id, decision in (decisions or {}).items():
        if len(payloads) >= max(0, max_item_scores):
            break
        if not isinstance(decision, dict):
            continue
        action = str(decision.get("action") or "").strip().lower()
        if action not in {"accept", "reject", "edit"}:
            continue
        item = item_map.get(str(item_id))
        if not item:
            continue
        value = 1.0 if action in {"accept", "edit"} else 0.0
        metadata = _confirmation_base_metadata(review_result)
        metadata.update(
            {
                "item_id": _safe_score_text(item_id, 120),
                "rule_id": _safe_score_text(item.get("rule_id"), 120),
                "dimension": _safe_score_text(item.get("dimension"), 120),
                "severity": _safe_score_text(item.get("severity"), 40),
                **_free_text_signal("location", item.get("location")),
                "action": action,
                "reason_category": _safe_score_text(decision.get("reason_category"), 80),
                "correctness_reason": _safe_score_text(decision.get("correctness_reason"), 80),
                "business_decision": _safe_score_text(decision.get("business_decision"), 80),
                **_free_text_signal(
                    "reason_note",
                    decision.get("reason_note") or decision.get("reason"),
                ),
                "source": "review_confirm",
            }
        )
        payloads.append(
            {
                "value": value,
                "score": {
                    "name": "pecker.pm_item_feedback",
                    "value": value,
                    "session_id": session_id,
                    "trace_id": trace_id,
                    "data_type": "NUMERIC",
                    "comment": f"{action}:{metadata.get('reason_category') or metadata.get('business_decision') or 'none'}",
                    "metadata": redact_sensitive(metadata),
                },
            }
        )
    return payloads


def _confirmation_aggregate_score(
    *,
    review_result: Dict[str, Any],
    scored_items: int,
    aggregate_acceptance_rate: float,
) -> Dict[str, Any]:
    metadata = _confirmation_base_metadata(review_result)
    metadata.update(
        {
            "source": "review_confirm",
            "scored_items": scored_items,
        }
    )
    return {
        "name": "pecker.pm_acceptance_rate",
        "value": aggregate_acceptance_rate,
        "session_id": _score_session_id(review_result),
        "trace_id": _score_trace_id(review_result),
        "data_type": "NUMERIC",
        "comment": f"{scored_items} scored PM decisions",
        "metadata": redact_sensitive(metadata),
    }


def _evidence_item_score_payloads(
    *,
    review_result: Dict[str, Any],
    verified_items: list[Dict[str, Any]],
    max_item_scores: int,
) -> list[Dict[str, Any]]:
    payloads: list[Dict[str, Any]] = []
    session_id = _score_session_id(review_result)
    trace_id = _score_trace_id(review_result)
    score_by_status = {
        "verified": 1.0,
        "verified_with_caveat": 0.5,
        "retracted": 0.0,
    }
    for item in verified_items or []:
        if len(payloads) >= max(0, max_item_scores):
            break
        if not isinstance(item, dict):
            continue
        status = _evidence_verification_status(item)
        if status not in score_by_status:
            continue
        reason_code = ""
        details = item.get("verification_details")
        if isinstance(details, dict):
            reason_code = _safe_score_text(details.get("reason_code"), 120)
        metadata = _confirmation_base_metadata(review_result)
        metadata.update(
            {
                "item_id": _safe_score_text(item.get("id"), 120),
                "rule_id": _safe_score_text(item.get("rule_id"), 120),
                "dimension": _safe_score_text(item.get("dimension"), 120),
                "severity": _safe_score_text(item.get("severity"), 40),
                "evidence_type": _safe_score_text(item.get("evidence_type"), 40),
                "verification_status": status,
                "reason_code": reason_code,
                "source": "evidence_verify",
            }
        )
        value = score_by_status[status]
        payloads.append(
            {
                "value": value,
                "score": {
                    "name": "pecker.evidence_item_status",
                    "value": value,
                    "session_id": session_id,
                    "trace_id": trace_id,
                    "data_type": "NUMERIC",
                    "comment": f"{status}:{reason_code or 'none'}",
                    "metadata": redact_sensitive(metadata),
                },
            }
        )
    return payloads


def _evidence_verification_status(item: Dict[str, Any]) -> str:
    status = str(item.get("verification_status") or "").strip().lower()
    if status:
        return status
    legacy_status = str(item.get("status") or "").strip().upper()
    if legacy_status == "RETRACTED":
        return "retracted"
    if legacy_status == "VERIFIED":
        return "verified"
    return ""


def _evidence_aggregate_score(
    *,
    review_result: Dict[str, Any],
    scored_items: int,
    summary: Dict[str, Any],
    reliability: float,
    caveat: int,
    retracted: int,
) -> Dict[str, Any]:
    metadata = _confirmation_base_metadata(review_result)
    metadata.update(
        {
            "source": "evidence_verify",
            "scored_items": scored_items,
            "total": _safe_summary_int(summary, "total"),
            "verified": _safe_summary_int(summary, "verified"),
            "caveat": caveat,
            "retracted": retracted,
        }
    )
    return {
        "name": "pecker.evidence_reliability",
        "value": reliability,
        "session_id": _score_session_id(review_result),
        "trace_id": _score_trace_id(review_result),
        "data_type": "NUMERIC",
        "comment": f"{scored_items} scored evidence checks",
        "metadata": redact_sensitive(metadata),
    }


def _evidence_reliability(summary: Optional[Dict[str, Any]], payloads: list[Dict[str, Any]]) -> float:
    reliability = _safe_summary_float(summary, "reliability", None)
    if reliability is not None:
        return reliability
    if not payloads:
        return 0.0
    value_sum = sum(float(payload.get("value") or 0.0) for payload in payloads)
    return round(value_sum / len(payloads), 3)


def _confirmation_base_metadata(review_result: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "review_id": _safe_score_text(review_result.get("review_id"), 120),
        "reviewer": _safe_score_text(review_result.get("reviewer"), 120),
        "workspace": _safe_score_text(review_result.get("workspace"), 120),
        "prd_name": _safe_score_text(review_result.get("prd_name"), 160),
        "mode": _safe_score_text(review_result.get("mode"), 80),
    }


def _safe_score_text(value: Any, limit: int) -> str:
    return redact_text(str(value or ""))[:limit]


def _free_text_signal(name: str, value: Any) -> Dict[str, Any]:
    text = str(value or "").strip()
    return {
        f"{name}_present": bool(text),
        f"{name}_chars": len(text),
    }


def _safe_summary_int(summary: Optional[Dict[str, Any]], key: str) -> int:
    if not isinstance(summary, dict):
        return 0
    try:
        return int(summary.get(key) or 0)
    except (TypeError, ValueError):
        return 0


def _safe_summary_float(
    summary: Optional[Dict[str, Any]],
    key: str,
    default: Optional[float],
) -> Optional[float]:
    if not isinstance(summary, dict):
        return default
    try:
        value = float(summary.get(key))
    except (TypeError, ValueError):
        return default
    return round(value, 3)


def _safe_langfuse_attribute(value: Any, limit: int) -> str:
    return redact_text(str(value or "").strip())[:limit]


def _score_session_id(review_result: Dict[str, Any]) -> Optional[str]:
    telemetry = review_result.get("telemetry") if isinstance(review_result, dict) else None
    observability = telemetry.get("observability") if isinstance(telemetry, dict) else None
    langfuse = observability.get("langfuse") if isinstance(observability, dict) else None
    session_id = langfuse.get("session_id") if isinstance(langfuse, dict) else None
    safe_session_id = _safe_langfuse_attribute(session_id, 200)
    if safe_session_id:
        return safe_session_id
    review_id = _safe_score_text(review_result.get("review_id"), 120)
    return review_id or None


def _score_trace_id(review_result: Dict[str, Any]) -> Optional[str]:
    telemetry = review_result.get("telemetry") if isinstance(review_result, dict) else None
    observability = telemetry.get("observability") if isinstance(telemetry, dict) else None
    langfuse = observability.get("langfuse") if isinstance(observability, dict) else None
    trace_id = langfuse.get("trace_id") if isinstance(langfuse, dict) else None
    return _safe_trace_id(trace_id) or None


def _score_trace_snapshot(review_result: Dict[str, Any]) -> Dict[str, Any]:
    trace_id = _score_trace_id(review_result)
    if not trace_id:
        return {}
    return {"trace_id": trace_id, "trace_linked": True}


def _client_can_create_score(client: Any) -> bool:
    return _client_can_batch_scores(client) or any(
        callable(getattr(client, name, None))
        for name in ("create_score", "score_current_trace", "score")
    )


def _client_can_batch_scores(client: Any) -> bool:
    api = getattr(client, "api", None)
    ingestion = getattr(api, "ingestion", None)
    return callable(getattr(ingestion, "batch", None))


def _create_langfuse_scores(client: Any, scores: list[Dict[str, Any]]) -> int:
    if not scores:
        return 0
    if _client_can_batch_scores(client):
        _create_langfuse_score_batch(client, scores)
        return len(scores)
    for score in scores:
        _create_langfuse_score(client, **score)
    _flush_client(client)
    return len(scores)


def _create_langfuse_score_batch(client: Any, scores: list[Dict[str, Any]]) -> None:
    batch = [_score_ingestion_event(client, score) for score in scores]
    client.api.ingestion.batch(
        batch=batch,
        metadata={
            "sdk_name": "python",
            "sdk_version": "pecker",
            "public_key": _safe_score_text(os.environ.get("LANGFUSE_PUBLIC_KEY"), 120),
        },
    )


def _score_ingestion_event(client: Any, score: Dict[str, Any]) -> Dict[str, Any]:
    body = {
        "id": score.get("score_id") or _new_langfuse_id(client),
        "name": score.get("name"),
        "value": score.get("value"),
        "sessionId": score.get("session_id"),
        "datasetRunId": score.get("dataset_run_id"),
        "traceId": score.get("trace_id"),
        "observationId": score.get("observation_id"),
        "dataType": score.get("data_type"),
        "comment": score.get("comment"),
        "configId": score.get("config_id"),
        "metadata": score.get("metadata"),
    }
    return {
        "id": _new_langfuse_id(client),
        "type": "score-create",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "body": {key: value for key, value in body.items() if value is not None},
    }


def _new_langfuse_id(client: Any) -> str:
    seed = f"pecker-score:{uuid.uuid4().hex}"
    create_trace_id = getattr(client, "create_trace_id", None)
    if callable(create_trace_id):
        try:
            trace_id = _safe_trace_id(create_trace_id(seed=seed))
            if trace_id:
                return trace_id
        except Exception:
            pass
    return uuid.uuid4().hex


def _create_langfuse_score(client: Any, **kwargs) -> None:
    create_score = getattr(client, "create_score", None)
    if callable(create_score):
        create_score(**kwargs)
        return
    current_trace_score = getattr(client, "score_current_trace", None)
    if callable(current_trace_score):
        current_trace_score(
            name=kwargs.get("name"),
            value=kwargs.get("value"),
            data_type=kwargs.get("data_type"),
            comment=kwargs.get("comment"),
            metadata=kwargs.get("metadata"),
        )
        return
    legacy_score = getattr(client, "score", None)
    if callable(legacy_score):
        legacy_score(**kwargs)


def _flush_client(client: Any) -> None:
    flush = getattr(client, "flush", None)
    if callable(flush):
        flush()
