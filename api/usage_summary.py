"""Read-only usage summary for the internal admin dashboard."""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from api.budget_gate import budget_status_snapshot
from api.sanitize import redact_prd_content, redact_sensitive, redact_text
from scripts.stability_metrics import (
    _filter_by_days,
    _iter_session_files,
    _parse_session,
    compute_metrics,
)


_AUDIT_ALLOWLIST = {
    "ts",
    "event",
    "reviewer",
    "workspace",
    "prd_name",
    "review_id",
    "items_count",
    "status",
    "action",
    "reason_category",
}


def _parse_ts(value: Any) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value)
        except (OSError, OverflowError, ValueError):
            return None
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value or default)
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value or default)
    except (TypeError, ValueError):
        return default


def _short_prd_preview(value: Any, limit: int = 80) -> str:
    text = str(value or "")
    if not text:
        return ""
    redacted = str(redact_prd_content(text, text))
    compact = " ".join(redacted.split())
    if redacted != text:
        compact = f"{compact}..."
    elif len(compact) > limit:
        compact = compact[: max(0, limit - 3)].rstrip() + "..."
    return compact[:limit]


def _load_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(row, dict):
                    rows.append(row)
    except OSError:
        return []
    return rows


def _iter_audit_files(project_root: Path) -> Iterable[Path]:
    logs_dir = project_root / "logs"
    if not logs_dir.is_dir():
        return []
    paths = list(logs_dir.glob("user_actions_*.jsonl"))
    legacy = logs_dir / "user_actions.jsonl"
    if legacy.is_file():
        paths.append(legacy)
    return sorted(paths)


def _filter_records_by_days(
    rows: Iterable[Dict[str, Any]],
    days: Optional[int],
    now: Optional[datetime],
) -> List[Dict[str, Any]]:
    rows = list(rows)
    if not days:
        return rows
    reference = now or datetime.now()
    cutoff = reference - timedelta(days=days)
    kept: List[Dict[str, Any]] = []
    for row in rows:
        ts = _parse_ts(row.get("ts"))
        if ts and ts >= cutoff:
            kept.append(row)
    return kept


def _empty_retry_summary(
    project_root: Path,
    days: int = 7,
    now: Optional[datetime] = None,
) -> Dict[str, int]:
    rows: List[Dict[str, Any]] = []
    for path in _iter_session_files(project_root):
        rows.extend(_load_jsonl(path))
    rows = _filter_records_by_days(rows, days, now)

    instrumented = 0
    triggered = 0
    rescued = 0
    kept_empty = 0
    confirmed_empty = 0
    forced_confirmed_empty_retry = 0

    for row in rows:
        if row.get("type") != "worker_done" or "empty_retry_used" not in row:
            continue
        instrumented += 1
        if not row.get("empty_retry_used"):
            continue
        triggered += 1
        if _safe_int(row.get("items_count")) > 0:
            rescued += 1
            continue
        kept_empty += 1
        if row.get("empty_submission_confirmed"):
            confirmed_empty += 1
        if row.get("confirmed_empty_retry_forced"):
            forced_confirmed_empty_retry += 1

    return {
        "instrumented_workers": instrumented,
        "triggered": triggered,
        "rescued": rescued,
        "kept_empty": kept_empty,
        "confirmed_empty": confirmed_empty,
        "forced_confirmed_empty_retry": forced_confirmed_empty_retry,
    }


def _sanitize_audit(row: Dict[str, Any]) -> Dict[str, Any]:
    return redact_sensitive({key: row.get(key) for key in _AUDIT_ALLOWLIST if key in row})


def _sanitize_stability(metrics: Dict[str, Any]) -> Dict[str, Any]:
    sanitized = dict(metrics)
    for key in ("by_reviewer", "by_workspace", "by_mode", "tool_breakdown"):
        value = sanitized.get(key)
        if isinstance(value, dict):
            sanitized[key] = {redact_text(str(group)): redact_sensitive(counts) for group, counts in value.items()}
    return sanitized


def _latest_ts(a: str, b: str) -> str:
    a_ts = _parse_ts(a)
    b_ts = _parse_ts(b)
    if not a_ts:
        return b or a
    if not b_ts:
        return a or b
    return a if a_ts >= b_ts else b


