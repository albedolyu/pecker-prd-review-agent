"""Infer downstream code-change signals for review findings.

This module treats source-code diffs as weak feedback. It does not claim that a
finding is correct; it only reports whether later implementation changes look
related enough to be useful as an adoption signal.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional

from api.sanitize import redact_text


_WORD_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9_]{2,}|[\u4e00-\u9fff]{2,}")
_DIFF_FILE_RE = re.compile(r"^diff --git a/(.*?) b/(.*?)\s*$")
_TRACE_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_NOISE_WORDS = {
    "add",
    "and",
    "api",
    "class",
    "def",
    "does",
    "for",
    "missing",
    "not",
    "prd",
    "required",
    "test",
    "the",
    "with",
}

_DIMENSION_EXPECTED_TYPES = {
    "acceptance": {"test_added", "validation_added"},
    "ai_coding": {"api_changed", "edge_case_handled", "test_added", "validation_added"},
    "data_contract": {
        "api_changed",
        "migration_added",
        "schema_added",
        "test_added",
        "validation_added",
    },
    "data_quality": {"schema_added", "test_added", "validation_added"},
    "edge_case": {"edge_case_handled", "test_added", "validation_added"},
    "process": {"api_changed", "test_added", "workflow_changed"},
    "quality": {"edge_case_handled", "test_added", "validation_added"},
    "structure": {"api_changed", "schema_added", "workflow_changed"},
    "workflow": {"api_changed", "test_added", "workflow_changed"},
}


def build_code_change_feedback(
    findings: Iterable[Mapping[str, Any]],
    diff_text: str,
    *,
    max_snippets_per_file: int = 2,
) -> Dict[str, Any]:
    """Map review findings to weak downstream implementation signals."""

    safe_findings = [finding for finding in findings or [] if isinstance(finding, Mapping)]
    files = parse_unified_diff(diff_text)
    signals = [
        _build_signal(
            finding,
            files,
            max_snippets_per_file=max(0, int(max_snippets_per_file or 0)),
        )
        for finding in safe_findings
    ]
    return {
        "feedback_kind": "downstream_code_change_signal",
        "summary": _summary(signals, total_findings=len(safe_findings)),
        "signals": signals,
    }


def build_code_change_feedback_score_payloads(
    result: Mapping[str, Any],
    *,
    trace_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> list[Dict[str, Any]]:
    """Create raw-code-free Langfuse score payloads for code-change feedback."""

    summary = dict(result.get("summary") or {})
    signals = [signal for signal in result.get("signals") or [] if isinstance(signal, Mapping)]
    metadata = {
        "feedback_kind": "downstream_code_change_signal",
        "total_findings": _safe_int(summary.get("total_findings")),
        "likely_adopted": _safe_int(summary.get("likely_adopted")),
        "possible_related": _safe_int(summary.get("possible_related")),
        "no_code_change_signal": _safe_int(summary.get("no_code_change_signal")),
    }
    target = _score_target(trace_id=trace_id, session_id=session_id)
    average_confidence = (
        sum(_safe_float(signal.get("confidence")) for signal in signals) / len(signals)
        if signals
        else 0.0
    )
    return [
        _score(
            name="pecker.code_change_feedback.implementation_signal_rate",
            value=_safe_float(summary.get("implementation_signal_rate")),
            metadata=metadata,
            target=target,
        ),
        _score(
            name="pecker.code_change_feedback.likely_adopted",
            value=_safe_float(summary.get("likely_adopted")),
            metadata=metadata,
            target=target,
        ),
        _score(
            name="pecker.code_change_feedback.possible_related",
            value=_safe_float(summary.get("possible_related")),
            metadata=metadata,
            target=target,
        ),
        _score(
            name="pecker.code_change_feedback.no_code_change_signal",
            value=_safe_float(summary.get("no_code_change_signal")),
            metadata=metadata,
            target=target,
        ),
        _score(
            name="pecker.code_change_feedback.average_confidence",
            value=average_confidence,
            metadata=metadata,
            target=target,
        ),
    ]


def record_code_change_feedback_scores(
    result: Mapping[str, Any],
    *,
    trace_id: Optional[str] = None,
    session_id: Optional[str] = None,
    client_factory=None,
) -> Dict[str, Any]:
    """Write code-change feedback scores to Langfuse when explicitly requested."""

    scores = build_code_change_feedback_score_payloads(
        result,
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


def parse_unified_diff(diff_text: str) -> list[Dict[str, Any]]:
    """Parse enough of a unified git diff for deterministic feedback signals."""

    files: list[Dict[str, Any]] = []
    current: Dict[str, Any] | None = None
    for raw_line in str(diff_text or "").splitlines():
        match = _DIFF_FILE_RE.match(raw_line)
        if match:
            path = match.group(2) or match.group(1)
            current = {"path": path, "added_lines": []}
            files.append(current)
            continue
        if current is None:
            continue
        if raw_line.startswith("+++") or raw_line.startswith("---"):
            continue
        if raw_line.startswith("+"):
            current["added_lines"].append(raw_line[1:])

    for file_change in files:
        file_change["change_types"] = classify_code_change(
            file_change["path"],
            file_change.get("added_lines") or [],
        )
    return files


def classify_code_change(path: str, added_lines: Iterable[str]) -> list[str]:
    """Classify changed code into coarse review-feedback categories."""

    path_text = _normal_text(path)
    body = _normal_text("\n".join(str(line) for line in added_lines))
    joined = f"{path_text}\n{body}"
    types: set[str] = set()

    if _path_has(path_text, "test", "tests", "spec", "__tests__") or re.search(
        r"\b(test|describe|it)_?[a-z0-9_]*\b", body
    ):
        types.add("test_added")
    if _path_has(path_text, "schema", "schemas", "dto", "model", "models", "types", "openapi"):
        types.add("schema_added")
    if _path_has(path_text, "migration", "migrations", "alembic"):
        types.add("migration_added")
    if _path_has(path_text, "api", "route", "routes", "controller", "handler") or re.search(
        r"\b(@router|router\.|def\s+\w+|post|get|put|patch|delete)\b",
        body,
    ):
        types.add("api_changed")
    if re.search(r"\b(validate|validator|required|raise|valueerror|assert|if\s+not|non_empty)\b", body):
        types.add("validation_added")
    if re.search(r"\b(status|state|workflow|transition|switch|case|elif|else|retry|fallback)\b", joined):
        types.add("workflow_changed")
    if re.search(r"\b(null|none|empty|missing|default|exception|timeout|edge|boundary)\b", joined):
        types.add("edge_case_handled")
    if re.search(r"\b(auth|permission|role|acl|jwt|token|signature)\b", joined):
        types.add("security_added")
    return sorted(types)


def _build_signal(
    finding: Mapping[str, Any],
    files: list[Mapping[str, Any]],
    *,
    max_snippets_per_file: int,
) -> Dict[str, Any]:
    finding_id = _safe_text(
        finding.get("id") or finding.get("finding_id") or finding.get("item_id"),
        120,
    )
    dimension = _normal_text(finding.get("dimension") or finding.get("dim_key"))
    expected_types = set(_DIMENSION_EXPECTED_TYPES.get(dimension, set()))
    keywords = _finding_keywords(finding)

    matched_files = []
    best_confidence = 0.0
    all_change_types: set[str] = set()
    for file_change in files:
        file_signal = _score_file_match(file_change, keywords, expected_types)
        if file_signal["confidence"] < 0.25:
            continue
        best_confidence = max(best_confidence, file_signal["confidence"])
        change_types = list(file_change.get("change_types") or [])
        all_change_types.update(change_types)
        matched_files.append(
            {
                "path": _safe_path(file_change.get("path")),
                "confidence": file_signal["confidence"],
                "keyword_hits": file_signal["keyword_hits"],
                "change_types": change_types,
                "snippets": _safe_added_snippets(
                    file_change.get("added_lines") or [],
                    max_snippets=max_snippets_per_file,
                ),
            }
        )

    confidence = _final_confidence(best_confidence, finding, matched_files)
    return {
        "finding_id": finding_id,
        "rule_id": _safe_text(finding.get("rule_id"), 120),
        "dimension": _safe_text(finding.get("dimension") or finding.get("dim_key"), 80),
        "severity": _safe_text(finding.get("severity"), 40),
        "prd_location": _safe_text(finding.get("location"), 200),
        "feedback_label": _feedback_label(confidence),
        "confidence": confidence,
        "changed_files": [item["path"] for item in matched_files] if confidence >= 0.45 else [],
        "change_types": sorted(all_change_types) if confidence >= 0.45 else [],
        "evidence": matched_files if confidence >= 0.45 else [],
    }


def _score_file_match(
    file_change: Mapping[str, Any],
    keywords: set[str],
    expected_types: set[str],
) -> Dict[str, Any]:
    change_types = set(file_change.get("change_types") or [])
    file_tokens = _tokens_for_file(file_change)
    keyword_hits = sorted((keywords & file_tokens) - _NOISE_WORDS)
    type_overlap = expected_types & change_types

    confidence = 0.0
    if type_overlap:
        confidence += 0.45
    if len(type_overlap) >= 2:
        confidence += 0.1
    confidence += min(0.35, len(keyword_hits) * 0.08)
    if "test_added" in change_types and (
        "acceptance" in keywords or "test" in keywords or "acceptance" in expected_types
    ):
        confidence += 0.15
    return {
        "confidence": round(min(1.0, confidence), 4),
        "keyword_hits": keyword_hits[:12],
    }


def _final_confidence(
    best_confidence: float,
    finding: Mapping[str, Any],
    matched_files: list[Mapping[str, Any]],
) -> float:
    confidence = best_confidence
    if matched_files and str(finding.get("severity") or "").strip().lower() == "must":
        confidence += 0.05
    if len(matched_files) >= 2:
        confidence += 0.05
    return round(min(1.0, confidence), 4)


def _feedback_label(confidence: float) -> str:
    if confidence >= 0.75:
        return "likely_adopted_by_implementation"
    if confidence >= 0.45:
        return "possible_related_code_change"
    return "no_code_change_signal"


def _summary(signals: list[Mapping[str, Any]], *, total_findings: int) -> Dict[str, Any]:
    likely = sum(1 for signal in signals if signal.get("feedback_label") == "likely_adopted_by_implementation")
    possible = sum(1 for signal in signals if signal.get("feedback_label") == "possible_related_code_change")
    no_signal = sum(1 for signal in signals if signal.get("feedback_label") == "no_code_change_signal")
    return {
        "total_findings": total_findings,
        "likely_adopted": likely,
        "possible_related": possible,
        "no_code_change_signal": no_signal,
        "implementation_signal_rate": round((likely + possible * 0.5) / total_findings, 4)
        if total_findings
        else 0.0,
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
        "value": _safe_float(value),
        **target,
        "data_type": "NUMERIC",
        "comment": "downstream_code_change_signal",
        "metadata": dict(metadata),
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


def _finding_keywords(finding: Mapping[str, Any]) -> set[str]:
    parts = [
        finding.get("dimension"),
        finding.get("location"),
        finding.get("issue"),
        finding.get("problem"),
        finding.get("title"),
        finding.get("summary"),
        finding.get("suggestion"),
        finding.get("proposed_patch"),
    ]
    return _tokens(" ".join(str(part or "") for part in parts))


def _tokens_for_file(file_change: Mapping[str, Any]) -> set[str]:
    path = Path(str(file_change.get("path") or "")).as_posix().replace("/", " ")
    body = "\n".join(str(line or "") for line in file_change.get("added_lines") or [])
    return _tokens(f"{path}\n{body}")


def _tokens(value: str) -> set[str]:
    return {
        token.lower()
        for token in _WORD_RE.findall(_normal_text(value))
        if token.lower() not in _NOISE_WORDS
    }


def _safe_added_snippets(lines: Iterable[str], *, max_snippets: int) -> list[str]:
    snippets = []
    for line in lines:
        text = str(line or "").strip()
        if not text:
            continue
        snippets.append(redact_text(text)[:240])
        if len(snippets) >= max_snippets:
            break
    return snippets


def _path_has(path_text: str, *parts: str) -> bool:
    path_parts = set(re.split(r"[/\\_.-]+", path_text))
    return any(part in path_parts for part in parts)


def _safe_path(value: Any) -> str:
    return redact_text(str(value or "").strip().replace("\\", "/"))[:240]


def _safe_text(value: Any, limit: int) -> str:
    return redact_text(str(value or "").strip())[: max(0, int(limit))]


def _safe_trace_id(value: Any) -> str:
    text = str(value or "").strip().lower()
    return text if _TRACE_ID_RE.match(text) else ""


def _safe_float(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return number if number == number and abs(number) != float("inf") else 0.0


def _safe_int(value: Any) -> int:
    try:
        return max(0, int(float(value or 0)))
    except (TypeError, ValueError):
        return 0


def _normal_text(value: Any) -> str:
    return str(value or "").replace("\\", "/").lower()
