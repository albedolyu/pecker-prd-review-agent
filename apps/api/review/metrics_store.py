"""Pecker v2 — Metrics Store (sqlite 后端 + 零开销埋点 + 90 天保留).

设计目标:
  - 不引重型监控 (prometheus/grafana 太重), 用 sqlite + 静态 html dashboard.
  - 关键路径埋点必须零开销: 失败 silent skip, 不阻 review 主流程.
  - 长期趋势用 daily_aggregate 表预聚合, 原始 events 90 天后 prune.

数据模型:
  events {
    id INTEGER PK,
    timestamp TEXT (iso),
    event_type TEXT (review.started / worker.completed / llm.api_call / oauth.refresh ...),
    workspace TEXT?,
    reviewer TEXT?,
    duration_ms INTEGER?,
    model TEXT?,
    cost_usd REAL?,
    status TEXT (success | failed | timeout),
    details_json TEXT
  }
  daily_aggregate {
    date TEXT,
    event_type TEXT,
    count INTEGER,
    avg_duration_ms REAL,
    total_cost_usd REAL,
    error_count INTEGER,
    PRIMARY KEY (date, event_type)
  }

使用方式 (从业务代码):
    from review.metrics_store import record_event
    record_event("review.started", workspace="ws-1", reviewer="alice")
    record_event("worker.completed", workspace="ws-1", duration_ms=15234,
                 model="claude-sonnet-4-6", cost_usd=0.012, status="success",
                 details={"dim_key": "rule_check"})

环境变量:
  METRICS_DB_PATH: 显式指定 db 文件, 默认 workspace/metrics.db (workspace 来自 env)
  METRICS_DISABLED: 设为 1 / true 时所有 record_event 变 no-op (eval / unit test 场景)
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional


_LOCK = threading.Lock()
_LAST_WARN_TS = 0.0  # 用于错误降噪 (失败时 1 分钟内只 warn 一次)


def _resolve_db_path(workspace: Optional[str] = None) -> Optional[str]:
    """决定 metrics.db 路径; 找不到合理 path 时返回 None → 触发 silent skip."""
    explicit = os.environ.get("METRICS_DB_PATH")
    if explicit:
        return explicit
    ws = workspace or os.environ.get("WORKSPACE")
    if ws and os.path.isdir(ws):
        return os.path.join(ws, "metrics.db")
    return None


def _disabled() -> bool:
    return os.environ.get("METRICS_DISABLED", "").lower() in ("1", "true", "yes")


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            event_type TEXT NOT NULL,
            workspace TEXT,
            reviewer TEXT,
            duration_ms INTEGER,
            model TEXT,
            cost_usd REAL,
            status TEXT,
            details_json TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp);
        CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);
        CREATE INDEX IF NOT EXISTS idx_events_workspace ON events(workspace);

        CREATE TABLE IF NOT EXISTS daily_aggregate (
            date TEXT NOT NULL,
            event_type TEXT NOT NULL,
            count INTEGER NOT NULL DEFAULT 0,
            avg_duration_ms REAL,
            total_cost_usd REAL NOT NULL DEFAULT 0,
            error_count INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (date, event_type)
        );
        CREATE INDEX IF NOT EXISTS idx_daily_date ON daily_aggregate(date);
        """
    )


