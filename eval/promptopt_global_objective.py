from __future__ import annotations

import hashlib
import math
import re
from statistics import mean
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence


DEFAULT_THRESHOLDS: Dict[str, float] = {
    "min_cases": 3,
    "min_global_score": 0.70,
    "min_mean_signature_jaccard": 0.70,
    "min_case_signature_jaccard": 0.55,
    "max_mean_false_positive_rate": 0.30,
    "max_case_false_positive_rate": 0.30,
    "max_mean_final_item_delta_ratio": 0.35,
    "min_case_final_item_ratio": 0.60,
    "min_scenario_signature_jaccard": 0.65,
}


def score_promptopt_suite(
    cases: Sequence[Mapping[str, Any]],
    *,
    prompt_variant: str,
    batch_id: str,
    thresholds: Optional[Mapping[str, float]] = None,
) -> Dict[str, Any]:
    active_thresholds = {**DEFAULT_THRESHOLDS, **dict(thresholds or {})}
    case_scores = [_score_case(case) for case in cases]
    summary = _summarize_cases(case_scores)
    global_score = _global_score(summary)
    fail_reasons = _fail_reasons(case_scores, summary, global_score, active_thresholds)

    return {
        "pass": not fail_reasons,
        "global_score": round(global_score, 4),
        "summary": summary,
        "cases": case_scores,
        "thresholds": active_thresholds,
        "fail_reasons": fail_reasons,
        "metadata": {
            "batch_id": str(batch_id or ""),
            "prompt_variant": str(prompt_variant or ""),
        },
    }


