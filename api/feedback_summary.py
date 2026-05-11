"""Read-only PM decision feedback summary for the admin dashboard."""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from api.sanitize import redact_prd_content, redact_text


_VALID_ACTIONS = {"accept", "reject", "edit"}


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value if value is not None else default)
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value if value is not None else default)
    except (TypeError, ValueError):
        return default


def _timestamp_from_payload(payload: Dict[str, Any], path: Path) -> int:
    timestamp = _safe_int(payload.get("timestamp"), 0)
    if timestamp > 0:
        return timestamp
    match = re.search(r"_(\d{9,})\.json$", path.name)
    if match:
        return _safe_int(match.group(1), 0)
    try:
        return int(path.stat().st_mtime)
    except OSError:
        return 0


def _iso_from_timestamp(timestamp: int) -> str:
    if timestamp <= 0:
        return ""
    try:
        return datetime.fromtimestamp(timestamp).isoformat(timespec="seconds")
    except (OSError, OverflowError, ValueError):
        return ""


def _short_text(value: Any, limit: int = 160) -> str:
    if value is None:
        return ""
    text = re.sub(r"\s+", " ", redact_text(str(value))).strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def _safe_text(value: Any) -> str:
    return redact_text(str(value or ""))


def _iter_ground_truth_files(project_root: Path) -> Iterable[Path]:
    gt_dir = project_root / "eval" / "ground_truth"
    if not gt_dir.is_dir():
        return []
    return sorted(gt_dir.glob("*.json"))


def _iter_draft_files(project_root: Path) -> Iterable[Path]:
    draft_dir = project_root / ".pecker_drafts"
    if not draft_dir.is_dir():
        return []
    return sorted(draft_dir.glob("*_draft.json"))


def _missing_feedback_file(project_root: Path) -> Path:
    return project_root / "logs" / "missing_feedback.jsonl"


def _load_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _in_window(timestamp: int, days: int, now: Optional[datetime]) -> bool:
    if not days:
        return True
    if timestamp <= 0:
        return False
    reference = now or datetime.now()
    return datetime.fromtimestamp(timestamp) >= reference - timedelta(days=days)


def _timestamp_from_draft(payload: Dict[str, Any], path: Path) -> int:
    ts = str(payload.get("ts") or "")
    if ts:
        try:
            return int(datetime.fromisoformat(ts).timestamp())
        except ValueError:
            pass
    return _timestamp_from_payload(payload, path)


def _timestamp_from_iso(value: Any) -> int:
    text = str(value or "")
    if not text:
        return 0
    try:
        return int(datetime.fromisoformat(text).timestamp())
    except ValueError:
        return 0


