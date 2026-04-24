"""GET /api/reports/{workspace}/{kind}/{date_tag}_{reviewer} — 下载评审报告

POST /api/reports/{workspace}/save-to-wiki — 保存评审记录到 workspace/wiki/

kind: 改动 / 交互 / 差异
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from api.deps import get_current_user, get_workspace_dir, require_writer
from api.workspace_acl import require_workspace_access

router = APIRouter(tags=["reports"])


def _safe_reviewer(reviewer: str) -> str:
    return re.sub(r'[\\/:*?"<>|\s]+', '_', (reviewer or "unknown").strip())[:20] or "unknown"


def _safe_prd_name(name: str) -> str:
    """清洗 prd_name,防路径穿越。前端传的 prd_name 直接拼入 filename,
    不 sanitize 会让 `../../etc/passwd` 之类的字符串写到 workspace 外面。

    规则: 去掉路径分隔符/通配符/. 以及首尾空白,截 50 字符,空值回退 unknown。
    """
    safe = re.sub(r'[\\/:*?"<>|\s\.]+', '_', (name or "unknown").strip())[:50]
    return safe.strip("_") or "unknown"


class SaveReviewRequest(BaseModel):
    prd_name: str
    report_markdown: str = Field(..., description="完整的评审报告 markdown")
    items_count: int = 0
    accepted_count: int = 0
    rejected_count: int = 0
    edited_count: int = 0
    peck_score: int = 0
    peck_label: str = ""


@router.get("/reports/{workspace}")
async def list_reports(workspace: str, user: dict = Depends(get_current_user)):
    """列出某个 workspace/output 下的所有 PRD_开发任务_*.md 报告。"""
    ws_dir = get_workspace_dir(workspace)
    require_workspace_access(ws_dir, user)
    output = ws_dir / "output"
    if not output.is_dir():
        return {"reports": []}

    reports = []
    for p in sorted(output.glob("PRD_开发任务_*.md"), key=lambda x: x.stat().st_mtime, reverse=True):
        reports.append({
            "filename": p.name,
            "size": p.stat().st_size,
            "mtime": p.stat().st_mtime,
        })
    return {"reports": reports[:50]}  # 最多返回 50 条


@router.get("/reports/{workspace}/download")
async def download_report(
    workspace: str,
    filename: str = Query(...),
    user: dict = Depends(get_current_user),
):
    """下载指定报告文件。防路径穿越: filename 不能含 / \\ ..

    前端从 list_reports 拿 filename 后,直接拼 URL 下载。
    """
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="非法文件名")
    ws_dir = get_workspace_dir(workspace)
    require_workspace_access(ws_dir, user)
    file_path = ws_dir / "output" / filename
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="报告不存在")
    return FileResponse(
        path=str(file_path),
        filename=filename,
        media_type="text/markdown",
    )


@router.post("/reports/{workspace}/save-to-wiki")
async def save_to_wiki(
    workspace: str,
    req: SaveReviewRequest,
    user: dict = Depends(require_writer),
):
    """把评审记录保存到 workspace/wiki/ 目录。

    只读用户 (PECKER_READONLY_USERS) 无权调用此端点,中间件返回 403。
    无 workspace 访问权限的用户,ACL 校验返回 403。
    """
    ws_dir = get_workspace_dir(workspace)
    require_workspace_access(ws_dir, user)
    wiki_dir = ws_dir / "wiki"
    wiki_dir.mkdir(parents=True, exist_ok=True)

    import time
    rev_safe = _safe_reviewer(user["reviewer"])
    prd_safe = _safe_prd_name(req.prd_name)
    date_tag = time.strftime("%Y%m%d")
    filename = f"评审记录-{prd_safe}-{rev_safe}-{date_tag}.md"
    report_path = wiki_dir / filename

    # 前缀 frontmatter
    frontmatter = (
        f"---\n"
        f"source: Web评审-{time.strftime('%Y-%m-%d')}\n"
        f"reviewer: {user['reviewer']}\n"
        f"created: {time.strftime('%Y-%m-%d')}\n"
        f"tags: [domain/评审记录, status/已验证]\n"
        f"---\n\n"
    )

    try:
        # 原子写
        import tempfile
        fd, tmp = tempfile.mkstemp(prefix=".report_", suffix=".tmp", dir=str(wiki_dir))
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(frontmatter)
            f.write(req.report_markdown)
        os.replace(tmp, report_path)

        # 追加 log.md
        log_path = wiki_dir / "log.md"
        log_entry = (
            f"\n\n## [{time.strftime('%Y-%m-%d %H:%M')}] review | {req.prd_name} by {user['reviewer']}\n"
            f"- 改进项: {req.items_count} 条\n"
            f"- 已接受: {req.accepted_count}, 已驳回: {req.rejected_count}, 已修改: {req.edited_count}\n"
            f"- 啄伤度: {req.peck_score}/100 ({req.peck_label})\n"
        )
        if log_path.exists():
            existing = log_path.read_text(encoding="utf-8")
            log_path.write_text(existing.rstrip() + log_entry, encoding="utf-8")
        else:
            log_path.write_text("# 操作日志\n" + log_entry, encoding="utf-8")

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"保存失败: {str(e)[:200]}")

    return {
        "status": "ok",
        "filename": filename,
        "path": str(report_path.relative_to(ws_dir.parent)),
    }