def build_langfuse_score_payloads(
    result: Mapping[str, Any],
    *,
    trace_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    metadata = dict(result.get("metadata") or {})
    summary = dict(result.get("summary") or {})
    scores: List[Dict[str, Any]] = []

    def add(name: str, value: Any, *, extra_metadata: Optional[Mapping[str, Any]] = None) -> None:
        score_metadata = {**metadata, **dict(extra_metadata or {})}
        payload: Dict[str, Any] = {
            "name": name,
            "value": _numeric(value),
            "data_type": "NUMERIC",
            "comment": "Pecker prompt optimization global objective",
            "metadata": score_metadata,
        }
        if trace_id:
            payload["trace_id"] = trace_id
        if session_id:
            payload["session_id"] = session_id
        scores.append(payload)

    add("pecker.promptopt.global_score", result.get("global_score", 0.0))
    add("pecker.promptopt.global.pass", 1.0 if result.get("pass") else 0.0)
    for key in (
        "case_count",
        "mean_signature_jaccard",
        "min_signature_jaccard",
        "mean_input_token_savings_ratio",
        "mean_elapsed_savings_ratio",
        "mean_false_positive_rate",
        "max_false_positive_rate",
        "mean_final_item_delta_ratio",
    ):
        add(f"pecker.promptopt.global.{key}", summary.get(key, 0.0))

    for case in result.get("cases") or []:
        case_metadata = {
            "case_id": case.get("case_id"),
            "scenario": case.get("scenario"),
            "baseline_final_items": case.get("baseline_final_items"),
            "candidate_final_items": case.get("candidate_final_items"),
        }
        add(
            "pecker.promptopt.case.signature_jaccard",
            case.get("signature_jaccard", 0.0),
            extra_metadata=case_metadata,
        )
        add(
            "pecker.promptopt.case.false_positive_rate",
            case.get("false_positive_rate", 0.0),
            extra_metadata=case_metadata,
        )
        add(
            "pecker.promptopt.case.final_item_delta_ratio",
            case.get("final_item_delta_ratio", 0.0),
            extra_metadata=case_metadata,
        )

    for scenario, row in (summary.get("by_scenario") or {}).items():
        scenario_metadata = {"scenario": scenario}
        add(
            "pecker.promptopt.scenario.mean_signature_jaccard",
            row.get("mean_signature_jaccard", 0.0),
            extra_metadata=scenario_metadata,
        )
        add(
            "pecker.promptopt.scenario.mean_false_positive_rate",
            row.get("mean_false_positive_rate", 0.0),
            extra_metadata=scenario_metadata,
        )

    return scores


def _score_case(case: Mapping[str, Any]) -> Dict[str, Any]:
    baseline = _as_mapping(case.get("baseline"))
    candidate = _as_mapping(case.get("candidate"))
    baseline_items = _extract_items(baseline)
    candidate_items = _extract_items(candidate)
    baseline_final_items = _final_items_count(baseline, baseline_items)
    candidate_final_items = _final_items_count(candidate, candidate_items)
    candidate_fp_count = _false_positive_count(candidate)

    baseline_signatures = {_item_signature(item) for item in baseline_items}
    candidate_signatures = {_item_signature(item) for item in candidate_items}
    signature_jaccard = _jaccard(baseline_signatures, candidate_signatures)

    baseline_input = _usage_value(baseline, "input_tokens")
    candidate_input = _usage_value(candidate, "input_tokens")
    baseline_elapsed = _float_value(baseline.get("elapsed_s"))
    candidate_elapsed = _float_value(candidate.get("elapsed_s"))

    final_item_delta_ratio = (
        abs(candidate_final_items - baseline_final_items) / max(1, baseline_final_items)
    )
    final_item_ratio = (
        candidate_final_items / baseline_final_items if baseline_final_items > 0 else 1.0
    )

    return {
        "case_id": str(case.get("case_id") or case.get("id") or "unknown"),
        "scenario": _scenario(case),
        "signature_jaccard": round(signature_jaccard, 4),
        "input_token_savings_ratio": round(_savings_ratio(baseline_input, candidate_input), 4),
        "elapsed_savings_ratio": round(_savings_ratio(baseline_elapsed, candidate_elapsed), 4),
        "false_positive_count": candidate_fp_count,
        "false_positive_rate": round(candidate_fp_count / max(1, candidate_final_items), 4),
        "false_positive_allowed": _allowed_false_positives(candidate_final_items),
        "baseline_final_items": baseline_final_items,
        "candidate_final_items": candidate_final_items,
        "final_item_delta_ratio": round(final_item_delta_ratio, 4),
        "final_item_ratio": round(final_item_ratio, 4),
    }


def _summarize_cases(case_scores: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    if not case_scores:
        return {
            "case_count": 0,
            "scenario_count": 0,
            "by_scenario": {},
            "mean_signature_jaccard": 0.0,
            "min_signature_jaccard": 0.0,
            "mean_input_token_savings_ratio": 0.0,
            "mean_elapsed_savings_ratio": 0.0,
            "mean_false_positive_rate": 0.0,
            "max_false_positive_rate": 0.0,
            "mean_final_item_delta_ratio": 0.0,
        }

    by_scenario = _summarize_by_scenario(case_scores)
    return {
        "case_count": len(case_scores),
        "scenario_count": len(by_scenario),
        "by_scenario": by_scenario,
        "mean_signature_jaccard": _mean(case_scores, "signature_jaccard"),
        "min_signature_jaccard": round(min(_float_value(c.get("signature_jaccard")) for c in case_scores), 4),
        "mean_input_token_savings_ratio": _mean(case_scores, "input_token_savings_ratio"),
        "mean_elapsed_savings_ratio": _mean(case_scores, "elapsed_savings_ratio"),
        "mean_false_positive_rate": _mean(case_scores, "false_positive_rate"),
        "max_false_positive_rate": round(max(_float_value(c.get("false_positive_rate")) for c in case_scores), 4),
        "mean_final_item_delta_ratio": _mean(case_scores, "final_item_delta_ratio"),
    }


def _global_score(summary: Mapping[str, Any]) -> float:
    stability = _clamp(_float_value(summary.get("mean_signature_jaccard")))
    coverage = 1.0 - _clamp(
        _float_value(summary.get("mean_final_item_delta_ratio"))
        / DEFAULT_THRESHOLDS["max_mean_final_item_delta_ratio"]
    )
    fp_control = 1.0 - _clamp(
        _float_value(summary.get("mean_false_positive_rate"))
        / DEFAULT_THRESHOLDS["max_mean_false_positive_rate"]
    )
    token_efficiency = _clamp((_float_value(summary.get("mean_input_token_savings_ratio")) + 0.05) / 0.20)
    latency_efficiency = _clamp((_float_value(summary.get("mean_elapsed_savings_ratio")) + 0.05) / 0.20)
    return (
        0.45 * stability
        + 0.20 * coverage
        + 0.15 * fp_control
        + 0.10 * token_efficiency
        + 0.10 * latency_efficiency
    )


def _fail_reasons(
    case_scores: Sequence[Mapping[str, Any]],
    summary: Mapping[str, Any],
    global_score: float,
    thresholds: Mapping[str, float],
) -> List[str]:
    reasons: List[str] = []
    if len(case_scores) < int(thresholds["min_cases"]):
        reasons.append(
            f"case_count {len(case_scores)} < min_cases {int(thresholds['min_cases'])}"
        )
    if global_score < thresholds["min_global_score"]:
        reasons.append(
            f"global_score {global_score:.4f} < min_global_score {thresholds['min_global_score']:.4f}"
        )
    if summary.get("mean_signature_jaccard", 0.0) < thresholds["min_mean_signature_jaccard"]:
        reasons.append(
            "mean_signature_jaccard "
            f"{summary.get('mean_signature_jaccard', 0.0):.4f} "
            f"< {thresholds['min_mean_signature_jaccard']:.4f}"
        )
    if summary.get("mean_false_positive_rate", 0.0) > thresholds["max_mean_false_positive_rate"]:
        reasons.append(
            "mean_false_positive_rate "
            f"{summary.get('mean_false_positive_rate', 0.0):.4f} "
            f"> {thresholds['max_mean_false_positive_rate']:.4f}"
        )
    if summary.get("mean_final_item_delta_ratio", 0.0) > thresholds["max_mean_final_item_delta_ratio"]:
        reasons.append(
            "mean_final_item_delta_ratio "
            f"{summary.get('mean_final_item_delta_ratio', 0.0):.4f} "
            f"> {thresholds['max_mean_final_item_delta_ratio']:.4f}"
        )
    for scenario, row in (summary.get("by_scenario") or {}).items():
        if row.get("mean_signature_jaccard", 0.0) < thresholds["min_scenario_signature_jaccard"]:
            reasons.append(
                f"scenario {scenario} mean_signature_jaccard "
                f"{row.get('mean_signature_jaccard', 0.0):.4f} "
                f"< {thresholds['min_scenario_signature_jaccard']:.4f}"
            )

    for case in case_scores:
        case_id = case.get("case_id", "unknown")
        if case.get("signature_jaccard", 0.0) < thresholds["min_case_signature_jaccard"]:
            reasons.append(
                f"case {case_id} signature_jaccard "
                f"{case.get('signature_jaccard', 0.0):.4f} "
                f"< {thresholds['min_case_signature_jaccard']:.4f}"
            )
        if case.get("final_item_ratio", 1.0) < thresholds["min_case_final_item_ratio"]:
            reasons.append(
                f"case {case_id} final_item_ratio "
                f"{case.get('final_item_ratio', 0.0):.4f} "
                f"< {thresholds['min_case_final_item_ratio']:.4f}"
            )
        if case.get("false_positive_count", 0) > case.get("false_positive_allowed", 0):
            reasons.append(
                f"case {case_id} false_positive_rate "
                f"{case.get('false_positive_rate', 0.0):.4f} exceeds budget "
                f"{case.get('false_positive_allowed', 0)}/{case.get('candidate_final_items', 0)}"
            )
    return reasons


def _summarize_by_scenario(case_scores: Sequence[Mapping[str, Any]]) -> Dict[str, Dict[str, Any]]:
    grouped: Dict[str, List[Mapping[str, Any]]] = {}
    for case in case_scores:
        grouped.setdefault(str(case.get("scenario") or "default"), []).append(case)
    return {
        scenario: {
            "case_count": len(rows),
            "mean_signature_jaccard": _mean(rows, "signature_jaccard"),
            "mean_false_positive_rate": _mean(rows, "false_positive_rate"),
            "mean_final_item_delta_ratio": _mean(rows, "final_item_delta_ratio"),
        }
        for scenario, rows in sorted(grouped.items())
    }


def _extract_items(result: Mapping[str, Any]) -> List[Mapping[str, Any]]:
    items = result.get("items")
    if isinstance(items, list):
        return [item for item in items if isinstance(item, Mapping)]
    output = result.get("output")
    if isinstance(output, Mapping) and isinstance(output.get("items"), list):
        return [item for item in output["items"] if isinstance(item, Mapping)]
    return []


def _item_signature(item: Mapping[str, Any]) -> str:
    parts = [
        _normalize_text(item.get("rule_id")),
        _normalize_text(item.get("location")),
        _normalize_text(item.get("issue") or item.get("problem") or item.get("title"))[:120],
    ]
    if not any(parts):
        parts = [_normalize_text(item.get("id"))]
    raw = "::".join(parts)
    return hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()[:16]


def _jaccard(left: Iterable[str], right: Iterable[str]) -> float:
    left_set = set(left)
    right_set = set(right)
    if not left_set and not right_set:
        return 1.0
    union = left_set | right_set
    if not union:
        return 0.0
    return len(left_set & right_set) / len(union)


def _allowed_false_positives(final_items: int) -> int:
    return max(1, math.ceil(max(0, final_items) * DEFAULT_THRESHOLDS["max_case_false_positive_rate"]))


def _false_positive_count(result: Mapping[str, Any]) -> int:
    value = result.get("false_positive")
    if value is None:
        value = result.get("false_positive_count")
    if value is None:
        fps = result.get("flagged_as_false_positive")
        if isinstance(fps, list):
            return len(fps)
        return 0
    return max(0, int(_float_value(value)))


def _final_items_count(result: Mapping[str, Any], items: Sequence[Mapping[str, Any]]) -> int:
    for key in ("final_items", "final_item_count", "item_count"):
        if key in result:
            return max(0, int(_float_value(result.get(key))))
    return len(items)


def _usage_value(result: Mapping[str, Any], key: str) -> float:
    usage = result.get("usage")
    if isinstance(usage, Mapping):
        return _float_value(usage.get(key))
    return _float_value(result.get(key))


def _savings_ratio(baseline: float, candidate: float) -> float:
    if baseline <= 0:
        return 0.0
    return (baseline - candidate) / baseline


def _mean(rows: Sequence[Mapping[str, Any]], key: str) -> float:
    return round(mean(_float_value(row.get(key)) for row in rows), 4)


def _numeric(value: Any) -> float:
    return round(_float_value(value), 6)


def _float_value(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _scenario(case: Mapping[str, Any]) -> str:
    value = case.get("scenario") or case.get("domain") or case.get("workspace") or "default"
    return _normalize_text(value)[:80] or "default"


def _normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))
