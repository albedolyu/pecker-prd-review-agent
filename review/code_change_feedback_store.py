"""SQLite persistence for downstream code-change feedback signals."""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional

from api.sanitize import redact_sensitive, redact_text


_DEFAULT_DB_PATH = Path(__file__).resolve().parent / "code_change_feedback.db"
_LABELS = (
    "likely_adopted_by_implementation",
    "possible_related_code_change",
    "no_code_change_signal",
)


def init_code_change_feedback_store(db_path: str | Path | None = None) -> None:
    path = _resolve_db_path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS code_change_feedback_signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                review_id TEXT,
                finding_id TEXT NOT NULL,
                rule_id TEXT,
                dimension TEXT,
                severity TEXT,
                feedback_label TEXT NOT NULL,
                confidence REAL NOT NULL,
                changed_files_json TEXT NOT NULL,
                change_types_json TEXT NOT NULL,
                evidence_json TEXT NOT NULL,
                source_ref TEXT,
                target_ref TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_code_feedback_created
                ON code_change_feedback_signals(created_at);
            CREATE INDEX IF NOT EXISTS idx_code_feedback_review
                ON code_change_feedback_signals(review_id);
            CREATE INDEX IF NOT EXISTS idx_code_feedback_finding
                ON code_change_feedback_signals(finding_id);
            CREATE INDEX IF NOT EXISTS idx_code_feedback_rule
                ON code_change_feedback_signals(rule_id);
            CREATE INDEX IF NOT EXISTS idx_code_feedback_label
                ON code_change_feedback_signals(feedback_label);
            """
        )
        conn.commit()


def record_code_change_feedback_result(
    result: Mapping[str, Any],
    *,
    review_id: str = "",
    source_ref: str = "",
    target_ref: str = "",
    db_path: str | Path | None = None,
) -> Dict[str, Any]:
    path = _resolve_db_path(db_path)
    init_code_change_feedback_store(path)
    signals = [signal for signal in result.get("signals") or [] if isinstance(signal, Mapping)]
    created_at = datetime.now().isoformat(timespec="seconds")
    with _connect(path) as conn:
        for signal in signals:
            conn.execute(
                """INSERT INTO code_change_feedback_signals
                   (created_at, review_id, finding_id, rule_id, dimension, severity,
                    feedback_label, confidence, changed_files_json, change_types_json,
                    evidence_json, source_ref, target_ref)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    created_at,
                    _safe_text(review_id, 160),
                    _safe_text(signal.get("finding_id"), 120),
                    _safe_text(signal.get("rule_id"), 120),
                    _safe_text(signal.get("dimension"), 80),
                    _safe_text(signal.get("severity"), 40),
                    _safe_label(signal.get("feedback_label")),
                    _safe_float(signal.get("confidence")),
                    _safe_json(signal.get("changed_files") or []),
                    _safe_json(signal.get("change_types") or []),
                    _safe_json(_safe_evidence(signal.get("evidence") or [])),
                    _safe_text(source_ref, 160),
                    _safe_text(target_ref, 160),
                ),
            )
        conn.commit()
    return {"status": "recorded", "signals_recorded": len(signals), "db_path": str(path)}


def summarize_code_change_feedback_store(
    *,
    days: Optional[int] = None,
    db_path: str | Path | None = None,
) -> Dict[str, Any]:
    path = _resolve_db_path(db_path)
    init_code_change_feedback_store(path)
    rows = _load_rows(days=days, db_path=path)
    summary = _empty_summary()
    summary["total_signals"] = len(rows)
    by_dimension: dict[str, Dict[str, Any]] = {}
    by_rule: dict[str, Dict[str, Any]] = {}
    for row in rows:
        label = row["feedback_label"]
        if label == "likely_adopted_by_implementation":
            summary["likely_adopted"] += 1
        elif label == "possible_related_code_change":
            summary["possible_related"] += 1
        else:
            summary["no_code_change_signal"] += 1
        _bucket_increment(by_dimension, row["dimension"] or "unknown", label)
        _bucket_increment(by_rule, row["rule_id"] or "unknown", label)
    summary["implementation_signal_rate"] = _signal_rate(summary)
    summary["by_dimension"] = by_dimension
    summary["by_rule"] = by_rule
    return summary


