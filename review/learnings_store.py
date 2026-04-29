"""信鸽 v2 — Learnings Store (sqlite 后端 + 跨平台文件锁).

设计目标 (生产化 hardening 后):
  - **后端**: 单文件 workspace/learnings.db (sqlite, ACID 写并发安全)
  - **yaml**: 仅作为 export/import 的人可编辑视图 (workspace/learnings/*.yaml)
  - **跨平台 file lock**: 写 sqlite 前抢锁 (msvcrt.locking on Win, fcntl.flock on Unix)
  - **API 兼容**: feedback_v2.py 调用接口不变 (add/list_all/get/delete/update_usage)

数据模型:
  Learning {
    id: str                    # 短 hash (前 8 位)
    trigger_pattern: str       # "当 PRD 涉及收藏功能时"
    instruction: str           # "默认上限 10 条 (VIP 100 条), 不要再报 RC-005"
    scope: str                 # pr_local | team_local | org_global
    source_finding_id: str?
    reviewer: str
    created_at: str            # iso 时间
    last_used: str?
    usage_count: int
    related_rule_ids: list     # JSON-encoded
    dim_keys: list             # JSON-encoded
  }

迁移路径:
  v1 (yaml + index.json) → v2 (sqlite)
  - scripts/migrate_learnings_to_sqlite.py 一次性导入
  - 或调 store.import_yaml(dir_path) 程序化触发

并发场景验证:
  tests/test_learnings_concurrent.py 用 10 thread 并行 add, 确认无 corruption.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import sqlite3
import sys
import time
from dataclasses import dataclass, asdict, field
from typing import Any, Dict, Iterator, List, Literal, Optional

import yaml

from logger import get_logger

log = get_logger("learnings_store")


SCOPES = ("pr_local", "team_local", "org_global")
LearningScope = Literal["pr_local", "team_local", "org_global"]


# ============================================================
# 跨平台文件锁 (sqlite 自带 ACID, 但多进程并发 + 网络盘场景再加一层防御)
# ============================================================

@contextlib.contextmanager
def _file_lock(path: str, timeout: float = 10.0) -> Iterator[None]:
    """跨平台独占写锁; 通过哨兵文件 + msvcrt/fcntl 实现.

    Win: msvcrt.locking(LK_NBLCK) 轮询直到拿到锁或超时
    Unix: fcntl.flock(LOCK_EX | LOCK_NB) 同上
    任一平台导入失败 → fallback 到无锁 (sqlite 自身 ACID 兜底, 仅多进程跨网络盘存在风险).
    """
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    f = open(path, "a+b")
    locked = False
    deadline = time.time() + timeout
    try:
        if sys.platform == "win32":
            try:
                import msvcrt
                while time.time() < deadline:
                    try:
                        msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
                        locked = True
                        break
                    except OSError:
                        time.sleep(0.05)
            except ImportError:
                pass  # fallback 无锁
        else:
            try:
                import fcntl
                while time.time() < deadline:
                    try:
                        fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                        locked = True
                        break
                    except (BlockingIOError, OSError):
                        time.sleep(0.05)
            except ImportError:
                pass
        if not locked:
            log.warning(f"file lock 超时 ({timeout}s) 仍继续, sqlite 自身 ACID 兜底")
        yield
    finally:
        try:
            if locked:
                if sys.platform == "win32":
                    import msvcrt
                    try:
                        f.seek(0)
                        msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
                    except OSError:
                        pass
                else:
                    import fcntl
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        finally:
            f.close()


# ============================================================
# 数据结构
# ============================================================

@dataclass
class Learning:
    """单条 PM 反馈编译出的 learning record"""
    id: str
    trigger_pattern: str
    instruction: str
    scope: str = "pr_local"
    source_finding_id: Optional[str] = None
    reviewer: str = ""
    created_at: str = ""
    last_used: Optional[str] = None
    usage_count: int = 0
    related_rule_ids: List[str] = field(default_factory=list)
    dim_keys: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Learning":
        return cls(
            id=str(data.get("id") or "").strip(),
            trigger_pattern=str(data.get("trigger_pattern") or "").strip(),
            instruction=str(data.get("instruction") or "").strip(),
            scope=str(data.get("scope") or "pr_local").strip(),
            source_finding_id=data.get("source_finding_id"),
            reviewer=str(data.get("reviewer") or "").strip(),
            created_at=str(data.get("created_at") or ""),
            last_used=data.get("last_used"),
            usage_count=int(data.get("usage_count") or 0),
            related_rule_ids=list(data.get("related_rule_ids") or []),
            dim_keys=list(data.get("dim_keys") or []),
        )


# ============================================================
# Store (sqlite 后端)
# ============================================================

class LearningsStore:
    """workspace/learnings.db 的 sqlite 管理 + 跨平台 file lock 保护写路径.

    单例不必要 — 每个 workspace 独立 store. 调用方按需 new.
    """

    DB_FILE = "learnings.db"
    LOCK_FILE = ".learnings.lock"

    def __init__(self, workspace: str):
        if not workspace:
            raise ValueError("workspace 不能为空")
        self.workspace = workspace
        os.makedirs(workspace, exist_ok=True)
        self.db_path = os.path.join(workspace, self.DB_FILE)
        self.lock_path = os.path.join(workspace, self.LOCK_FILE)
        # 保留 yaml 目录作为 export 目标
        self.yaml_dir = os.path.join(workspace, "learnings")
        os.makedirs(self.yaml_dir, exist_ok=True)
        self._ensure_schema()

    # ---------- DDL ----------

    def _connect(self) -> sqlite3.Connection:
        # WAL 模式: 多读单写并发更佳; timeout=10s 给 SQLITE_BUSY 重试空间
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS learnings (
                    id TEXT PRIMARY KEY,
                    trigger_pattern TEXT NOT NULL,
                    instruction TEXT NOT NULL,
                    scope TEXT NOT NULL DEFAULT 'pr_local',
                    source_finding_id TEXT,
                    reviewer TEXT DEFAULT '',
                    created_at TEXT NOT NULL,
                    last_used TEXT,
                    usage_count INTEGER NOT NULL DEFAULT 0,
                    related_rule_ids TEXT NOT NULL DEFAULT '[]',
                    dim_keys TEXT NOT NULL DEFAULT '[]'
                );
                CREATE INDEX IF NOT EXISTS idx_learnings_scope ON learnings(scope);
                CREATE INDEX IF NOT EXISTS idx_learnings_created_at ON learnings(created_at);
                CREATE INDEX IF NOT EXISTS idx_learnings_reviewer ON learnings(reviewer);
                """
            )

    # ---------- ID 生成 ----------

    @staticmethod
    def _gen_id(trigger_pattern: str, instruction: str, reviewer: str) -> str:
        seed = f"{trigger_pattern}|{instruction}|{reviewer}".encode("utf-8")
        return hashlib.sha1(seed).hexdigest()[:8]

    def _resolve_unique_id(self, base_id: str, conn: sqlite3.Connection) -> str:
        cur = conn.execute("SELECT 1 FROM learnings WHERE id = ?", (base_id,))
        if cur.fetchone() is None:
            return base_id
        for suffix in range(2, 100):
            candidate = f"{base_id}-{suffix}"
            cur = conn.execute("SELECT 1 FROM learnings WHERE id = ?", (candidate,))
            if cur.fetchone() is None:
                return candidate
        return f"{base_id}-{int(time.time())}"

    # ---------- 行转换 ----------

    @staticmethod
    def _row_to_learning(row: sqlite3.Row) -> Learning:
        return Learning(
            id=row["id"],
            trigger_pattern=row["trigger_pattern"],
            instruction=row["instruction"],
            scope=row["scope"],
            source_finding_id=row["source_finding_id"],
            reviewer=row["reviewer"] or "",
            created_at=row["created_at"],
            last_used=row["last_used"],
            usage_count=int(row["usage_count"] or 0),
            related_rule_ids=json.loads(row["related_rule_ids"] or "[]"),
            dim_keys=json.loads(row["dim_keys"] or "[]"),
        )

    # ---------- 读 ----------

    def get(self, learning_id: str) -> Optional[Learning]:
        try:
            with self._connect() as conn:
                cur = conn.execute(
                    "SELECT * FROM learnings WHERE id = ?", (learning_id,)
                )
                row = cur.fetchone()
                if row is None:
                    return None
                return self._row_to_learning(row)
        except sqlite3.DatabaseError as e:
            log.warning(f"读 learning {learning_id} 失败: {e}")
            return None

    def list_all(
        self,
        scope: Optional[str] = None,
        dim_key: Optional[str] = None,
        reviewer: Optional[str] = None,
    ) -> List[Learning]:
        sql = "SELECT * FROM learnings WHERE 1=1"
        params: List[Any] = []
        if scope:
            sql += " AND scope = ?"
            params.append(scope)
        if reviewer:
            sql += " AND reviewer = ?"
            params.append(reviewer)
        sql += " ORDER BY created_at DESC"
        results: List[Learning] = []
        try:
            with self._connect() as conn:
                for row in conn.execute(sql, params):
                    learning = self._row_to_learning(row)
                    # dim_key 过滤在 Python 侧做 (列表 IN 查询 sqlite 不直接支持)
                    if dim_key and dim_key not in learning.dim_keys:
                        continue
                    results.append(learning)
        except sqlite3.DatabaseError as e:
            log.warning(f"list_all 失败: {e}")
        return results

    # ---------- 写 (file lock 保护) ----------

    def add(
        self,
        trigger_pattern: str,
        instruction: str,
        *,
        scope: str = "pr_local",
        source_finding_id: Optional[str] = None,
        reviewer: str = "",
        related_rule_ids: Optional[List[str]] = None,
        dim_keys: Optional[List[str]] = None,
    ) -> Learning:
        if not trigger_pattern or not instruction:
            raise ValueError("trigger_pattern 和 instruction 不能为空")
        if scope not in SCOPES:
            log.warning(f"scope={scope} 非法, 兜底为 pr_local")
            scope = "pr_local"

        base_id = self._gen_id(trigger_pattern, instruction, reviewer)
        created_at = time.strftime("%Y-%m-%dT%H:%M:%S")
        rrids = list(related_rule_ids or [])
        dks = list(dim_keys or [])

        with _file_lock(self.lock_path):
            with self._connect() as conn:
                learning_id = self._resolve_unique_id(base_id, conn)
                conn.execute(
                    """
                    INSERT INTO learnings (
                        id, trigger_pattern, instruction, scope,
                        source_finding_id, reviewer, created_at,
                        last_used, usage_count, related_rule_ids, dim_keys
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        learning_id,
                        trigger_pattern.strip(),
                        instruction.strip(),
                        scope,
                        source_finding_id,
                        reviewer.strip(),
                        created_at,
                        None,
                        0,
                        json.dumps(rrids, ensure_ascii=False),
                        json.dumps(dks, ensure_ascii=False),
                    ),
                )
                conn.commit()

        learning = Learning(
            id=learning_id,
            trigger_pattern=trigger_pattern.strip(),
            instruction=instruction.strip(),
            scope=scope,
            source_finding_id=source_finding_id,
            reviewer=reviewer.strip(),
            created_at=created_at,
            usage_count=0,
            related_rule_ids=rrids,
            dim_keys=dks,
        )
        log.info(f"learning 已添加: id={learning_id} reviewer={reviewer}")
        return learning

    def update_usage(self, learning_id: str) -> bool:
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        with _file_lock(self.lock_path):
            with self._connect() as conn:
                cur = conn.execute(
                    """
                    UPDATE learnings
                    SET usage_count = usage_count + 1, last_used = ?
                    WHERE id = ?
                    """,
                    (now, learning_id),
                )
                conn.commit()
                return cur.rowcount > 0

    def delete(self, learning_id: str) -> bool:
        with _file_lock(self.lock_path):
            with self._connect() as conn:
                cur = conn.execute(
                    "DELETE FROM learnings WHERE id = ?", (learning_id,)
                )
                conn.commit()
                return cur.rowcount > 0

    # ---------- yaml export / import (人可读视图) ----------

    def export_yaml(self, out_dir: Optional[str] = None) -> int:
        """把 sqlite 全量 dump 到 <out_dir>/<id>.yaml. 返回写出条数."""
        target = out_dir or self.yaml_dir
        os.makedirs(target, exist_ok=True)
        count = 0
        for learning in self.list_all():
            path = os.path.join(target, f"{learning.id}.yaml")
            try:
                with open(path, "w", encoding="utf-8") as f:
                    yaml.safe_dump(
                        learning.to_dict(),
                        f,
                        allow_unicode=True,
                        sort_keys=False,
                    )
                count += 1
            except OSError as e:
                log.warning(f"导出 {learning.id} 失败: {e}")
        return count

    def import_yaml(self, src_dir: Optional[str] = None, *, overwrite: bool = False) -> int:
        """扫 src_dir 下所有 yaml 文件 import 到 sqlite. 返回成功条数."""
        src = src_dir or self.yaml_dir
        if not os.path.isdir(src):
            return 0
        count = 0
        for fn in os.listdir(src):
            if not fn.endswith(".yaml") or fn.startswith("."):
                continue
            path = os.path.join(src, fn)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                if not isinstance(data, dict) or not data.get("id"):
                    continue
                learning = Learning.from_dict(data)
                with _file_lock(self.lock_path):
                    with self._connect() as conn:
                        cur = conn.execute(
                            "SELECT 1 FROM learnings WHERE id = ?", (learning.id,)
                        )
                        exists = cur.fetchone() is not None
                        if exists and not overwrite:
                            continue
                        if exists:
                            conn.execute("DELETE FROM learnings WHERE id = ?", (learning.id,))
                        conn.execute(
                            """
                            INSERT INTO learnings (
                                id, trigger_pattern, instruction, scope,
                                source_finding_id, reviewer, created_at,
                                last_used, usage_count, related_rule_ids, dim_keys
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                learning.id,
                                learning.trigger_pattern,
                                learning.instruction,
                                learning.scope,
                                learning.source_finding_id,
                                learning.reviewer,
                                learning.created_at or time.strftime("%Y-%m-%dT%H:%M:%S"),
                                learning.last_used,
                                learning.usage_count,
                                json.dumps(learning.related_rule_ids, ensure_ascii=False),
                                json.dumps(learning.dim_keys, ensure_ascii=False),
                            ),
                        )
                        conn.commit()
                count += 1
            except (yaml.YAMLError, OSError, sqlite3.DatabaseError) as e:
                log.warning(f"import {fn} 失败: {e}")
        log.info(f"yaml import 完成: {count} 条")
        return count


