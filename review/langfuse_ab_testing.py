"""Safe Langfuse payload helpers for Pecker A/B experiments."""
from __future__ import annotations

import math
import re
from typing import Any, Dict, Iterable, Mapping, Optional

from api.sanitize import redact_sensitive


_TRACE_ID_RE = re.compile(r"^[0-9a-f]{32}$")


def compare_goshawk_ab_runs(
    *,
    batch_id: str,
    case_id: str,
    baseline: Mapping[str, Any],
    candidate: Mapping[str, Any],
    source_items_count: int,
    pass_signature_threshold: float = 0.9,
    pass_item_delta_threshold: float = 0.25,
) -> Dict[str, Any]:
    """Build a compact, raw-content-free summary for final-only Goshawk A/B."""

    baseline_items = _items(baseline)
    candidate_items = _items(candidate)
    baseline_usage = _usage(baseline)
    candidate_usage = _usage(candidate)
    metrics = {
        "elapsed_savings_ratio": _savings_ratio(
            _safe_float(baseline.get("elapsed_s")),
            _safe_float(candidate.get("elapsed_s")),
        ),
        "input_token_savings_ratio": _savings_ratio(
            baseline_usage["input_tokens"],
            candidate_usage["input_tokens"],
        ),
        "output_token_delta_ratio": _delta_ratio(
            candidate_usage["output_tokens"],
            baseline_usage["output_tokens"],
        ),
        "final_item_delta_ratio": _delta_ratio(len(candidate_items), len(baseline_items)),
        "final_rule_jaccard": _jaccard(_rule_ids(baseline_items), _rule_ids(candidate_items)),
        "final_signature_jaccard": _jaccard(
            _item_signatures(baseline_items),
            _item_signatures(candidate_items),
        ),
    }
    metrics["compact_pass"] = (
        metrics["final_signature_jaccard"] >= pass_signature_threshold
        and abs(metrics["final_item_delta_ratio"]) <= pass_item_delta_threshold
    )
    metadata = {
        "ab_kind": "goshawk_final_only",
        "batch_id": _safe_text(batch_id, 160),
        "case_id": _safe_text(case_id, 160),
        "baseline_variant": _safe_text(baseline.get("variant") or "full", 80),
        "candidate_variant": _safe_text(candidate.get("variant") or "compact", 80),
        "source_items_count": max(0, int(source_items_count or 0)),
    }
    return {
        "metadata": redact_sensitive(metadata),
        "baseline": _run_summary(baseline, default_variant="full"),
        "candidate": _run_summary(candidate, default_variant="compact"),
        "metrics": metrics,
    }


def build_goshawk_ab_score_payloads(
    summary: Mapping[str, Any],
    *,
    trace_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> list[Dict[str, Any]]:
    """Create Langfuse score payloads from an A/B summary."""

    metadata = dict(summary.get("metadata") or {})
    metrics = dict(summary.get("metrics") or {})
    target = _score_target(trace_id=trace_id, session_id=session_id)
    scores: list[Dict[str, Any]] = []

    for name, value in (
        ("pecker.goshawk_ab.final_rule_jaccard", metrics.get("final_rule_jaccard")),
        ("pecker.goshawk_ab.final_signature_jaccard", metrics.get("final_signature_jaccard")),
        ("pecker.goshawk_ab.input_token_savings_ratio", metrics.get("input_token_savings_ratio")),
        ("pecker.goshawk_ab.elapsed_savings_ratio", metrics.get("elapsed_savings_ratio")),
        ("pecker.goshawk_ab.final_item_delta_ratio", metrics.get("final_item_delta_ratio")),
        ("pecker.goshawk_ab.compact_pass", 1.0 if metrics.get("compact_pass") else 0.0),
    ):
        scores.append(_score(name=name, value=_safe_float(value), metadata=metadata, target=target))

    for run_key in ("baseline", "candidate"):
        run = dict(summary.get(run_key) or {})
        variant = _safe_text(run.get("variant") or run_key, 80)
        run_metadata = {**metadata, "variant": variant, "summary_role": run_key}
        usage = dict(run.get("usage") or {})
        for name, value in (
            ("pecker.goshawk_ab.variant_elapsed_s", run.get("elapsed_s")),
            ("pecker.goshawk_ab.variant_input_tokens", usage.get("input_tokens")),
            ("pecker.goshawk_ab.variant_items_count", run.get("items_count")),
        ):
            scores.append(
                _score(
                    name=name,
                    value=_safe_float(value),
                    metadata=run_metadata,
                    target=target,
                )
            )
    return scores


def record_goshawk_ab_scores(
    summary: Mapping[str, Any],
    *,
    trace_id: Optional[str] = None,
    session_id: Optional[str] = None,
    client_factory=None,
) -> Dict[str, Any]:
    """Write A/B scores to Langfuse when explicitly requested by a script."""

    scores = build_goshawk_ab_score_payloads(
        summary,
        trace_id=trace_id,
        session_id=session_id,
    )
    try:
        from review.langfuse_observability import (
            _client_can_create_score,
            _create_langfuse_scores,
            _default_langfuse_client_factory,
        )

        client = (client_factory or _default_langfuse_client_factory)()
        if not _client_can_create_score(client):
            return {"status": "score_api_missing", "scores_sent": 0}
        sent = _create_langfuse_scores(client, scores)
        return {"status": "recorded", "scores_sent": sent}
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "scores_sent": 0, "error": _safe_text(str(exc), 500)}


