"""workspace 访问控制 — 防止任意登录用户读他人 workspace。

约定:
- workspace 根目录下放 `.pecker_acl.json`:
    {"owner": "alice", "readers": ["bob", "carol"]}
- 无 .pecker_acl.json → 公开(所有已登录用户可读,保持向后兼容,用于 workspace-sample 等 demo)
- PECKER_ADMIN_USERS 环境变量(逗号分隔)列出的用户 bypass 所有 ACL
- owner + readers 都算可读; 只有 owner 和 admin 可写(后续扩展,当前依赖 require_writer 的只读/非只读二分)

这是 MVP 实现,够挡"登录用户之间误看他人业务 PRD"这类内测场景的威胁。
敏感 workspace 需管理员手动 drop `.pecker_acl.json` 开启 ACL。
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional, Set

from fastapi import HTTPException, status


_ACL_FILENAME = ".pecker_acl.json"


def _admin_users() -> Set[str]:
    raw = os.environ.get("PECKER_ADMIN_USERS", "")
    return {u.strip() for u in raw.split(",") if u.strip()}


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
        return True  # 无 acl = 公开(backward compat)

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
