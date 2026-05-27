"""GET /api/metrics — 运维指标端点 (admin 限定).

数据源:
- 稳定性指标: 复用 scripts.stability_metrics (扫 workspace-*/output/sessions/*.jsonl)
- 预算快照: api.budget_gate.budget_status_snapshot (扫 logs/daily_cost_*.jsonl)

设计: 纯只读, 零 LLM 调用. 给内测阶段的管理员回答 "今天跑了几次 / 失败几次 /
平均耗时 / 烧了多少钱" — gate v2 第 5 类运维要求.

权限: PECKER_ADMIN_USERS (和 workspace_acl bypass 用同一白名单). 非 admin 403.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Query, status

from api.budget_gate import budget_status_snapshot
from api.deps import get_current_user, get_project_root

# scripts 已作为 package 声明在 pyproject.toml (2026-04-24 修复), 走标准 import
# 路径, 不再需要 sys.path 黑魔法 — 之前的 "parent.parent.parent" 在 pip install
# 后 __file__ 指向 site-packages 完全找不到 scripts 目录
from scripts.stability_metrics import (
    _filter_by_days,
    _iter_session_files,
    _parse_session,
    compute_metrics,
)

router = APIRouter(tags=["metrics"])


def _require_admin(user: dict = Depends(get_current_user)) -> dict:
    """只允许 PECKER_ADMIN_USERS 里的用户. 非 admin 403."""
    admins = {
        u.strip() for u in os.environ.get("PECKER_ADMIN_USERS", "").split(",") if u.strip()
    }
    if not admins:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="运维接口需 PECKER_ADMIN_USERS 环境变量白名单, 请联系管理员配置",
        )
    if user.get("reviewer", "") not in admins:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="运维接口仅 admin 可访问",
        )
    return user


@router.get("/metrics")
async def get_metrics(
    days: int = Query(7, ge=1, le=90, description="统计最近 N 天 (1-90)"),
    workspace: str = Query("", description="只看某个 workspace, 空=全部"),
    user: dict = Depends(_require_admin),
    project_root: Path = Depends(get_project_root),
) -> Dict[str, Any]:
    """返回稳定性 + 预算组合指标, 给运维面板用.

    返回结构 (给前端 dashboard / 自研监控消费):
    {
      "window_days": 7,
      "workspace_filter": "" | "workspace-foo",
      "stability": { total_runs, completed, failed, zero_items_rate, p95_duration_ms, ... },
      "budget": { enabled, limit, spent, remaining, warn, today_count }
    }
    """
    # 稳定性
    runs = []
    for path in _iter_session_files(project_root, workspace or None):
        summary = _parse_session(path)
        if summary:
            runs.append(summary)
    runs = _filter_by_days(runs, days)
    stability = compute_metrics(runs)

    # 预算
    budget = budget_status_snapshot(project_root)

    return {
        "window_days": days,
        "workspace_filter": workspace or None,
        "stability": stability,
        "budget": budget,
    }