def _run_summary(run: Mapping[str, Any], *, default_variant: str) -> Dict[str, Any]:
    items = _items(run)
    usage = _usage(run)
    advisor = dict(run.get("goshawk_result") or {})
    summary = {
        "variant": _safe_text(run.get("variant") or default_variant, 80),
        "elapsed_s": _safe_float(run.get("elapsed_s")),
        "usage": usage,
        "items_count": len(items),
        "rule_ids_count": len(_rule_ids(items)),
        "advisor": {
            "false_positive_count": len(advisor.get("flagged_as_false_positive") or []),
            "additional_count": len(advisor.get("additional_findings") or []),
            "conflict_count": len(advisor.get("conflict_resolutions") or []),
            "verdict": _safe_text(advisor.get("verdict"), 80),
            "model_used": _safe_text(advisor.get("model_used"), 120),
        },
    }
    compaction = _safe_compaction(run.get("compaction"))
    if compaction:
        summary["compaction"] = compaction
    trace = _safe_trace_snapshot(run.get("trace"))
    if trace:
        summary["trace"] = trace
    return redact_sensitive(summary)


def _score(
    *,
    name: str,
    value: float,
    metadata: Mapping[str, Any],
    target: Mapping[str, str],
) -> Dict[str, Any]:
    return {
        "name": name,
        "value": value,
        **target,
        "data_type": "NUMERIC",
        "comment": _safe_text(metadata.get("batch_id") or "goshawk_ab", 200),
        "metadata": redact_sensitive(dict(metadata)),
    }


def _score_target(*, trace_id: Optional[str], session_id: Optional[str]) -> Dict[str, str]:
    target: Dict[str, str] = {}
    safe_trace = _safe_trace_id(trace_id)
    if safe_trace:
        target["trace_id"] = safe_trace
    safe_session = _safe_text(session_id, 200)
    if safe_session:
        target["session_id"] = safe_session
    return target


def _safe_trace_snapshot(value: Any) -> Dict[str, str]:
    if not isinstance(value, Mapping):
        return {}
    trace_id = _safe_trace_id(value.get("trace_id"))
    if not trace_id:
        return {}
    snapshot = {"trace_id": trace_id}
    trace_url = str(value.get("trace_url") or "")
    if trace_url.startswith(("https://", "http://")):
        snapshot["trace_url"] = trace_url[:500]
    return snapshot


def _safe_trace_id(value: Any) -> str:
    text = str(value or "").strip().lower()
    return text if _TRACE_ID_RE.match(text) else ""


def _safe_compaction(value: Any) -> Dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    allowed = {
        "enabled": bool(value.get("enabled")),
        "budget_chars": _safe_int(value.get("budget_chars") or value.get("budget")),
        "selected_count": _safe_int(value.get("selected_count")),
        "worker_union_count": _safe_int(value.get("worker_union_count")),
    }
    return {key: val for key, val in allowed.items() if val not in (None, "")}


def _usage(run: Mapping[str, Any]) -> Dict[str, int]:
    usage = run.get("usage") if isinstance(run.get("usage"), Mapping) else {}
    return {
        "input_tokens": _safe_int(usage.get("input_tokens")),
        "output_tokens": _safe_int(usage.get("output_tokens")),
    }


def _items(run: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    items = run.get("items") or []
    return [item for item in items if isinstance(item, Mapping)]


def _rule_ids(items: Iterable[Mapping[str, Any]]) -> set[str]:
    return {
        _normalize(item.get("rule_id"))
        for item in items
        if _normalize(item.get("rule_id"))
    }


def _item_signatures(items: Iterable[Mapping[str, Any]]) -> set[str]:
    signatures = set()
    for item in items:
        parts = [
            _normalize(item.get("rule_id")),
            _normalize(item.get("location")),
            _normalize(item.get("issue") or item.get("title") or item.get("summary")),
        ]
        signature = "|".join(parts)
        if signature.strip("|"):
            signatures.add(signature)
    return signatures


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left and not right:
        return 1.0
    union = left | right
    if not union:
        return 0.0
    return len(left & right) / len(union)


def _savings_ratio(baseline: float, candidate: float) -> float:
    if baseline <= 0:
        return 0.0
    return (baseline - candidate) / baseline


def _delta_ratio(value: float, baseline: float) -> float:
    if baseline <= 0:
        return 0.0
    return (value - baseline) / baseline


def _safe_float(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(number):
        return 0.0
    return number


def _safe_int(value: Any) -> int:
    try:
        return max(0, int(float(value or 0)))
    except (TypeError, ValueError):
        return 0


def _normalize(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _safe_text(value: Any, limit: int) -> str:
    return str(value or "").strip()[: max(0, int(limit))]

