"""workspace 访问控制 — 防止任意登录用户读他人 workspace。

约定:
- workspace 根目录下放 `.pecker_acl.json`:
    {"owner": "alice", "readers": ["bob", "carol"]}
- 无 .pecker_acl.json:
    * workspace-sample 白名单: 视为公开(demo 用)
    * 其他 workspace: **fail-closed** 只有 admin 可访问 (2026-04-24 反转, 之前是公开,
      导致"代码实现但 zero deployment" 漏洞 — 9 个业务 workspace 0 个配 ACL 时任何
      登录用户都能横向访问)
- PECKER_ADMIN_USERS 环境变量(逗号分隔)列出的用户 bypass 所有 ACL
- owner + readers 都算可读; 只有 owner 和 admin 可写(后续扩展,当前依赖 require_writer 的只读/非只读二分)

新建 workspace 务必同时生成 ACL: `make init-acl WS=workspace-xxx OWNER=albedolyu READERS=bob,carol`
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional, Set

from fastapi import HTTPException, status


_ACL_FILENAME = ".pecker_acl.json"

# 白名单: 无 ACL 文件但仍视为公开的 workspace. demo / 脱敏样本专用.
# 添加新 public workspace 前先考虑是否真的没有敏感数据 (PRD 原文 / 内部业务逻辑).
_PUBLIC_FALLBACK_WORKSPACES = frozenset({"workspace-sample"})


def _admin_users() -> Set[str]:
    raw = os.environ.get("PECKER_ADMIN_USERS", "")
    return {u.strip() for u in raw.split(",") if u.strip()}


def is_admin(user: dict) -> bool:
    """判断当前用户是否管理员。drafts/reports 等跨人读端点借此做 bypass。"""
    reviewer = (user or {}).get("reviewer", "").strip()
    return bool(reviewer) and reviewer in _admin_users()


def _load_acl(workspace_dir: Path) -> Optional[dict]:
    """读 .pecker_acl.json; 无文件或解析失败返回 None (视为公开)。"""
    acl_path = workspace_dir / _ACL_FILENAME
    if not acl_path.is_file():
        return None
    try:
        with open(acl_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except (json.JSONDecodeError, OSError):
        # acl 文件坏了 → 安全起见当作"有 acl 但没人能读"
        return {"owner": "", "readers": []}
    return None


def can_access_workspace(workspace_dir: Path, user: dict) -> bool:
    """判定某用户能否读该 workspace。user 来自 get_current_user。"""
    reviewer = (user or {}).get("reviewer", "").strip()
    if not reviewer:
        return False

    if reviewer in _admin_users():
        return True

    acl = _load_acl(workspace_dir)
    if acl is None:
        # 2026-04-24 反转默认: 无 ACL 文件时 fail-closed, 除非 workspace 在白名单里 (demo).
        # 之前无 ACL = 所有登录用户可读, 是"实现了但没部署"的漏洞.
        return workspace_dir.name in _PUBLIC_FALLBACK_WORKSPACES

    owner = (acl.get("owner") or "").strip()
    readers = {r.strip() for r in (acl.get("readers") or []) if isinstance(r, str)}

    return reviewer == owner or reviewer in readers


def require_workspace_access(workspace_dir: Path, user: dict) -> None:
    """无权访问则 403。通常紧跟 get_workspace_dir() 调用。"""
    if not can_access_workspace(workspace_dir, user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="无权访问此 workspace",
        )
