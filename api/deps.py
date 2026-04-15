"""FastAPI 依赖注入层 — 全局 semaphore + 共享 Claude client 单例。"""
from __future__ import annotations

import asyncio
import os
from functools import lru_cache
from pathlib import Path

from fastapi import Depends, HTTPException, Request, status


# ============================================================
# 全局并发 semaphore(对应 Streamlit Step 2.3 的 threading.Semaphore)
# ============================================================

_MAX_CONCURRENT = int(os.environ.get("PECKER_MAX_CONCURRENT", "2"))
review_semaphore = asyncio.Semaphore(_MAX_CONCURRENT)


def get_max_concurrent() -> int:
    """当前进程的并发上限,用于前端展示和排队 UI。"""
    return _MAX_CONCURRENT


# ============================================================
# Claude Code CLI Client 单例
# ============================================================

@lru_cache(maxsize=1)
def get_client():
    """返回 ClaudeCodeCLIClient 单例,整个 FastAPI 进程共享。

    api_adapter.create_client 内部已经忽略 api_key/base_url,只走本地 CC CLI。
    """
    from api_adapter import create_client
    return create_client()


# ============================================================
# 项目根目录 helper
# ============================================================

_PROJECT_ROOT = Path(__file__).parent.parent


def get_project_root() -> Path:
    """prd review 项目根目录(api/ 的上一级)"""
    return _PROJECT_ROOT


def get_workspace_dir(workspace_name: str) -> Path:
    """从 workspace 名得到完整路径,校验目录存在且是 workspace-* 格式。

    防止前端传 `../../etc/passwd` 之类的路径注入。
    """
    if not workspace_name.startswith("workspace-"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"非法 workspace 名: {workspace_name}(必须 workspace-* 开头)",
        )
    # 禁止 .. / / \\ 之类的路径穿越
    if "/" in workspace_name or "\\" in workspace_name or ".." in workspace_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"非法 workspace 名: {workspace_name}(含非法字符)",
        )
    ws_path = _PROJECT_ROOT / workspace_name
    if not ws_path.is_dir():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"workspace 不存在: {workspace_name}",
        )
    return ws_path


# ============================================================
# 当前登录用户 helper(占位,A12 auth 中间件实现后填充)
# ============================================================

def get_current_user(request: Request) -> dict:
    """从 JWT cookie 解析当前 reviewer + readonly 状态。

    A12 之前的占位实现:直接从请求 header `X-Reviewer` 读(开发用)。
    """
    # 占位:A12 里替换为 JWT cookie 解析
    reviewer = request.headers.get("x-reviewer", "")
    if not reviewer:
        # 开发模式允许未登录访问,生产模式 A12 会改成 401
        reviewer = "anonymous"

    readonly_list = os.environ.get("PECKER_READONLY_USERS", "")
    readonly_users = {u.strip() for u in readonly_list.split(",") if u.strip()}
    is_readonly = reviewer in readonly_users

    return {
        "reviewer": reviewer,
        "readonly": is_readonly,
    }


def require_writer(user: dict = Depends(get_current_user)) -> dict:
    """只读用户禁止访问此端点,返回 403。"""
    if user.get("readonly"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="只读用户不能执行此操作",
        )
    return user
