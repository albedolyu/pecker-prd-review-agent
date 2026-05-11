"""GET /api/workspaces — 返回所有可用的 workspace-* 目录,给前端 selectbox 用。"""
from __future__ import annotations

import os
from pathlib import Path
from typing import List

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from api.deps import get_current_user, get_external_workspace_roots, get_project_root
from api.workspace_acl import can_access_workspace

router = APIRouter(tags=["workspaces"])


class WorkspaceInfo(BaseModel):
    """单个 workspace 的元信息,给前端下拉框展示。"""
    name: str = Field(..., description="workspace 目录名,如 workspace-对外投资")
    display_name: str = Field(..., description="去掉 workspace- 前缀的人类可读名字")
    path: str = Field(..., description="完整绝对路径")
    has_prd_dir: bool = Field(..., description="workspace/prd/ 目录是否存在")
    has_wiki_dir: bool = Field(..., description="workspace/wiki/ 目录是否存在")
    wiki_page_count: int = Field(0, description="wiki 目录下的 .md 文件数")
    prd_count: int = Field(0, description="prd 目录下的 .md 文件数")


@router.get("/workspaces", response_model=List[WorkspaceInfo])
async def list_workspaces(
    project_root: Path = Depends(get_project_root),
    user: dict = Depends(get_current_user),
):
    """扫项目根下的 workspace-* 目录列表。

    排序: 按字典序。前端拿到后自己决定默认选哪个(通常用 URL query param 或 zustand 持久化)。
    """
    results: List[WorkspaceInfo] = []
    seen: set[str] = set()
    external_roots = get_external_workspace_roots()
    roots = [*external_roots, project_root]
    for root in roots:
        if not root.is_dir():
            continue
        local_sample_only = bool(external_roots) and root == project_root
        for name in sorted(os.listdir(root)):
            full = root / name
            if not name.startswith("workspace-") or not full.is_dir():
                continue
            if local_sample_only and name != "workspace-sample":
                continue
            if name in seen:
                continue

            # ACL: 过滤掉当前用户无权访问的 workspace
            if not can_access_workspace(full, user):
                continue

            prd_dir = full / "prd"
            wiki_dir = full / "wiki"

            wiki_count = 0
            if wiki_dir.is_dir():
                wiki_count = sum(1 for _ in wiki_dir.glob("*.md"))

            prd_count = 0
            if prd_dir.is_dir():
                prd_count = sum(1 for _ in prd_dir.glob("*.md"))

            seen.add(name)
            results.append(WorkspaceInfo(
                name=name,
                display_name=name[len("workspace-"):],
                path=str(full),
                has_prd_dir=prd_dir.is_dir(),
                has_wiki_dir=wiki_dir.is_dir(),
                wiki_page_count=wiki_count,
                prd_count=prd_count,
            ))
    return results
