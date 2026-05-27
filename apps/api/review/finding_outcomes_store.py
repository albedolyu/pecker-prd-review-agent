"""Pecker PM accept-rate 在线度量 store.

核心目标 (CodeRabbit "online F1 acceptance > offline gold-set" 哲学):
  - report 渲染后 PM 对每条 finding 的反馈 (accept/reject/edit) 写到 sqlite
  - 聚合每条 rule 的 accept_rate, 用于:
      * 自动告警 (low accept rate → 规则待优化; high accept rate → 可固化为 learning)
      * 苍鹰交叉校验时优先关注 high-reject rule_id (倾向标 fp)
      * 信鸽 v2 学习记录的反向触发条件

设计:
  - sqlite 单表 finding_outcomes, 索引 rule_id 用于聚合
  - 跨进程并发写: O_CREAT|O_EXCL 文件锁 (与 wiki_lock 相同套路, 不引第三方包)
  - Windows GBK 兼容: 所有 print/log 走 ascii 安全, 文件写 utf-8

表结构 finding_outcomes:
    id           autoincrement
    finding_id   报告里的 R-001 / RC-005 等
    rule_id      规则编号 (TM-001 / RC-005), null 时按 finding_id 兜底分组
    outcome      accept | reject | edit
    pm_name      接受/驳回的 PM
    timestamp    iso 字符串
    reason       PM 写的理由 (edit 模式必填)
    workspace    所属 workspace 名 (跨工作区分析用)
    prd_name     所属 PRD (单 PRD 累加分析用)
    severity     报告时的 severity (must/should/could)

聚合 API:
  - get_rule_accept_rate(rule_id, days=30) -> {accept, reject, edit, total, accept_rate}
  - get_all_rules_metrics(days=30) -> {rule_id: metrics}
  - get_pm_accept_history(pm_name, days=30) -> List[outcome]
  - get_low_accept_rules(threshold=0.3, min_count=5) -> List[(rule_id, rate, count)]
  - get_high_accept_rules(threshold=0.95, min_count=5) -> List[(rule_id, rate, count)]
"""
from __future__ import annotations

import contextlib
import os
import sqlite3
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from logger import get_logger
from api.sanitize import redact_prd_content, redact_text

log = get_logger("finding_outcomes")


# ============================================================
# 文件锁 (跨进程互斥) — 抄 wiki_lock.py 套路, 不引第三方
# ============================================================

_LOCK_TIMEOUT = 30
_LOCK_STALE = 120


@contextlib.contextmanager
def _store_write_lock(db_path: str):
    """sqlite 写入锁. WAL 模式下 sqlite 自己能处理并发, 但跨进程
    promote / migration 仍需互斥 — 留这层兜底."""
    lock_path = db_path + ".lock"
    start = time.time()
    acquired = False
    while time.time() - start < _LOCK_TIMEOUT:
        if os.path.exists(lock_path):
            try:
                if time.time() - os.path.getmtime(lock_path) > _LOCK_STALE:
                    os.remove(lock_path)
            except OSError:
                pass
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            acquired = True
            break
        except (FileExistsError, PermissionError, OSError):
            # Windows 下 O_EXCL 失败可能抛 PermissionError 或 OSError, 全部当锁未拿到
            time.sleep(0.05)
    try:
        if not acquired:
            log.warning(f"finding_outcomes store 锁获取超时 ({db_path}), 继续 (并发风险)")
        yield
    finally:
        if acquired:
            try:
                os.remove(lock_path)
            except OSError:
                pass


# ============================================================
# Store 主体
# ============================================================


_DEFAULT_DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "review",
    "finding_outcomes.db",
)


def _resolve_db_path(db_path: Optional[str] = None) -> str:
    return db_path or os.environ.get("PECKER_OUTCOMES_DB", _DEFAULT_DB_PATH)


