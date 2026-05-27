"""Personal review-history endpoint.

This is intentionally not an admin endpoint: each PM can only see their own
metadata-level history. The response excludes PRD body and raw materials.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, Depends, Query

from api.deps import get_current_user, get_project_root
from api.usage_summary import build_personal_review_history

router = APIRouter(prefix="/reviews", tags=["reviews"])


@router.get("/history")
async def get_my_review_history(
    days: int = Query(30, ge=1, le=90, description="统计最近 N 天"),
    limit: int = Query(50, ge=1, le=100, description="最多返回多少条记录"),
    user: dict = Depends(get_current_user),
    project_root: Path = Depends(get_project_root),
) -> Dict[str, Any]:
    return build_personal_review_history(
        project_root=project_root,
        reviewer=str(user.get("reviewer") or ""),
        days=days,
        limit=limit,
    )
