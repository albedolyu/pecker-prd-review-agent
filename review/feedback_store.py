"""Structured PM feedback store beyond per-finding decisions."""
from __future__ import annotations

import json
import os
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

from api.sanitize import redact_text


REWORK_AVOIDANCE_CATEGORIES = {
    "field_caliber",
    "experience_flow",
    "implementation_risk",
    "none",
}

_DEFAULT_DB_PATH = Path(__file__).resolve().parent / "feedback.db"


def _resolve_db_path(db_path: str | Path | None = None) -> Path:
    return Path(db_path or os.environ.get("PECKER_FEEDBACK_DB", _DEFAULT_DB_PATH))


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def init_feedback_store(db_path: str | Path | None = None) -> None:
    path = _resolve_db_path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS pm_rework_avoidance (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp       TEXT NOT NULL,
                reviewer        TEXT,
                workspace       TEXT,
                prd_name        TEXT,
                categories_json TEXT NOT NULL,
                note            TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_pm_rework_ts ON pm_rework_avoidance(timestamp);
            CREATE INDEX IF NOT EXISTS idx_pm_rework_reviewer ON pm_rework_avoidance(reviewer);
            CREATE INDEX IF NOT EXISTS idx_pm_rework_workspace ON pm_rework_avoidance(workspace);
            """
        )
        conn.commit()


def normalize_rework_categories(categories: Iterable[str]) -> list[str]:
    normalized: list[str] = []
    for raw in categories:
        value = str(raw or "").strip()
        if not value:
            continue
        if value not in REWORK_AVOIDANCE_CATEGORIES:
            raise ValueError(f"unknown rework avoidance category: {value}")
        if value not in normalized:
            normalized.append(value)
    if not normalized:
        raise ValueError("categories must not be empty")
    if "none" in normalized:
        return ["none"]
    return normalized


def record_rework_avoidance(
    *,
    categories: Iterable[str],
    note: str = "",
    reviewer: str = "",
    workspace: str = "",
    prd_name: str = "",
    db_path: str | Path | None = None,
) -> int:
    path = _resolve_db_path(db_path)
    init_feedback_store(path)
    normalized = normalize_rework_categories(categories)
    safe_note = redact_text(str(note or "").strip())[:100]
    timestamp = datetime.now().isoformat(timespec="seconds")
    with _connect(path) as conn:
        cur = conn.execute(
            """
            INSERT INTO pm_rework_avoidance
                (timestamp, reviewer, workspace, prd_name, categories_json, note)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                timestamp,
                redact_text(str(reviewer or ""))[:64],
                redact_text(str(workspace or ""))[:128],
                redact_text(str(prd_name or ""))[:128],
                json.dumps(normalized, ensure_ascii=False),
                safe_note,
            ),
        )
        conn.commit()
        return int(cur.lastrowid or 0)


def get_rework_avoidance_summary(
    *,
    db_path: str | Path | None = None,
    days: int = 7,
    now: datetime | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    path = _resolve_db_path(db_path)
    if not path.exists():
        return _empty_summary()
    reference = now or datetime.now()
    cutoff = (reference - timedelta(days=days)).isoformat(timespec="seconds")
    try:
        with _connect(path) as conn:
            rows = conn.execute(
                """
                SELECT id, timestamp, reviewer, workspace, prd_name, categories_json, note
                FROM pm_rework_avoidance
                WHERE timestamp >= ?
                ORDER BY timestamp DESC, id DESC
                """,
                (cutoff,),
            ).fetchall()
    except sqlite3.Error:
        return _empty_summary()

    category_counts: Counter[str] = Counter()
    weekly: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"week": "", "total_samples": 0, "productive_samples": 0, "productive_rate": 0.0}
    )
    recent_notes: list[dict[str, Any]] = []
    productive_samples = 0

    for row in rows:
        categories = _decode_categories(row["categories_json"])
        is_productive = categories != ["none"]
        if is_productive:
            productive_samples += 1
        for category in categories:
            category_counts[category] += 1
        week = _week_label(row["timestamp"])
        bucket = weekly[week]
        bucket["week"] = week
        bucket["total_samples"] += 1
        if is_productive:
            bucket["productive_samples"] += 1
        note = str(row["note"] or "").strip()
        if note and len(recent_notes) < limit:
            recent_notes.append(
                {
                    "timestamp": row["timestamp"],
                    "reviewer": row["reviewer"] or "",
                    "workspace": row["workspace"] or "",
                    "prd_name": row["prd_name"] or "",
                    "categories": categories,
                    "note": redact_text(note)[:100],
                }
            )

    for bucket in weekly.values():
        bucket["productive_rate"] = _pct(bucket["productive_samples"], bucket["total_samples"])

    total = len(rows)
    return {
        "total_samples": total,
        "productive_samples": productive_samples,
        "productive_rate": _pct(productive_samples, total),
        "category_counts": dict(category_counts.most_common()),
        "weekly": sorted(weekly.values(), key=lambda item: item["week"], reverse=True),
        "recent_notes": recent_notes,
    }


def _empty_summary() -> dict[str, Any]:
    return {
        "total_samples": 0,
        "productive_samples": 0,
        "productive_rate": 0.0,
        "category_counts": {},
        "weekly": [],
        "recent_notes": [],
    }


def _decode_categories(value: str) -> list[str]:
    try:
        data = json.loads(value)
    except json.JSONDecodeError:
        return ["none"]
    if not isinstance(data, list):
        return ["none"]
    try:
        return normalize_rework_categories(str(item) for item in data)
    except ValueError:
        return ["none"]


def _week_label(value: str) -> str:
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return "unknown"
    year, week, _ = dt.isocalendar()
    return f"{year}-W{week:02d}"


def _pct(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 4)