def _get_conn(db_path: str) -> sqlite3.Connection:
    """sqlite 连接 + WAL 模式 (并发读写更友好)."""
    conn = sqlite3.connect(db_path, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def init_store(db_path: Optional[str] = None) -> None:
    """建表 + 索引. 幂等可重复跑."""
    path = _resolve_db_path(db_path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with _store_write_lock(path), _get_conn(path) as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS finding_outcomes (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                finding_id  TEXT NOT NULL,
                rule_id     TEXT,
                outcome     TEXT NOT NULL CHECK (outcome IN ('accept', 'reject', 'edit')),
                pm_name     TEXT,
                timestamp   TEXT NOT NULL,
                reason      TEXT,
                workspace   TEXT,
                prd_name    TEXT,
                severity    TEXT,
                evidence_content TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_outcomes_rule_id ON finding_outcomes(rule_id);
            CREATE INDEX IF NOT EXISTS idx_outcomes_timestamp ON finding_outcomes(timestamp);
            CREATE INDEX IF NOT EXISTS idx_outcomes_pm ON finding_outcomes(pm_name);
            CREATE INDEX IF NOT EXISTS idx_outcomes_finding_id ON finding_outcomes(finding_id);
        """)
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(finding_outcomes)").fetchall()}
        if "evidence_content" not in columns:
            conn.execute("ALTER TABLE finding_outcomes ADD COLUMN evidence_content TEXT")
        conn.commit()


# ============================================================
# 写入
# ============================================================


_VALID_OUTCOMES = {"accept", "reject", "edit"}


def record_outcome(
    finding_id: str,
    outcome: str,
    *,
    rule_id: Optional[str] = None,
    pm_name: Optional[str] = None,
    reason: Optional[str] = None,
    workspace: Optional[str] = None,
    prd_name: Optional[str] = None,
    severity: Optional[str] = None,
    evidence_content: Optional[str] = None,
    prd_body: Optional[str] = None,
    db_path: Optional[str] = None,
) -> int:
    """写一条 outcome. 返回新行 id.

    设计: 一条 finding 可以被同一 PM 反复改写 outcome (PM 反悔),
    每次都是新行不覆盖, 聚合时取最新 outcome 即可 (留审计轨迹)。
    """
    if outcome not in _VALID_OUTCOMES:
        raise ValueError(f"outcome 必须是 {_VALID_OUTCOMES}, got {outcome}")
    if not finding_id:
        raise ValueError("finding_id 必填")

    path = _resolve_db_path(db_path)
    init_store(path)
    ts = datetime.now().isoformat(timespec="seconds")
    safe_evidence = _sanitize_evidence_content(evidence_content, prd_body or "")
    with _store_write_lock(path), _get_conn(path) as conn:
        cur = conn.execute(
            """INSERT INTO finding_outcomes
               (finding_id, rule_id, outcome, pm_name, timestamp, reason, workspace, prd_name, severity, evidence_content)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                finding_id,
                rule_id,
                outcome,
                pm_name,
                ts,
                reason,
                workspace,
                prd_name,
                severity,
                safe_evidence,
            ),
        )
        conn.commit()
        new_id = cur.lastrowid or 0
    log.info(f"outcome 记录: finding={finding_id} rule={rule_id} outcome={outcome} pm={pm_name}")
    return new_id


def _sanitize_evidence_content(value: Optional[str], prd_body: str = "") -> str:
    if not value:
        return ""
    text = redact_text(str(value))
    if prd_body:
        text = str(redact_prd_content(text, prd_body))
    return text[:500]


# ============================================================
# 聚合查询
# ============================================================


def _window_clause(days: Optional[int]) -> Tuple[str, List[Any]]:
    """生成滑动窗口 WHERE 子句."""
    if days is None or days <= 0:
        return "", []
    cutoff = (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")
    return " AND timestamp >= ?", [cutoff]


def get_rule_accept_rate(
    rule_id: str,
    days: Optional[int] = 30,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """单条 rule 在 days 窗口内的 accept_rate.

    返回:
        {rule_id, accept, reject, edit, total, accept_rate, latest_ts}
        accept_rate = (accept + edit*0.5) / total
        edit 视为 "半接受" — PM 改写后 finding 仍有效, 只是表达不准
    """
    path = _resolve_db_path(db_path)
    init_store(path)
    win_sql, win_args = _window_clause(days)
    with _get_conn(path) as conn:
        rows = conn.execute(
            f"""SELECT outcome, COUNT(*) as cnt, MAX(timestamp) as latest
                FROM finding_outcomes
                WHERE rule_id = ? {win_sql}
                GROUP BY outcome""",
            [rule_id] + win_args,
        ).fetchall()
    counts = {"accept": 0, "reject": 0, "edit": 0}
    latest = ""
    for r in rows:
        counts[r["outcome"]] = r["cnt"]
        if r["latest"] and r["latest"] > latest:
            latest = r["latest"]
    total = sum(counts.values())
    accept_rate = (counts["accept"] + counts["edit"] * 0.5) / total if total else 0.0
    return {
        "rule_id": rule_id,
        "accept": counts["accept"],
        "reject": counts["reject"],
        "edit": counts["edit"],
        "total": total,
        "accept_rate": round(accept_rate, 4),
        "latest_ts": latest,
    }


def get_all_rules_metrics(
    days: Optional[int] = 30,
    db_path: Optional[str] = None,
) -> Dict[str, Dict[str, Any]]:
    """所有 rule 的聚合 metrics."""
    path = _resolve_db_path(db_path)
    init_store(path)
    win_sql, win_args = _window_clause(days)
    with _get_conn(path) as conn:
        rows = conn.execute(
            f"""SELECT rule_id, outcome, COUNT(*) as cnt
                FROM finding_outcomes
                WHERE rule_id IS NOT NULL {win_sql}
                GROUP BY rule_id, outcome""",
            win_args,
        ).fetchall()
    out: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        rid = r["rule_id"]
        if rid not in out:
            out[rid] = {"rule_id": rid, "accept": 0, "reject": 0, "edit": 0, "total": 0}
        out[rid][r["outcome"]] = r["cnt"]
        out[rid]["total"] += r["cnt"]
    for m in out.values():
        m["accept_rate"] = round(
            (m["accept"] + m["edit"] * 0.5) / m["total"] if m["total"] else 0.0,
            4,
        )
    return out


def get_pm_accept_history(
    pm_name: str,
    days: Optional[int] = 30,
    db_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """单个 PM 在窗口内的所有 outcome 记录 (按时间倒序)."""
    path = _resolve_db_path(db_path)
    init_store(path)
    win_sql, win_args = _window_clause(days)
    with _get_conn(path) as conn:
        rows = conn.execute(
            f"""SELECT * FROM finding_outcomes
                WHERE pm_name = ? {win_sql}
                ORDER BY timestamp DESC LIMIT 500""",
            [pm_name] + win_args,
        ).fetchall()
    return [dict(r) for r in rows]


def get_pm_accept_summary(
    days: Optional[int] = 30,
    db_path: Optional[str] = None,
) -> Dict[str, Dict[str, Any]]:
    """按 PM 聚合 — 看每个 PM 的接受口味."""
    path = _resolve_db_path(db_path)
    init_store(path)
    win_sql, win_args = _window_clause(days)
    with _get_conn(path) as conn:
        rows = conn.execute(
            f"""SELECT pm_name, outcome, COUNT(*) as cnt
                FROM finding_outcomes
                WHERE pm_name IS NOT NULL {win_sql}
                GROUP BY pm_name, outcome""",
            win_args,
        ).fetchall()
    out: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        pm = r["pm_name"]
        if pm not in out:
            out[pm] = {"pm_name": pm, "accept": 0, "reject": 0, "edit": 0, "total": 0}
        out[pm][r["outcome"]] = r["cnt"]
        out[pm]["total"] += r["cnt"]
    for m in out.values():
        m["accept_rate"] = round(
            (m["accept"] + m["edit"] * 0.5) / m["total"] if m["total"] else 0.0,
            4,
        )
    return out


def get_low_accept_rules(
    threshold: float = 0.3,
    min_count: int = 5,
    days: Optional[int] = 30,
    db_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """accept_rate < threshold 且样本量 >= min_count 的 rule (待优化)."""
    metrics = get_all_rules_metrics(days=days, db_path=db_path)
    bad = [
        m for m in metrics.values()
        if m["total"] >= min_count and m["accept_rate"] < threshold
    ]
    return sorted(bad, key=lambda m: m["accept_rate"])


def get_high_accept_rules(
    threshold: float = 0.95,
    min_count: int = 5,
    days: Optional[int] = 30,
    db_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """accept_rate > threshold 的 rule (可固化为 learning)."""
    metrics = get_all_rules_metrics(days=days, db_path=db_path)
    good = [
        m for m in metrics.values()
        if m["total"] >= min_count and m["accept_rate"] >= threshold
    ]
    return sorted(good, key=lambda m: -m["accept_rate"])


def get_recent_outcomes(
    limit: int = 100,
    db_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """最近 N 条 outcome (调试 / dashboard 用)."""
    path = _resolve_db_path(db_path)
    init_store(path)
    with _get_conn(path) as conn:
        rows = conn.execute(
            "SELECT * FROM finding_outcomes ORDER BY timestamp DESC LIMIT ?",
            [limit],
        ).fetchall()
    return [dict(r) for r in rows]


def get_finding_latest_outcome(
    finding_id: str,
    db_path: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """取一条 finding 最新 outcome (PM 反悔时按最新算)."""
    path = _resolve_db_path(db_path)
    init_store(path)
    with _get_conn(path) as conn:
        row = conn.execute(
            """SELECT * FROM finding_outcomes
               WHERE finding_id = ?
               ORDER BY timestamp DESC LIMIT 1""",
            [finding_id],
        ).fetchone()
    return dict(row) if row else None


def trend_buckets(
    rule_id: Optional[str] = None,
    days: int = 30,
    bucket_days: int = 7,
    db_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """按 bucket_days 划分时间桶, 返回每个桶的 accept/reject/total."""
    path = _resolve_db_path(db_path)
    init_store(path)
    out: List[Dict[str, Any]] = []
    now = datetime.now()
    with _get_conn(path) as conn:
        for i in range(0, days, bucket_days):
            end = now - timedelta(days=i)
            start = end - timedelta(days=bucket_days)
            sql = """SELECT outcome, COUNT(*) cnt FROM finding_outcomes
                     WHERE timestamp >= ? AND timestamp < ?"""
            args: List[Any] = [start.isoformat(timespec="seconds"), end.isoformat(timespec="seconds")]
            if rule_id:
                sql += " AND rule_id = ?"
                args.append(rule_id)
            sql += " GROUP BY outcome"
            rows = conn.execute(sql, args).fetchall()
            counts = {"accept": 0, "reject": 0, "edit": 0}
            for r in rows:
                counts[r["outcome"]] = r["cnt"]
            total = sum(counts.values())
            out.append({
                "bucket_start": start.strftime("%Y-%m-%d"),
                "bucket_end": end.strftime("%Y-%m-%d"),
                "accept": counts["accept"],
                "reject": counts["reject"],
                "edit": counts["edit"],
                "total": total,
                "accept_rate": round(
                    (counts["accept"] + counts["edit"] * 0.5) / total if total else 0.0,
                    4,
                ),
            })
    out.reverse()  # 旧→新
    return out