def _new_reviewer_bucket(reviewer: str) -> Dict[str, Any]:
    return {
        "reviewer": reviewer,
        "reviews": 0,
        "session_count": 0,
        "started_events": 0,
        "completed": 0,
        "failed": 0,
        "degraded": 0,
        "last_seen": "",
        "last_prd_name": "",
        "workspaces_sessions": defaultdict(int),
        "workspaces_started": defaultdict(int),
    }


def _finalize_reviewer(bucket: Dict[str, Any]) -> Dict[str, Any]:
    workspaces: Dict[str, int] = {}
    for workspace in set(bucket["workspaces_sessions"]) | set(bucket["workspaces_started"]):
        safe_workspace = redact_text(str(workspace))
        workspaces[safe_workspace] = max(
            int(bucket["workspaces_sessions"].get(workspace, 0)),
            int(bucket["workspaces_started"].get(workspace, 0)),
        )
    return {
        "reviewer": redact_text(str(bucket["reviewer"])),
        "reviews": int(max(bucket["session_count"], bucket["started_events"])),
        "session_count": int(bucket["session_count"]),
        "started_events": int(bucket["started_events"]),
        "completed": int(bucket["completed"]),
        "failed": int(bucket["failed"]),
        "degraded": int(bucket["degraded"]),
        "last_seen": bucket["last_seen"],
        "last_prd_name": redact_text(str(bucket["last_prd_name"])),
        "workspaces": dict(sorted(workspaces.items())),
    }


