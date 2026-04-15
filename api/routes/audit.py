"""POST /api/audit — 前端事件审计日志,追加到 logs/user_actions.jsonl

复用 app.py Step 2.5 的 `_audit_log` 逻辑。
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
    """追加一行 jsonl 审计日志。失败静默(不阻塞前端)。"""
    try:
        log_dir = project_root / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / "user_actions.jsonl"

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
    """数某个 reviewer 今天 review_started 次数,给顶部 banner 用。"""
    try:
        log_path = project_root / "logs" / "user_actions.jsonl"
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
