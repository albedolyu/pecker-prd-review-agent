"""Safe Langfuse payload helpers for Pecker A/B experiments."""
from __future__ import annotations

import math
import re
from statistics import median
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
    baseline_fp_ids = _false_positive_item_ids(baseline.get("goshawk_result"))
    candidate_fp_ids = _false_positive_item_ids(candidate.get("goshawk_result"))
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
        "advisor_fp_jaccard": _jaccard(baseline_fp_ids, candidate_fp_ids),
        "false_positive_delta": len(candidate_fp_ids) - len(baseline_fp_ids),
    }
    metrics["compact_pass"] = (
        metrics["final_signature_jaccard"] >= pass_signature_threshold
        and abs(metrics["final_item_delta_ratio"]) <= pass_item_delta_threshold
        and metrics["false_positive_delta"] <= 0
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
        ("pecker.goshawk_ab.advisor_fp_jaccard", metrics.get("advisor_fp_jaccard")),
        ("pecker.goshawk_ab.false_positive_delta", metrics.get("false_positive_delta")),
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


def build_goshawk_ab_suite_score_payloads(
    suite: Mapping[str, Any],
    *,
    trace_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> list[Dict[str, Any]]:
    """Create Langfuse score payloads from a suite-level A/B summary."""

    summary = dict(suite.get("summary") or {})
    recommendation = dict(suite.get("recommendation") or {})
    failures = list(suite.get("failures") or [])
    metadata = {
        "ab_kind": "goshawk_ab_suite",
        "recommendation_action": _safe_text(recommendation.get("action"), 80),
        "recommendation_reason": _safe_text(recommendation.get("reason"), 160),
        "run_count": _safe_int(summary.get("run_count")),
        "failure_count": len(failures),
    }
    failure_batch_ids = [
        _safe_text(failure.get("batch_id"), 160)
        for failure in failures
        if isinstance(failure, Mapping) and _safe_text(failure.get("batch_id"), 160)
    ]
    if failure_batch_ids:
        metadata["failure_batch_ids"] = failure_batch_ids[:20]

    target = _score_target(trace_id=trace_id, session_id=session_id)
    action = metadata["recommendation_action"]
    scores: list[Dict[str, Any]] = []
    for name, value in (
        ("pecker.goshawk_ab_suite.compact_pass_rate", summary.get("compact_pass_rate")),
        (
            "pecker.goshawk_ab_suite.median_input_token_savings_ratio",
            summary.get("median_input_token_savings_ratio"),
        ),
        (
            "pecker.goshawk_ab_suite.median_elapsed_savings_ratio",
            summary.get("median_elapsed_savings_ratio"),
        ),
        ("pecker.goshawk_ab_suite.min_final_rule_jaccard", summary.get("min_final_rule_jaccard")),
        (
            "pecker.goshawk_ab_suite.min_final_signature_jaccard",
            summary.get("min_final_signature_jaccard"),
        ),
        (
            "pecker.goshawk_ab_suite.max_false_positive_delta",
            summary.get("max_false_positive_delta"),
        ),
        ("pecker.goshawk_ab_suite.keep_disabled", 1.0 if action == "keep_disabled" else 0.0),
        ("pecker.goshawk_ab_suite.canary_ready", 1.0 if action == "canary_only" else 0.0),
    ):
        scores.append(_score(name=name, value=_safe_float(value), metadata=metadata, target=target))
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


def record_goshawk_ab_suite_scores(
    suite: Mapping[str, Any],
    *,
    trace_id: Optional[str] = None,
    session_id: Optional[str] = None,
    client_factory=None,
) -> Dict[str, Any]:
    """Write suite-level A/B scores to Langfuse when explicitly requested."""

    try:
        from review.langfuse_observability import (
            _client_can_create_score,
            _create_langfuse_scores,
            _default_langfuse_client_factory,
            start_langgraph_review_trace,
        )

        active_trace_id = _safe_trace_id(trace_id)
        trace_snapshot: Dict[str, Any] = {}
        if not active_trace_id and _safe_text(session_id, 200):
            with start_langgraph_review_trace(
                workspace="goshawk_ab_suite",
                thread_id=_safe_text(session_id, 200),
                prd_content="",
                wiki_pages={},
                voting_rounds=1,
                dimensions=["goshawk_ab_suite"],
                client_factory=client_factory,
                trace_name="pecker.goshawk_ab.suite",
            ) as trace:
                trace.finish(
                    status="done",
                    output={
                        "summary": dict(suite.get("summary") or {}),
                        "recommendation": dict(suite.get("recommendation") or {}),
                        "failure_count": len(list(suite.get("failures") or [])),
                    },
                )
                trace_snapshot = trace.snapshot()
                active_trace_id = _safe_trace_id(trace_snapshot.get("trace_id"))

        scores = build_goshawk_ab_suite_score_payloads(
            suite,
            trace_id=active_trace_id,
            session_id=session_id if not active_trace_id else None,
        )
        client = (client_factory or _default_langfuse_client_factory)()
        if not _client_can_create_score(client):
            return {"status": "score_api_missing", "scores_sent": 0}
        sent = _create_langfuse_scores(client, scores)
        result: Dict[str, Any] = {
            "status": "recorded",
            "scores_sent": sent,
            "target": "trace" if active_trace_id else "session",
        }
        if trace_snapshot:
            result["trace"] = trace_snapshot
        return result
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "scores_sent": 0, "error": _safe_text(str(exc), 500)}


def summarize_goshawk_ab_suite(
    reports: Iterable[Mapping[str, Any]],
    *,
    min_runs_for_canary: int = 5,
    signature_threshold: float = 0.9,
    rule_threshold: float = 0.9,
) -> Dict[str, Any]:
    """Summarize multiple A/B report payloads into an enablement decision."""

    rows = []
    failures = []
    for report in reports or []:
        if not isinstance(report, Mapping):
            continue
        batch_id = _safe_text(report.get("batch_id"), 160)
        metrics = _report_metrics(report)
        if not metrics:
            continue
        row = {
            "batch_id": batch_id,
            "compact_pass": bool(metrics.get("compact_pass")),
            "input_token_savings_ratio": _safe_float(metrics.get("input_token_savings_ratio")),
            "elapsed_savings_ratio": _safe_float(metrics.get("elapsed_savings_ratio")),
            "final_rule_jaccard": _safe_float(metrics.get("final_rule_jaccard")),
            "final_signature_jaccard": _safe_float(metrics.get("final_signature_jaccard")),
            "advisor_fp_jaccard": _safe_float(metrics.get("advisor_fp_jaccard")),
            "false_positive_delta": _safe_float(metrics.get("false_positive_delta")),
        }
        rows.append(row)
        reasons = _suite_failure_reasons(
            row,
            signature_threshold=signature_threshold,
            rule_threshold=rule_threshold,
        )
        if reasons:
            failures.append(
                {
                    "batch_id": batch_id,
                    "reasons": reasons,
                    "metrics": row,
                }
            )

    run_count = len(rows)
    pass_count = sum(1 for row in rows if row["compact_pass"])
    summary = {
        "run_count": run_count,
        "compact_pass_count": pass_count,
        "compact_pass_rate": _safe_div(pass_count, run_count),
        "median_input_token_savings_ratio": _median(rows, "input_token_savings_ratio"),
        "median_elapsed_savings_ratio": _median(rows, "elapsed_savings_ratio"),
        "median_final_rule_jaccard": _median(rows, "final_rule_jaccard"),
        "min_final_rule_jaccard": _minimum(rows, "final_rule_jaccard"),
        "median_final_signature_jaccard": _median(rows, "final_signature_jaccard"),
        "min_final_signature_jaccard": _minimum(rows, "final_signature_jaccard"),
        "median_advisor_fp_jaccard": _median(rows, "advisor_fp_jaccard"),
        "max_false_positive_delta": _maximum(rows, "false_positive_delta"),
    }
    return {
        "summary": summary,
        "recommendation": _suite_recommendation(
            summary,
            failures,
            min_runs_for_canary=min_runs_for_canary,
        ),
        "failures": failures,
        "runs": rows,
    }


def _run_summary(run: Mapping[str, Any], *, default_variant: str) -> Dict[str, Any]:
    items = _items(run)
    usage = _usage(run)
    advisor = dict(run.get("goshawk_result") or {})
    fp_ids = _false_positive_item_ids(advisor)
    summary = {
        "variant": _safe_text(run.get("variant") or default_variant, 80),
        "elapsed_s": _safe_float(run.get("elapsed_s")),
        "usage": usage,
        "items_count": len(items),
        "rule_ids_count": len(_rule_ids(items)),
        "advisor": {
            "false_positive_count": len(advisor.get("flagged_as_false_positive") or []),
            "false_positive_item_ids": sorted(fp_ids),
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


def _report_metrics(report: Mapping[str, Any]) -> Dict[str, Any]:
    if isinstance(report.get("metrics"), Mapping):
        return dict(report.get("metrics") or {})
    ab = report.get("ab")
    if isinstance(ab, Mapping) and isinstance(ab.get("metrics"), Mapping):
        return dict(ab.get("metrics") or {})
    return {}


def _suite_failure_reasons(
    row: Mapping[str, Any],
    *,
    signature_threshold: float,
    rule_threshold: float,
) -> list[str]:
    reasons = []
    if not row.get("compact_pass"):
        reasons.append("compact_pass_false")
    if _safe_float(row.get("final_signature_jaccard")) < signature_threshold:
        reasons.append("signature_below_threshold")
    if _safe_float(row.get("final_rule_jaccard")) < rule_threshold:
        reasons.append("rule_below_threshold")
    if _safe_float(row.get("false_positive_delta")) > 0:
        reasons.append("false_positive_delta_positive")
    return reasons


def _suite_recommendation(
    summary: Mapping[str, Any],
    failures: list[Mapping[str, Any]],
    *,
    min_runs_for_canary: int,
) -> Dict[str, Any]:
    if failures:
        return {
            "action": "keep_disabled",
            "reason": "one_or_more_ab_runs_failed_quality_gate",
        }
    if int(summary.get("run_count") or 0) < max(1, int(min_runs_for_canary or 1)):
        return {
            "action": "collect_more_samples",
            "reason": "not_enough_ab_runs_for_canary_decision",
        }
    return {
        "action": "canary_only",
        "reason": "quality_gate_passed_but_keep_default_off_until_canary",
    }


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
        return target
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


def _false_positive_item_ids(advisor_result: Any) -> set[str]:
    if not isinstance(advisor_result, Mapping):
        return set()
    ids = set()
    for item in advisor_result.get("flagged_as_false_positive") or []:
        if not isinstance(item, Mapping):
            continue
        item_id = _normalize(item.get("item_id"))
        if item_id:
            ids.add(item_id)
    return ids


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


def _median(rows: list[Mapping[str, Any]], key: str) -> float:
    values = [_safe_float(row.get(key)) for row in rows]
    return float(median(values)) if values else 0.0


def _minimum(rows: list[Mapping[str, Any]], key: str) -> float:
    values = [_safe_float(row.get(key)) for row in rows]
    return min(values) if values else 0.0


def _maximum(rows: list[Mapping[str, Any]], key: str) -> float:
    values = [_safe_float(row.get(key)) for row in rows]
    return max(values) if values else 0.0


def _safe_div(numerator: float, denominator: float) -> float:
    return _safe_float(numerator) / _safe_float(denominator) if _safe_float(denominator) > 0 else 0.0


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
