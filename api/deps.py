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
# 当前登录用户 helper(A12: 从 pecker_session JWT cookie 解析)
# ============================================================

def get_current_user(request: Request) -> dict:
    """从 pecker_session JWT cookie 解析当前 reviewer + readonly 状态。

    认证契约:
    - 缺失 cookie → 401 未登录(不再静默 fallback 到 anonymous)
    - HMAC 签名不对或过期 → 401 登录已失效
    - 解析成功 → 返回 JWT payload 里的 reviewer 和 readonly 字段
      readonly 由 auth.login 在签发时根据 PECKER_READONLY_USERS 决定,
      服务端签发后客户端无法篡改(HS256 HMAC 保护)。
    """
    from jose import JWTError, jwt

    token = request.cookies.get("pecker_session", "")
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未登录")

    secret = os.environ.get("PECKER_JWT_SECRET", "")
    if not secret or len(secret) < 16:
        # 理论上 main.lifespan 已经拦住了,这里是双保险
        raise HTTPException(status_code=500, detail="PECKER_JWT_SECRET 未配置或过短")

    try:
        payload = jwt.decode(token, secret, algorithms=["HS256"])
    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"登录已失效: {str(e)[:60]}",
        )

    return {
        "reviewer": payload.get("reviewer", ""),
        "readonly": payload.get("readonly", False),
    }


def require_writer(user: dict = Depends(get_current_user)) -> dict:
    """只读用户禁止访问此端点,返回 403。"""
    if user.get("readonly"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="只读用户不能执行此操作",
        )
    return user