def build_usage_summary(
    project_root: Path,
    days: int = 7,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Build a PM-safe admin usage summary without exposing PRD content."""
    runs: List[Dict[str, Any]] = []
    for path in _iter_session_files(project_root):
        summary = _parse_session(path)
        if summary:
            runs.append(summary)
    if now is not None and days:
        cutoff = now - timedelta(days=days)
        runs = [
            run for run in runs
            if (ts := _parse_ts(run.get("ts_start"))) is not None and ts >= cutoff
        ]
    else:
        runs = _filter_by_days(runs, days)

    stability = _sanitize_stability(compute_metrics(runs))

    audit_rows: List[Dict[str, Any]] = []
    for path in _iter_audit_files(project_root):
        audit_rows.extend(_load_jsonl(path))
    audit_rows = _filter_records_by_days(audit_rows, days, now)

    reviewers: Dict[str, Dict[str, Any]] = {}

    for run in runs:
        reviewer = str(run.get("reviewer") or "unknown")
        bucket = reviewers.setdefault(reviewer, _new_reviewer_bucket(reviewer))
        status = str(run.get("status") or "unknown")
        workspace = str(run.get("workspace") or "")
        ts_start = str(run.get("ts_start") or "")

        bucket["session_count"] += 1
        if status in {"completed", "failed", "degraded"}:
            bucket[status] += 1
        if workspace:
            bucket["workspaces_sessions"][workspace] += 1
        if _latest_ts(bucket["last_seen"], ts_start) == ts_start:
            bucket["last_seen"] = ts_start
            bucket["last_prd_name"] = redact_text(str(run.get("prd_name") or ""))

    for row in audit_rows:
        reviewer = str(row.get("reviewer") or "unknown")
        bucket = reviewers.setdefault(reviewer, _new_reviewer_bucket(reviewer))
        event = str(row.get("event") or "")
        ts = str(row.get("ts") or "")
        workspace = str(row.get("workspace") or "")

        if event == "review_started":
            bucket["started_events"] += 1
            if workspace:
                bucket["workspaces_started"][workspace] += 1
        if _latest_ts(bucket["last_seen"], ts) == ts:
            bucket["last_seen"] = ts
            if row.get("prd_name"):
                bucket["last_prd_name"] = redact_text(str(row.get("prd_name")))

    reviewer_rows = sorted(
        (_finalize_reviewer(bucket) for bucket in reviewers.values()),
        key=lambda r: (r["reviews"], r["started_events"], r["last_seen"]),
        reverse=True,
    )

    recent_runs = sorted(
        runs,
        key=lambda run: _parse_ts(run.get("ts_start")) or datetime.min,
        reverse=True,
    )[:25]
    recent_actions = sorted(
        (_sanitize_audit(row) for row in audit_rows),
        key=lambda row: _parse_ts(row.get("ts")) or datetime.min,
        reverse=True,
    )[:30]

    review_started_events = sum(1 for row in audit_rows if row.get("event") == "review_started")
    total_reviews = int(stability.get("total_runs") or review_started_events)

    try:
        budget = budget_status_snapshot(project_root)
    except Exception as exc:  # pragma: no cover - dashboard should degrade gracefully
        budget = {"enabled": False, "error": redact_text(f"{type(exc).__name__}: {exc}")}

    return {
        "window_days": days,
        "generated_at": (now or datetime.now()).isoformat(timespec="seconds"),
        "summary": {
            "total_reviews": total_reviews,
            "active_reviewers": len([r for r in reviewer_rows if r["reviews"] or r["started_events"]]),
            "completed": _safe_int(stability.get("completed")),
            "failed": _safe_int(stability.get("failed")),
            "degraded": _safe_int(stability.get("degraded")),
            "avg_duration_ms": _safe_int(stability.get("avg_duration_ms")),
            "p95_duration_ms": _safe_int(stability.get("p95_duration_ms")),
            "total_cost_usd": round(_safe_float(stability.get("total_cost_usd")), 4),
            "review_started_events": review_started_events,
            "audit_events": len(audit_rows),
        },
        "reviewers": reviewer_rows,
        "recent_runs": [
            {
                "reviewer": redact_text(str(run.get("reviewer") or "")),
                "prd_name": redact_text(str(run.get("prd_name") or "")),
                "prd_preview": _short_prd_preview(run.get("prd_preview")),
                "workspace": redact_text(str(run.get("workspace") or "")),
                "status": run.get("status"),
                "ts_start": run.get("ts_start"),
                "duration_ms": _safe_int(run.get("duration_ms")),
                "cost_usd": round(_safe_float(run.get("cost_usd")), 4),
                "mode": redact_text(str(run.get("mode") or "")),
                "items_count": _safe_int(run.get("items_count")),
            }
            for run in recent_runs
        ],
        "recent_actions": recent_actions,
        "empty_retry": _empty_retry_summary(project_root, days=days, now=now),
        "stability": stability,
        "budget": budget,
    }


def build_personal_review_history(
    project_root: Path,
    reviewer: str,
    days: int = 30,
    now: Optional[datetime] = None,
    limit: int = 50,
) -> Dict[str, Any]:
    """Build a PM-safe personal review history.

    The response is intentionally metadata-only: material name, workspace,
    status, timing and high-level actions. PRD body/raw event payloads are never
    returned to the browser from this helper.
    """
    reviewer = str(reviewer or "").strip()
    runs: List[Dict[str, Any]] = []
    for path in _iter_session_files(project_root):
        summary = _parse_session(path)
        if summary and str(summary.get("reviewer") or "") == reviewer:
            runs.append(summary)

    if now is not None and days:
        cutoff = now - timedelta(days=days)
        runs = [
            run for run in runs
            if (ts := _parse_ts(run.get("ts_start"))) is not None and ts >= cutoff
        ]
    else:
        runs = _filter_by_days(runs, days)

    audit_rows: List[Dict[str, Any]] = []
    for path in _iter_audit_files(project_root):
        audit_rows.extend(_load_jsonl(path))
    audit_rows = [
        row for row in _filter_records_by_days(audit_rows, days, now)
        if str(row.get("reviewer") or "") == reviewer
    ]

    runs = sorted(
        runs,
        key=lambda run: _parse_ts(run.get("ts_start")) or datetime.min,
        reverse=True,
    )[:limit]
    recent_actions = sorted(
        (_sanitize_audit(row) for row in audit_rows),
        key=lambda row: _parse_ts(row.get("ts")) or datetime.min,
        reverse=True,
    )[:limit]

    return {
        "window_days": days,
        "generated_at": (now or datetime.now()).isoformat(timespec="seconds"),
        "reviewer": redact_text(reviewer),
        "runs": [
            {
                "prd_name": redact_text(str(run.get("prd_name") or "")),
                "workspace": redact_text(str(run.get("workspace") or "")),
                "status": run.get("status"),
                "ts_start": run.get("ts_start"),
                "duration_ms": _safe_int(run.get("duration_ms")),
                "mode": redact_text(str(run.get("mode") or "")),
                "items_count": _safe_int(run.get("items_count")),
            }
            for run in runs
        ],
        "recent_actions": recent_actions,
    }