def _iter_missing_records(project_root: Path) -> Iterable[Dict[str, Any]]:
    path = _missing_feedback_file(project_root)
    if not path.is_file():
        return []
    records: List[Dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return []
    for index, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        timestamp = _timestamp_from_iso(row.get("timestamp"))
        records.append(
            {
                "timestamp": timestamp,
                "ts": _iso_from_timestamp(timestamp),
                "sort_index": index,
                "feedback_id": str(row.get("feedback_id") or ""),
                "reviewer": _safe_text(row.get("reviewer") or "unknown"),
                "workspace": _safe_text(row.get("workspace")),
                "prd_name": _safe_text(row.get("prd_name")),
                "problem": _short_text(row.get("problem"), 180),
                "location": _short_text(row.get("location"), 120),
                "responsible_bird_id": _safe_text(row.get("responsible_bird_id")),
                "source": "missing_report",
            }
        )
    return records


def _record_from_item(
    payload: Dict[str, Any],
    item: Dict[str, Any],
    path: Path,
    timestamp: int,
    index: int,
) -> Dict[str, Any]:
    action = str(item.get("action") or "").strip()
    record = {
        "timestamp": timestamp,
        "ts": _iso_from_timestamp(timestamp),
        "sort_index": index,
        "reviewer": _safe_text(payload.get("reviewer") or "unknown"),
        "workspace": _safe_text(payload.get("workspace")),
        "prd_name": _safe_text(payload.get("prd_name")),
        "item_id": _safe_text(item.get("id")),
        "rule_id": _safe_text(item.get("rule_id")),
        "dimension": _safe_text(item.get("dimension")),
        "location": _short_text(item.get("location"), 120),
        "severity": _safe_text(item.get("severity")),
        "action": action if action in _VALID_ACTIONS else "unknown",
        "reason_category": _safe_text(item.get("reason_category")),
        "reason_note": _short_text(item.get("reason_note"), 120),
        "problem": _short_text(item.get("problem"), 180),
        "suggestion": _short_text(item.get("suggestion"), 180),
        "is_true_positive": bool(item.get("is_true_positive")),
        "source_file": path.name,
        "source": str(payload.get("_feedback_source") or "confirmed"),
    }
    # contract: NoPRDBody
    prd_body = str(payload.get("prd_content") or payload.get("prd_body") or "")
    return redact_prd_content(record, prd_body) if prd_body else record


def _pct(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 4)


def build_feedback_summary(
    project_root: Path,
    days: int = 7,
    now: Optional[datetime] = None,
    reviewer: str = "",
    workspace: str = "",
    action: str = "",
    limit: int = 100,
) -> Dict[str, Any]:
    """Build an admin-only summary of PM item decisions.

    The response intentionally keeps to reviewed item metadata and short model
    issue summaries. It does not include the uploaded PRD body or raw materials.
    """
    reviewer = reviewer.strip()
    workspace = workspace.strip()
    action = action.strip()
    limit = max(1, min(int(limit or 100), 500))

    records: List[Dict[str, Any]] = []
    source_index = 0
    for path in _iter_ground_truth_files(project_root):
        payload = _load_json(path)
        if not payload:
            continue
        payload["_feedback_source"] = "confirmed"
        timestamp = _timestamp_from_payload(payload, path)
        if not _in_window(timestamp, days, now):
            continue
        if reviewer and payload.get("reviewer") != reviewer:
            continue
        if workspace and payload.get("workspace") != workspace:
            continue
        items = payload.get("items")
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            record = _record_from_item(payload, item, path, timestamp, source_index)
            source_index += 1
            if action and record["action"] != action:
                continue
            records.append(record)

    confirmed_keys = {
        (
            row["reviewer"],
            row["workspace"],
            row["prd_name"],
            row["item_id"],
        )
        for row in records
        if row.get("source") == "confirmed"
    }

    for path in _iter_draft_files(project_root):
        payload = _load_json(path)
        if not payload:
            continue
        payload["_feedback_source"] = "draft"
        timestamp = _timestamp_from_draft(payload, path)
        if not _in_window(timestamp, days, now):
            continue
        if reviewer and payload.get("reviewer") != reviewer:
            continue
        if workspace and payload.get("workspace") != workspace:
            continue
        review_result = payload.get("review_result")
        decisions = payload.get("item_decisions")
        if not isinstance(review_result, dict) or not isinstance(decisions, dict):
            continue
        items = review_result.get("items")
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            item_id = str(item.get("id") or "")
            decision = decisions.get(item_id)
            if not isinstance(decision, dict):
                continue
            dedupe_key = (
                str(payload.get("reviewer") or "unknown"),
                str(payload.get("workspace") or ""),
                str(payload.get("prd_name") or ""),
                item_id,
            )
            if dedupe_key in confirmed_keys:
                continue
            draft_item = {
                **item,
                "action": decision.get("action"),
                "reason_category": decision.get("reason_category"),
                "reason_note": decision.get("reason"),
                "problem": decision.get("edited_problem") or item.get("problem"),
            }
            record = _record_from_item(payload, draft_item, path, timestamp, source_index)
            source_index += 1
            if action and record["action"] != action:
                continue
            records.append(record)

    missing_records: List[Dict[str, Any]] = []
    for row in _iter_missing_records(project_root):
        if not _in_window(row["timestamp"], days, now):
            continue
        if reviewer and row.get("reviewer") != reviewer:
            continue
        if workspace and row.get("workspace") != workspace:
            continue
        missing_records.append(row)

    records.sort(key=lambda row: (row["timestamp"], row["sort_index"]), reverse=True)
    missing_records.sort(key=lambda row: (row["timestamp"], row["sort_index"]), reverse=True)

    action_counts = Counter(row["action"] for row in records)
    category_counts = Counter(
        row["reason_category"] or "未填写"
        for row in records
        if row["action"] == "reject"
    )
    dimension_counts = Counter(row["dimension"] or "未标注" for row in records)

    by_reviewer: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {
            "reviewer": "",
            "total_items": 0,
            "accepted": 0,
            "rejected": 0,
            "edited": 0,
            "last_seen": "",
        }
    )
    by_workspace: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {
            "workspace": "",
            "total_items": 0,
            "accepted": 0,
            "rejected": 0,
            "edited": 0,
            "last_seen": "",
        }
    )

    for row in records:
        reviewer_bucket = by_reviewer[row["reviewer"]]
        reviewer_bucket["reviewer"] = row["reviewer"]
        reviewer_bucket["total_items"] += 1
        if row["action"] == "accept":
            reviewer_bucket["accepted"] += 1
        elif row["action"] == "reject":
            reviewer_bucket["rejected"] += 1
        elif row["action"] == "edit":
            reviewer_bucket["edited"] += 1
        if row["ts"] > reviewer_bucket["last_seen"]:
            reviewer_bucket["last_seen"] = row["ts"]

        workspace_bucket = by_workspace[row["workspace"]]
        workspace_bucket["workspace"] = row["workspace"]
        workspace_bucket["total_items"] += 1
        if row["action"] == "accept":
            workspace_bucket["accepted"] += 1
        elif row["action"] == "reject":
            workspace_bucket["rejected"] += 1
        elif row["action"] == "edit":
            workspace_bucket["edited"] += 1
        if row["ts"] > workspace_bucket["last_seen"]:
            workspace_bucket["last_seen"] = row["ts"]

    total = len(records)
    accepted = int(action_counts.get("accept", 0))
    rejected = int(action_counts.get("reject", 0))
    edited = int(action_counts.get("edit", 0))
    draft_items = sum(1 for row in records if row.get("source") == "draft")

    public_records = [
        {
            key: value
            for key, value in row.items()
            if key not in {"sort_index", "source_file"}
        }
        for row in records[:limit]
    ]

    return {
        "window_days": days,
        "generated_at": (now or datetime.now()).isoformat(timespec="seconds"),
        "summary": {
            "total_items": total,
            "accepted": accepted,
            "rejected": rejected,
            "edited": edited,
            "accept_rate": _pct(accepted + edited, total),
            "reject_rate": _pct(rejected, total),
            "feedback_reviewers": len(by_reviewer),
        },
        "draft_items": draft_items,
        "missing_reports": len(missing_records),
        "by_reviewer": sorted(
            by_reviewer.values(),
            key=lambda row: (row["total_items"], row["last_seen"]),
            reverse=True,
        ),
        "by_workspace": sorted(
            by_workspace.values(),
            key=lambda row: (row["total_items"], row["last_seen"]),
            reverse=True,
        ),
        "reason_categories": dict(category_counts.most_common()),
        "dimensions": dict(dimension_counts.most_common()),
        "records": public_records,
        "missing_records": [
            {key: value for key, value in row.items() if key != "sort_index"}
            for row in missing_records[:limit]
        ],
    }
