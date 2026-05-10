"""Admin-only usage dashboard endpoint."""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Query, status

from api.deps import get_current_user, get_project_root
from api.feedback_summary import build_feedback_summary
from api.review_jobs import review_job_store
from api.sanitize import redact_sensitive, redact_text
from api.usage_summary import build_usage_summary

router = APIRouter(prefix="/admin", tags=["admin"])

_ACTIVE_DRAFT_TTL_DAYS = 3


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
    data = build_usage_summary(project_root=project_root, days=days)
    jobs = review_job_store.list_jobs(admin=True, limit=30)
    data["active_jobs"] = [
        {
            "job_id": job["job_id"],
            "status": job["status"],
            "owner": redact_text(str(job["owner"])),
            "workspace": redact_text(str(job["workspace"])),
            "prd_name": redact_text(str(job["prd_name"])),
            "mode": redact_text(str(job["mode"])),
            "created_at": job["created_at"],
            "updated_at": job["updated_at"],
            "event_count": len(job.get("events", [])),
            "last_event": (job.get("events") or [{}])[-1].get("event"),
            "error": redact_text(str(job.get("error", "")))[:500],
        }
        for job in jobs
    ]
    data["recent_job_events"] = _load_recent_job_events(project_root, limit=50)
    data["active_drafts"] = _load_active_drafts(project_root, limit=30)
    return data


def _load_recent_job_events(project_root: Path, *, limit: int = 50) -> List[Dict[str, Any]]:
    path = project_root / "logs" / "review_jobs.jsonl"
    if not path.is_file():
        return []
    rows: List[Dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                rows.append(_sanitize_job_event(row))
    except OSError:
        return []
    rows.sort(key=lambda row: float(row.get("ts") or 0), reverse=True)
    return rows[: max(1, limit)]


def _sanitize_job_event(row: Dict[str, Any]) -> Dict[str, Any]:
    allowed = {
        "job_id",
        "owner",
        "workspace",
        "prd_name",
        "mode",
        "status",
        "event",
        "index",
        "ts",
        "progress",
        "label",
        "dim_key",
        "dim_name",
        "success",
        "items_count",
        "error",
        "error_type",
        "message",
        "failed_count",
        "total_count",
        "reason",
        "result_review_id",
        "result_items_count",
        "result_status",
        "duration_ms",
        "input_tokens",
        "output_tokens",
        "cost_usd",
        "prd_context_packet_chars",
    }
    return redact_sensitive({key: value for key, value in row.items() if key in allowed})


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value or default)
    except (TypeError, ValueError):
        return default


def _load_active_drafts(project_root: Path, *, limit: int = 30) -> List[Dict[str, Any]]:
    draft_dir = project_root / ".pecker_drafts"
    if not draft_dir.is_dir():
        return []
    rows: List[Dict[str, Any]] = []
    for path in draft_dir.glob("*_draft.json"):
        try:
            draft = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(draft, dict):
            ts = draft.get("ts", "")
            if ts:
                try:
                    age = (datetime.now() - datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S")).total_seconds()
                    if age > _ACTIVE_DRAFT_TTL_DAYS * 86400:
                        continue
                except ValueError:
                    pass
            rows.append(_sanitize_draft(draft))
    rows.sort(key=lambda row: str(row.get("ts") or ""), reverse=True)
    return rows[: max(1, limit)]


def _sanitize_draft(draft: Dict[str, Any]) -> Dict[str, Any]:
    review_result = draft.get("review_result") if isinstance(draft.get("review_result"), dict) else {}
    items = review_result.get("items") if isinstance(review_result, dict) else []
    telemetry = review_result.get("telemetry") if isinstance(review_result.get("telemetry"), dict) else {}
    resilience = telemetry.get("resilience") if isinstance(telemetry.get("resilience"), dict) else {}
    decisions = draft.get("item_decisions") if isinstance(draft.get("item_decisions"), dict) else {}
    action_counts: Dict[str, int] = {"accept": 0, "reject": 0, "edit": 0}
    for decision in decisions.values():
        if isinstance(decision, dict):
            action = str(decision.get("action") or "")
            if action in action_counts:
                action_counts[action] += 1
    phase = int(draft.get("phase") or 0)
    return {
        "ts": draft.get("ts", ""),
        "reviewer": redact_text(str(draft.get("reviewer", ""))),
        "phase": phase,
        "phase_label": _phase_label(phase),
        "workspace": redact_text(str(draft.get("workspace", ""))),
        "prd_name": redact_text(str(draft.get("prd_name", ""))),
        "mode": redact_text(str(draft.get("mode", ""))),
        "has_review_result": bool(review_result),
        "items_count": len(items) if isinstance(items, list) else 0,
        "decisions_count": len(decisions),
        "accepted": action_counts["accept"],
        "rejected": action_counts["reject"],
        "edited": action_counts["edit"],
        "has_confirmed_report": bool(draft.get("confirmed_report_markdown")),
        "duration_ms": _safe_int(telemetry.get("total_duration_ms")),
        "orchestrator": str(telemetry.get("orchestrator") or ""),
        "failed_workers": _safe_int(resilience.get("failed_workers")),
        "recovered_workers": _safe_int(resilience.get("recovered_workers")),
        "context_packet_workers": _safe_int(resilience.get("context_packet_workers")),
        "max_context_packet_chars": _safe_int(resilience.get("max_context_packet_chars")),
    }


def _phase_label(phase: int) -> str:
    labels = {
        0: "上传 PRD",
        1: "资料预检",
        2: "生成意见",
        3: "逐条确认",
        4: "评审报告",
    }
    return labels.get(phase, f"第 {phase} 步")


@router.get("/feedback")
async def get_admin_feedback(
    days: int = Query(7, ge=1, le=90, description="统计最近 N 天"),
    reviewer: str = Query("", description="按评审人筛选"),
    workspace: str = Query("", description="按资料库筛选"),
    action: str = Query("", description="按处理结果筛选: accept/reject/edit"),
    limit: int = Query(100, ge=1, le=500, description="最多返回多少条逐条反馈"),
    _user: dict = Depends(_require_admin),
    project_root: Path = Depends(get_project_root),
) -> Dict[str, Any]:
    return build_feedback_summary(
        project_root=project_root,
        days=days,
        reviewer=reviewer,
        workspace=workspace,
        action=action,
        limit=limit,
    )