# ============================================================
# 启发式匹配 (按 PRD 内容选相关 learning 注入) — 接口不变
# ============================================================

def find_relevant_learnings(
    store: LearningsStore,
    prd_content: str,
    dim_key: str,
    *,
    max_count: int = 5,
) -> List[Learning]:
    """根据 trigger_pattern 与 PRD 内容做关键词匹配, 选最相关的 learnings."""
    candidates = [
        l for l in store.list_all()
        if not l.dim_keys or dim_key in l.dim_keys
    ]
    if not candidates:
        return []

    STOP_WORDS = {
        "当", "时", "的", "了", "是", "和", "或", "在", "及", "需要", "不要",
        "请", "如", "如果", "PRD", "prd",
    }

    def _keywords(text: str) -> List[str]:
        import re
        tokens: List[str] = []
        for chunk in re.findall(r"[\u4e00-\u9fa5]+|[A-Za-z][\w\-]+", text or ""):
            if re.match(r"[A-Za-z]", chunk):
                if len(chunk) >= 2 and chunk not in STOP_WORDS:
                    tokens.append(chunk)
            else:
                if len(chunk) >= 2:
                    for i in range(len(chunk) - 1):
                        bigram = chunk[i:i+2]
                        if bigram not in STOP_WORDS:
                            tokens.append(bigram)
        return tokens

    prd_lower = (prd_content or "").lower()
    scored: List[tuple] = []
    for learning in candidates:
        kws = _keywords(learning.trigger_pattern)
        hits = sum(1 for kw in kws if kw.lower() in prd_lower)
        if hits == 0:
            continue
        prio = {"org_global": 0, "team_local": 1, "pr_local": 2}.get(learning.scope, 2)
        score = hits * 10 + min(learning.usage_count, 10)
        scored.append((prio, -score, learning))

    scored.sort(key=lambda t: (t[0], t[1]))
    return [t[2] for t in scored[:max_count]]
