"""Admin-only usage dashboard endpoint."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Query, status

from api.deps import get_current_user, get_project_root
from api.usage_summary import build_usage_summary

router = APIRouter(prefix="/admin", tags=["admin"])


def _require_admin(user: dict = Depends(get_current_user)) -> dict:
    admins = {
        value.strip()
        for value in os.environ.get("PECKER_ADMIN_USERS", "").split(",")
        if value.strip()
    }
    if not admins:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="后台看板需要先配置 PECKER_ADMIN_USERS",
        )
    if user.get("reviewer", "") not in admins:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="只有管理员可以查看团队使用情况",
        )
    return user


@router.get("/usage")
async def get_admin_usage(
    days: int = Query(7, ge=1, le=90, description="统计最近 N 天"),
    _user: dict = Depends(_require_admin),
    project_root: Path = Depends(get_project_root),
) -> Dict[str, Any]:
    return build_usage_summary(project_root=project_root, days=days)

