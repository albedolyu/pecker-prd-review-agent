from __future__ import annotations

import gzip
import os
import sqlite3
import sys
import tarfile
from datetime import datetime, timedelta
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _touch_days_old(path: Path, days: int) -> None:
    old = datetime.now() - timedelta(days=days)
    ts = old.timestamp()
    os.utime(path, (ts, ts))


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_retention_sweep_dry_run_does_not_mutate_old_files(tmp_path: Path) -> None:
    from scripts.retention_sweep import RetentionConfig, run_retention_sweep

    draft = _write(tmp_path / ".pecker_drafts" / "old.json", '{"prd_body":"secret"}')
    log = _write(tmp_path / "logs" / "old.log", "old log")
    event_store = _write(tmp_path / "event_store.jsonl", '{"type":"review_started"}\n')
    _touch_days_old(draft, 45)
    _touch_days_old(log, 20)

    result = run_retention_sweep(
        tmp_path,
        apply=False,
        config=RetentionConfig(
            draft_days=30,
            log_days=14,
            event_store_max_mb=0.000001,
        ),
    )

    assert result["summary"]["mode"] == "dry-run"
    assert {a["category"] for a in result["actions"]} >= {"draft", "log", "event_store"}
    assert draft.exists()
    assert log.exists()
    assert event_store.read_text(encoding="utf-8") == '{"type":"review_started"}\n'


def test_retention_sweep_apply_archives_and_removes_live_files(tmp_path: Path) -> None:
    from scripts.retention_sweep import RetentionConfig, run_retention_sweep

    draft = _write(tmp_path / ".pecker_drafts" / "old.json", '{"prd_body":"secret"}')
    report = _write(tmp_path / "eval_reports" / "old_eval.json", '{"score":0.8}')
    log = _write(tmp_path / "logs" / "old.log", "old log")
    event_store = _write(tmp_path / "event_store.jsonl", '{"type":"review_started"}\n')
    _touch_days_old(draft, 45)
    _touch_days_old(report, 100)
    _touch_days_old(log, 20)

    result = run_retention_sweep(
        tmp_path,
        apply=True,
        config=RetentionConfig(
            draft_days=30,
            eval_report_days=90,
            log_days=14,
            event_store_max_mb=0.000001,
        ),
    )

    assert result["summary"]["mode"] == "apply"
    assert not draft.exists()
    assert not report.exists()
    assert not log.exists()
    assert event_store.exists()
    assert event_store.read_text(encoding="utf-8") == ""
    assert list((tmp_path / ".trash" / "retention").glob("*/.pecker_drafts/old.json"))

    event_archives = list(tmp_path.glob("event_store.*.jsonl.gz"))
    assert event_archives
    with gzip.open(event_archives[0], "rt", encoding="utf-8") as fh:
        assert "review_started" in fh.read()

    eval_archives = list((tmp_path / "eval_reports" / "archive").glob("*.tar.gz"))
    assert eval_archives
    with tarfile.open(eval_archives[0], "r:gz") as tar:
        assert "old_eval.json" in tar.getnames()

    log_archives = list((tmp_path / "logs" / "archive").glob("*.tar.gz"))
    assert log_archives
    with tarfile.open(log_archives[0], "r:gz") as tar:
        assert "old.log" in tar.getnames()


def test_retention_sweep_archives_old_finding_rows(tmp_path: Path) -> None:
    from review.finding_outcomes_store import init_store, record_outcome
    from scripts.retention_sweep import RetentionConfig, run_retention_sweep

    db = tmp_path / "review" / "finding_outcomes.db"
    init_store(str(db))
    old_id = record_outcome("R-old", "reject", rule_id="R-old", db_path=str(db))
    new_id = record_outcome("R-new", "accept", rule_id="R-new", db_path=str(db))

    old_ts = (datetime.now() - timedelta(days=240)).isoformat(timespec="seconds")
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE finding_outcomes SET timestamp = ? WHERE id = ?", (old_ts, old_id))
        conn.commit()

    run_retention_sweep(
        tmp_path,
        apply=True,
        config=RetentionConfig(finding_days=180),
    )

    with sqlite3.connect(db) as conn:
        live_ids = {row[0] for row in conn.execute("SELECT id FROM finding_outcomes")}
        archived_ids = {row[0] for row in conn.execute("SELECT id FROM findings_archive")}

    assert new_id in live_ids
    assert old_id not in live_ids
    assert old_id in archived_ids


def test_retention_report_summarizes_reclaimable_bytes_without_mutation(tmp_path: Path) -> None:
    from scripts.retention_report import build_retention_report
    from scripts.retention_sweep import RetentionConfig

    draft = _write(tmp_path / ".pecker_drafts" / "old.json", '{"prd_body":"secret"}')
    _touch_days_old(draft, 45)

    report = build_retention_report(
        tmp_path,
        config=RetentionConfig(draft_days=30),
    )

    assert report["summary"]["mode"] == "report"
    assert report["summary"]["action_count"] == 1
    assert report["summary"]["reclaimable_bytes"] >= draft.stat().st_size
    assert draft.exists()