def get_recent_code_change_feedback_signals(
    *,
    limit: int = 20,
    db_path: str | Path | None = None,
) -> list[Dict[str, Any]]:
    path = _resolve_db_path(db_path)
    init_code_change_feedback_store(path)
    with _connect(path) as conn:
        rows = conn.execute(
            """SELECT *
               FROM code_change_feedback_signals
               ORDER BY id DESC
               LIMIT ?""",
            [max(0, int(limit or 0))],
        ).fetchall()
    return [_row_to_public_dict(row) for row in rows]


def _load_rows(*, days: Optional[int], db_path: Path) -> list[sqlite3.Row]:
    clause = ""
    args: list[Any] = []
    if days is not None and days > 0:
        clause = "WHERE created_at >= ?"
        args.append((datetime.now() - timedelta(days=days)).isoformat(timespec="seconds"))
    with _connect(db_path) as conn:
        return conn.execute(
            f"""SELECT *
                FROM code_change_feedback_signals
                {clause}
                ORDER BY id DESC""",
            args,
        ).fetchall()


def _row_to_public_dict(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "review_id": row["review_id"] or "",
        "finding_id": row["finding_id"],
        "rule_id": row["rule_id"] or "",
        "dimension": row["dimension"] or "",
        "severity": row["severity"] or "",
        "feedback_label": row["feedback_label"],
        "confidence": _safe_float(row["confidence"]),
        "changed_files": _load_json_list(row["changed_files_json"]),
        "change_types": _load_json_list(row["change_types_json"]),
        "evidence": _load_json_list(row["evidence_json"]),
        "source_ref": row["source_ref"] or "",
        "target_ref": row["target_ref"] or "",
    }


def _bucket_increment(bucket: dict[str, Dict[str, Any]], key: str, label: str) -> None:
    current = bucket.setdefault(key, _empty_summary())
    current["total_signals"] += 1
    if label == "likely_adopted_by_implementation":
        current["likely_adopted"] += 1
    elif label == "possible_related_code_change":
        current["possible_related"] += 1
    else:
        current["no_code_change_signal"] += 1
    current["implementation_signal_rate"] = _signal_rate(current)


def _empty_summary() -> Dict[str, Any]:
    return {
        "total_signals": 0,
        "likely_adopted": 0,
        "possible_related": 0,
        "no_code_change_signal": 0,
        "implementation_signal_rate": 0.0,
    }


def _signal_rate(summary: Mapping[str, Any]) -> float:
    total = _safe_float(summary.get("total_signals"))
    if total <= 0:
        return 0.0
    value = _safe_float(summary.get("likely_adopted")) + _safe_float(summary.get("possible_related")) * 0.5
    return round(value / total, 4)


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def _resolve_db_path(db_path: str | Path | None = None) -> Path:
    raw = db_path or os.environ.get("PECKER_CODE_CHANGE_FEEDBACK_DB") or _DEFAULT_DB_PATH
    return Path(raw).expanduser().resolve()


def _safe_evidence(value: Iterable[Any]) -> list[Any]:
    return redact_sensitive(list(value or []))


def _safe_json(value: Any) -> str:
    return json.dumps(redact_sensitive(value), ensure_ascii=False, separators=(",", ":"))


def _load_json_list(value: str) -> list[Any]:
    try:
        loaded = json.loads(value or "[]")
    except json.JSONDecodeError:
        return []
    return loaded if isinstance(loaded, list) else []


def _safe_label(value: Any) -> str:
    label = str(value or "").strip()
    return label if label in _LABELS else "no_code_change_signal"


def _safe_text(value: Any, limit: int) -> str:
    return redact_text(str(value or "").strip())[: max(0, int(limit))]


def _safe_float(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return number if number == number and abs(number) != float("inf") else 0.0
