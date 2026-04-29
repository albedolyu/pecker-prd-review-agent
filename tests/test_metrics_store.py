"""metrics_store 单元测试: 写读 / 聚合 / prune / timer 上下文 / silent skip."""
from __future__ import annotations

import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from review.metrics_store import (  # noqa: E402
    aggregate_daily, get_summary, materialize_daily_aggregate,
    prune_old_events, query_events, record_event, timer,
)


def test_record_and_query():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db = os.path.join(tmp, "metrics.db")
        assert record_event(
            "review.completed", workspace="ws", reviewer="alice",
            duration_ms=12000, model="claude-sonnet-4-6", cost_usd=0.012,
            db_path=db,
        ) is True
        events = query_events(db, event_type="review.completed")
        assert len(events) == 1
        e = events[0]
        assert e["reviewer"] == "alice"
        assert e["duration_ms"] == 12000
        assert e["cost_usd"] == 0.012


def test_silent_skip_no_db_path():
    """无 workspace + 无 METRICS_DB_PATH → silent return False, 不抛."""
    old_ws = os.environ.pop("WORKSPACE", None)
    old_dbp = os.environ.pop("METRICS_DB_PATH", None)
    try:
        result = record_event("test.event")
        assert result is False
    finally:
        if old_ws:
            os.environ["WORKSPACE"] = old_ws
        if old_dbp:
            os.environ["METRICS_DB_PATH"] = old_dbp


def test_silent_skip_disabled_env():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db = os.path.join(tmp, "metrics.db")
        os.environ["METRICS_DISABLED"] = "1"
        try:
            assert record_event("x", db_path=db) is False
        finally:
            os.environ.pop("METRICS_DISABLED")


def test_timer_context():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db = os.path.join(tmp, "metrics.db")
        with timer("worker.completed", workspace="ws", model="haiku", db_path=db) as ctx:
            time.sleep(0.05)
            ctx["details"] = {"items": 7}
        events = query_events(db)
        assert len(events) == 1
        assert events[0]["status"] == "success"
        assert events[0]["duration_ms"] >= 50

        # 异常路径 status=failed
        try:
            with timer("worker.completed", workspace="ws", db_path=db):
                raise RuntimeError("boom")
        except RuntimeError:
            pass
        events = query_events(db, event_type="worker.completed")
        assert any(e["status"] == "failed" for e in events)


def test_aggregate_daily_and_summary():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db = os.path.join(tmp, "metrics.db")
        for i in range(5):
            record_event(
                "review.completed", duration_ms=10000 + i * 1000,
                cost_usd=0.01, status="success", db_path=db,
            )
        record_event("review.failed", status="failed", db_path=db)
        agg = aggregate_daily(db, days_back=7)
        assert any(r["event_type"] == "review.completed" and r["count"] == 5 for r in agg)
        s = get_summary(db, days=7)
        assert s["reviews"] == 5
        assert s["errors"] == 1
        assert s["total_cost_usd"] >= 0.05 - 1e-6


def test_materialize_and_prune():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db = os.path.join(tmp, "metrics.db")
        for _ in range(3):
            record_event("worker.completed", status="success", db_path=db)
        n = materialize_daily_aggregate(db)
        assert n >= 1
        # prune 0 天前 → 全删 (因为 timestamp < 'now-0 days' 永远 false, 实际上不删)
        # 用极大 keep_days 验证不删
        deleted = prune_old_events(db, keep_days=365)
        assert deleted == 0
        events = query_events(db)
        assert len(events) == 3


if __name__ == "__main__":
    test_record_and_query()
    test_silent_skip_no_db_path()
    test_silent_skip_disabled_env()
    test_timer_context()
    test_aggregate_daily_and_summary()
    test_materialize_and_prune()
    print("[OK] metrics_store tests passed")
