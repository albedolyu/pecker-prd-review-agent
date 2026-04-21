"""GET/PUT/DELETE /api/drafts/{reviewer} — 评审草稿持久化,浏览器崩溃恢复用。

复用 app.py Step 3.1 的 `_save_draft / _load_draft / _clear_draft` 逻辑,
但重写为 pure Python(不依赖 st.session_state),让 FastAPI 可以直接用。
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from api.deps import get_current_user, get_project_root

router = APIRouter(tags=["drafts"])

_DRAFT_TTL_DAYS = 3


class DraftPayload(BaseModel):
    """前端上传的 draft 内容,字段结构与 Streamlit 保持兼容。"""
    phase: int = Field(..., ge=0, le=4)
    prd_name: str = ""
    prd_content: str = ""
    raw_materials: list[str] = Field(default_factory=list)
    user_notes: str = ""
    review_result: Optional[Dict[str, Any]] = None
    item_decisions: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    workspace: str = ""


def _draft_dir(project_root: Path) -> Path:
    return project_root / ".pecker_drafts"


def _safe_reviewer(reviewer: str) -> str:
    """把 reviewer 名规范化为安全的文件名片段,防路径穿越。"""
    safe = re.sub(r'[\\/:*?"<>|\s]+', '_', (reviewer or "unknown").strip())[:20]
    if not safe or safe == "_":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="非法 reviewer 名",
        )
    return safe


def _draft_path(project_root: Path, reviewer: str) -> Path:
    return _draft_dir(project_root) / f"{_safe_reviewer(reviewer)}_draft.json"


@router.get("/drafts/{reviewer}")
async def get_draft(
    reviewer: str,
    project_root: Path = Depends(get_project_root),
    user: dict = Depends(get_current_user),
):
    """读草稿。不存在或过期返回 404。"""
    path = _draft_path(project_root, reviewer)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="无草稿")

    try:
        with open(path, "r", encoding="utf-8") as f:
            draft = json.load(f)
    except (json.JSONDecodeError, OSError):
        raise HTTPException(status_code=404, detail="草稿文件损坏")

    # TTL 检查
    ts = draft.get("ts", "")
    if ts:
        try:
            age = (datetime.now() - datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S")).total_seconds()
            if age > _DRAFT_TTL_DAYS * 86400:
                try:
                    path.unlink()
                except OSError:
                    pass
                raise HTTPException(status_code=404, detail="草稿已过期")
        except ValueError:
            pass

    return draft


@router.put("/drafts/{reviewer}")
async def save_draft(
    reviewer: str,
    payload: DraftPayload,
    project_root: Path = Depends(get_project_root),
    user: dict = Depends(get_current_user),
):
    """保存/覆盖草稿。原子写 (tempfile + os.replace)。"""
    path = _draft_path(project_root, reviewer)
    path.parent.mkdir(parents=True, exist_ok=True)

    draft = {
        "ts": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "reviewer": reviewer,
        **payload.model_dump(),
    }

    fd, tmp = tempfile.mkstemp(
        prefix=".draft_",
        suffix=".tmp",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(draft, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass
        raise

    return {"status": "ok", "path": str(path.name), "ts": draft["ts"]}


@router.delete("/drafts/{reviewer}")
async def delete_draft(
    reviewer: str,
    project_root: Path = Depends(get_project_root),
    user: dict = Depends(get_current_user),
):
    """删除草稿。文件不存在也返回成功(幂等)。"""
    path = _draft_path(project_root, reviewer)
    if path.is_file():
        try:
            path.unlink()
        except OSError as e:
            raise HTTPException(status_code=500, detail=f"删除失败: {e}")
    return {"status": "ok"}
