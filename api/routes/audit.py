"""POST /api/audit — 前端事件审计日志,按日期轮转到 logs/user_actions_YYYYMMDD.jsonl

2026-04-23 按日轮转: 之前写单一 user_actions.jsonl 无上限, 内测几个月后单文件
会膨胀到 MB 级. 改成按天切分:
- logs/user_actions_20260423.jsonl  (今天)
- logs/user_actions_20260424.jsonl  (明天)
- ...

读取侧(如 count_today_reviews / stability_metrics)扫匹配 pattern 即可.
旧的 user_actions.jsonl 保留读取兼容, 新写入走新文件.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.deps import get_current_user, get_project_root

router = APIRouter(tags=["audit"])


class AuditEvent(BaseModel):
    event: str = Field(..., description="事件类型,如 review_started / wiki_saved / feishu_pushed")
    workspace: str = ""
    prd_name: str = ""
    extra: Dict[str, Any] = Field(default_factory=dict, description="额外元数据")


@router.post("/audit")
async def log_audit(
    ev: AuditEvent,
    user: dict = Depends(get_current_user),
    project_root: Path = Depends(get_project_root),
):
    """追加一行 jsonl 审计日志, 按日期轮转. 失败静默(不阻塞前端)."""
    try:
        log_dir = project_root / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        # 按日切分: user_actions_YYYYMMDD.jsonl
        day_tag = time.strftime("%Y%m%d")
        log_path = log_dir / f"user_actions_{day_tag}.jsonl"

        entry = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "event": ev.event,
            "reviewer": user.get("reviewer", "unknown"),
            "workspace": ev.workspace,
            "prd_name": ev.prd_name,
            **ev.extra,
        }

        # append 单行 < 4KB 是原子的,无需文件锁
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        # 审计日志失败绝不阻塞前端
        return {"status": "logged_locally", "error": str(e)[:100]}

    return {"status": "ok"}


@router.get("/audit/today/{reviewer}")
async def count_today_reviews(
    reviewer: str,
    project_root: Path = Depends(get_project_root),
):
    """数某个 reviewer 今天 review_started 次数,给顶部 banner 用.

    2026-04-23 起读今天 user_actions_<today>.jsonl (按日轮转后), 不存在时
    兼容读旧的 user_actions.jsonl(未轮转前历史数据)."""
    try:
        logs_dir = project_root / "logs"
        day_tag = time.strftime("%Y%m%d")
        today_path = logs_dir / f"user_actions_{day_tag}.jsonl"
        legacy_path = logs_dir / "user_actions.jsonl"

        # 新路径不存在且旧路径存在 → 读旧的(向后兼容迁移期)
        log_path = today_path if today_path.is_file() else legacy_path
        if not log_path.is_file():
            return {"reviewer": reviewer, "count": 0}

        today = time.strftime("%Y-%m-%d")
        count = 0
        with open(log_path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                    if (rec.get("event") == "review_started"
                            and rec.get("reviewer") == reviewer
                            and rec.get("ts", "").startswith(today)):
                        count += 1
                except json.JSONDecodeError:
                    continue
        return {"reviewer": reviewer, "count": count}
    except Exception:
        return {"reviewer": reviewer, "count": 0}