@contextmanager
def _connect(db_path: str) -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(db_path, timeout=10.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.row_factory = sqlite3.Row
    try:
        _ensure_schema(conn)
        yield conn
    finally:
        conn.close()


def record_event(
    event_type: str,
    *,
    workspace: Optional[str] = None,
    reviewer: Optional[str] = None,
    duration_ms: Optional[int] = None,
    model: Optional[str] = None,
    cost_usd: Optional[float] = None,
    status: Optional[str] = "success",
    details: Optional[Dict[str, Any]] = None,
    db_path: Optional[str] = None,
) -> bool:
    """埋点入口. 失败 silent skip, 永远不抛, 不阻 review 主流程.

    Returns: True 写成功, False 跳过 (disabled / 无 db_path / 写失败).
    """
    global _LAST_WARN_TS
    if _disabled():
        return False
    path = db_path or _resolve_db_path(workspace)
    if not path:
        return False
    try:
        details_json = json.dumps(details, ensure_ascii=False) if details else None
        ts = time.strftime("%Y-%m-%dT%H:%M:%S")
        with _LOCK, _connect(path) as conn:
            conn.execute(
                """
                INSERT INTO events (
                    timestamp, event_type, workspace, reviewer,
                    duration_ms, model, cost_usd, status, details_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ts, event_type, workspace, reviewer,
                    duration_ms, model, cost_usd, status, details_json,
                ),
            )
            conn.commit()
        return True
    except Exception as e:  # noqa: BLE001 — 故意吞所有异常, 埋点零开销
        now = time.time()
        if now - _LAST_WARN_TS > 60:
            try:
                from logger import get_logger
                get_logger("metrics").warning(f"record_event 失败 (silent skip): {e}")
            except Exception:
                pass
            _LAST_WARN_TS = now
        return False


# ============================================================
# Timer 上下文管理器 (常见场景: 测一段代码耗时 + 自动埋点)
# ============================================================

@contextmanager
def timer(event_type: str, **kwargs: Any) -> Iterator[Dict[str, Any]]:
    """用法:
        with timer("worker.completed", workspace=ws, model="sonnet") as ctx:
            do_work()
            ctx["details"] = {"items": len(items)}
    抛异常时自动记 status=failed, 不吞异常.
    """
    start = time.time()
    ctx: Dict[str, Any] = {"details": kwargs.pop("details", None)}
    status = "success"
    try:
        yield ctx
    except Exception:
        status = "failed"
        raise
    finally:
        duration_ms = int((time.time() - start) * 1000)
        record_event(
            event_type,
            duration_ms=duration_ms,
            status=status,
            details=ctx.get("details"),
            **kwargs,
        )


# ============================================================
# 查询 / 统计接口 (供 dashboard / 告警用)
# ============================================================

def query_events(
    db_path: str,
    *,
    event_type: Optional[str] = None,
    since_iso: Optional[str] = None,
    until_iso: Optional[str] = None,
    workspace: Optional[str] = None,
    limit: int = 1000,
) -> List[Dict[str, Any]]:
    if not os.path.isfile(db_path):
        return []
    sql = "SELECT * FROM events WHERE 1=1"
    params: List[Any] = []
    if event_type:
        sql += " AND event_type = ?"
        params.append(event_type)
    if since_iso:
        sql += " AND timestamp >= ?"
        params.append(since_iso)
    if until_iso:
        sql += " AND timestamp <= ?"
        params.append(until_iso)
    if workspace:
        sql += " AND workspace = ?"
        params.append(workspace)
    sql += " ORDER BY timestamp DESC LIMIT ?"
    params.append(limit)
    with _connect(db_path) as conn:
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]


def aggregate_daily(db_path: str, *, days_back: int = 30) -> List[Dict[str, Any]]:
    """按天 + event_type 聚合, 返回最近 N 天的明细."""
    if not os.path.isfile(db_path):
        return []
    sql = """
        SELECT
            substr(timestamp, 1, 10) AS date,
            event_type,
            COUNT(*) AS count,
            AVG(duration_ms) AS avg_duration_ms,
            COALESCE(SUM(cost_usd), 0) AS total_cost_usd,
            SUM(CASE WHEN status != 'success' THEN 1 ELSE 0 END) AS error_count
        FROM events
        WHERE timestamp >= date('now', ?)
        GROUP BY date, event_type
        ORDER BY date DESC, event_type
    """
    with _connect(db_path) as conn:
        rows = conn.execute(sql, (f"-{days_back} days",)).fetchall()
        return [dict(r) for r in rows]


def materialize_daily_aggregate(db_path: str) -> int:
    """把当日 (含已完成的昨日) 聚合写入 daily_aggregate 表 (cron 每日跑).

    幂等: INSERT OR REPLACE.
    Returns: 写入条数.
    """
    rows = aggregate_daily(db_path, days_back=2)  # 含昨天 + 今天
    if not rows:
        return 0
    with _connect(db_path) as conn:
        for r in rows:
            conn.execute(
                """
                INSERT OR REPLACE INTO daily_aggregate
                    (date, event_type, count, avg_duration_ms, total_cost_usd, error_count)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    r["date"], r["event_type"], r["count"],
                    r["avg_duration_ms"], r["total_cost_usd"], r["error_count"],
                ),
            )
        conn.commit()
    return len(rows)


def prune_old_events(db_path: str, *, keep_days: int = 90) -> int:
    """删 keep_days 天前的原始 events. 返回删除条数.

    daily_aggregate 表保留, 长期趋势从那读.
    """
    if not os.path.isfile(db_path):
        return 0
    with _connect(db_path) as conn:
        cur = conn.execute(
            "DELETE FROM events WHERE timestamp < date('now', ?)",
            (f"-{keep_days} days",),
        )
        deleted = cur.rowcount
        conn.commit()
        # WAL checkpoint, 释放磁盘空间
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    return deleted


def get_summary(db_path: str, *, days: int = 7) -> Dict[str, Any]:
    """一次性查多个常用维度的 summary, 给 dashboard 顶部 KPI 用."""
    if not os.path.isfile(db_path):
        return {"reviews": 0, "errors": 0, "total_cost_usd": 0.0, "avg_review_ms": 0.0}
    with _connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT
                SUM(CASE WHEN event_type = 'review.completed' THEN 1 ELSE 0 END) AS reviews,
                SUM(CASE WHEN status != 'success' THEN 1 ELSE 0 END) AS errors,
                COALESCE(SUM(cost_usd), 0) AS total_cost_usd,
                AVG(CASE WHEN event_type = 'review.completed' THEN duration_ms END) AS avg_review_ms
            FROM events
            WHERE timestamp >= datetime('now', ?)
            """,
            (f"-{days} days",),
        ).fetchone()
        return {
            "reviews": int(row["reviews"] or 0),
            "errors": int(row["errors"] or 0),
            "total_cost_usd": float(row["total_cost_usd"] or 0),
            "avg_review_ms": float(row["avg_review_ms"] or 0),
        }
