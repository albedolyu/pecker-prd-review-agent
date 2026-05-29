"""Admin-only usage dashboard endpoint."""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, status

from api.deps import get_current_user, get_external_workspace_roots, get_project_root
from api.feedback_summary import build_feedback_summary
from api.review_jobs import review_job_store
from api.sanitize import redact_sensitive, redact_text
from api.usage_summary import build_usage_summary
from review.langgraph_checkpoint import summarize_review_job_checkpoints
from scripts.langfuse_smoke_check import run_langfuse_smoke_check

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
    data["rule_impact_reports"] = _load_rule_impact_reports(project_root, limit=4)
    return data


@router.get("/langfuse-smoke")
async def get_admin_langfuse_smoke(
    _user: dict = Depends(_require_admin),
) -> Dict[str, Any]:
    return redact_sensitive(run_langfuse_smoke_check(write_score=False))


@router.get("/langgraph-checkpoints")
async def get_admin_langgraph_checkpoints(
    _user: dict = Depends(_require_admin),
    project_root: Path = Depends(get_project_root),
) -> Dict[str, Any]:
    return redact_sensitive(summarize_review_job_checkpoints(project_root))


@router.get("/langfuse-run-audits")
async def get_admin_langfuse_run_audits(
    limit: int = Query(12, ge=1, le=100, description="最近 N 个 Langfuse run audit"),
    _user: dict = Depends(_require_admin),
    project_root: Path = Depends(get_project_root),
) -> Dict[str, Any]:
    return redact_sensitive(
        _load_recent_langfuse_run_audits(
            project_root,
            limit=max(1, min(_safe_int(limit, 12), 100)),
        )
    )


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
        "context_manager_calls",
        "context_manager_tokens_saved",
        "context_manager_nudges",
        "context_manager_failures",
    }
    return redact_sensitive({key: value for key, value in row.items() if key in allowed})


def _load_recent_langfuse_run_audits(project_root: Path, *, limit: int = 12) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    for workspace_dir in _iter_workspace_dirs(project_root):
        audit_dir = workspace_dir / "output" / "langfuse_audits"
        if not audit_dir.is_dir():
            continue
        try:
            paths = list(audit_dir.glob("*.json"))
        except OSError:
            continue
        for path in paths:
            rows.append(_langfuse_audit_row(workspace_dir, path))
    rows.sort(key=lambda row: float(row.get("mtime") or 0), reverse=True)
    rows = rows[: max(1, limit)]
    summary = {
        "total": len(rows),
        "ready": sum(1 for row in rows if row.get("ok")),
        "missing": sum(1 for row in rows if not row.get("ok")),
        "trace_ready": sum(1 for row in rows if row.get("trace_ready")),
        "graph_ready": sum(1 for row in rows if row.get("graph_ready")),
        "checkpoint_ready": sum(1 for row in rows if row.get("checkpoint_ready")),
        "graph_order_failures": sum(1 for row in rows if row.get("graph_order_failure")),
        "checkpoint_failures": sum(1 for row in rows if row.get("checkpoint_failure")),
        "worker_failures": sum(1 for row in rows if row.get("worker_failure")),
        "session_checkpoint_mismatches": sum(
            1 for row in rows if row.get("session_checkpoint_mismatch")
        ),
        "evidence_score_failures": sum(
            1 for row in rows if row.get("evidence_score_failure")
        ),
        "feedback_score_failures": sum(
            1 for row in rows if row.get("feedback_score_failure")
        ),
        "audits": rows,
    }
    return redact_sensitive(summary)


def _iter_workspace_dirs(project_root: Path):
    seen = set()
    for root in [*get_external_workspace_roots(), project_root]:
        try:
            candidates = list(Path(root).glob("workspace-*"))
        except OSError:
            continue
        for path in candidates:
            try:
                resolved = path.resolve(strict=False)
            except OSError:
                resolved = path
            if str(resolved) in seen or not path.is_dir():
                continue
            seen.add(str(resolved))
            yield path


def _langfuse_audit_row(workspace_dir: Path, path: Path) -> Dict[str, Any]:
    mtime = 0.0
    try:
        mtime = path.stat().st_mtime
    except OSError:
        pass
    json_url = _langfuse_audit_url(workspace_dir.name, path.stem, "json")
    markdown_path = path.with_suffix(".md")
    markdown_url = (
        _langfuse_audit_url(workspace_dir.name, path.stem, "markdown")
        if markdown_path.is_file()
        else None
    )
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        row = {
            "workspace": redact_text(workspace_dir.name),
            "review_id": redact_text(path.stem),
            "ok": False,
            "status": "invalid_json",
            "trace_ready": False,
            "graph_ready": False,
            "checkpoint_ready": False,
            "graph_order_failure": False,
            "checkpoint_failure": False,
            "worker_failure": False,
            "session_checkpoint_linked": False,
            "session_checkpoint_mismatch": False,
            "evidence_score_failure": False,
            "feedback_score_failure": False,
            "missing_count": 1,
            "missing": ["invalid_json"],
            "mtime": mtime,
            "json_path": f"output/langfuse_audits/{path.name}",
        }
        if json_url:
            row["json_url"] = json_url
        if markdown_url:
            row["markdown_url"] = markdown_url
        row["missing_summary"] = "invalid_json"
        return row
    if not isinstance(payload, dict):
        payload = {}
    langfuse = _dict_value(payload, "langfuse")
    langgraph = _dict_value(payload, "langgraph")
    checkpoint = _dict_value(payload, "langgraph_checkpoint")
    evidence_scores = _dict_value(langfuse, "evidence_scores")
    feedback_scores = _dict_value(langfuse, "pm_feedback_scores")
    prompt_versions = langfuse.get("prompt_versions")
    prompts_count = len(prompt_versions) if isinstance(prompt_versions, list) else 0
    missing_values = payload.get("missing")
    missing = [
        redact_text(str(item))[:200]
        for item in (missing_values if isinstance(missing_values, list) else [])
    ][:8]
    missing_count = (
        _safe_int(payload.get("missing_count"))
        if isinstance(payload.get("missing_count"), (int, float, str))
        else len(missing_values) if isinstance(missing_values, list) else 0
    )
    status = redact_text(
        str(payload.get("status") or ("ready" if payload.get("ok") else "missing"))
    )
    trace_ready = bool(langfuse.get("trace_link_ready") or langfuse.get("trace_url"))
    graph_ready = bool(langgraph.get("graph_trace_ready") and langgraph.get("worker_nodes_ready"))
    graph_order_failure = langgraph.get("graph_trace_order_ready") is False
    worker_failure = (
        langgraph.get("worker_nodes_ready") is False
        or _safe_int(langgraph.get("failed_workers")) > 0
    )
    session_checkpoint_linked, session_checkpoint_mismatch = (
        _session_checkpoint_link_state(
            payload,
            langfuse=langfuse,
            checkpoint=checkpoint,
            missing=missing,
        )
    )
    evidence_score_failure = _score_snapshot_failure(
        evidence_scores,
        missing=missing,
        missing_prefix="langfuse_evidence",
    )
    feedback_score_failure = _score_snapshot_failure(
        feedback_scores,
        missing=missing,
        missing_prefix="langfuse_feedback",
    )
    checkpoint_ready = bool(
        checkpoint.get("status") == "ready"
        and checkpoint.get("thread_found")
        and checkpoint.get("checkpoint_exists", True)
    )
    checkpoint_failure = not checkpoint_ready
    row = {
        "workspace": redact_text(workspace_dir.name),
        "review_id": redact_text(str(payload.get("review_id") or path.stem)),
        "ok": bool(payload.get("ok")),
        "status": status,
        "trace_ready": trace_ready,
        "graph_ready": graph_ready,
        "graph_order_failure": graph_order_failure,
        "checkpoint_ready": checkpoint_ready,
        "checkpoint_failure": checkpoint_failure,
        "worker_failure": worker_failure,
        "session_checkpoint_linked": session_checkpoint_linked,
        "session_checkpoint_mismatch": session_checkpoint_mismatch,
        "evidence_score_failure": evidence_score_failure,
        "feedback_score_failure": feedback_score_failure,
        "evidence_status": redact_text(str(evidence_scores.get("status") or "")),
        "feedback_status": redact_text(str(feedback_scores.get("status") or "")),
        "prompt_versions": prompts_count,
        "recovered_workers": _safe_int(langgraph.get("recovered_workers")),
        "checkpoint_count": _safe_int(checkpoint.get("checkpoint_count")),
        "missing_count": missing_count,
        "missing": missing,
        "mtime": mtime,
        "json_path": f"output/langfuse_audits/{path.name}",
    }
    missing_summary = _missing_summary(missing)
    if missing_summary:
        row["missing_summary"] = missing_summary
    if json_url:
        row["json_url"] = json_url
    if markdown_path.is_file():
        row["markdown_path"] = f"output/langfuse_audits/{markdown_path.name}"
        if markdown_url:
            row["markdown_url"] = markdown_url
    return redact_sensitive(row)


def _missing_summary(missing: List[str], *, limit: int = 3) -> str:
    values = [redact_text(str(item))[:200] for item in missing if str(item).strip()]
    return ", ".join(values[: max(1, limit)])


def _session_checkpoint_link_state(
    payload: Dict[str, Any],
    *,
    langfuse: Dict[str, Any],
    checkpoint: Dict[str, Any],
    missing: List[str],
) -> tuple[bool, bool]:
    if isinstance(payload.get("session_checkpoint_linked"), bool):
        linked = bool(payload.get("session_checkpoint_linked"))
    else:
        session_id = str(langfuse.get("session_id") or "").strip()
        thread_id = str(checkpoint.get("thread_id") or "").strip()
        linked = bool(session_id and thread_id and session_id == thread_id)
    if isinstance(payload.get("session_checkpoint_mismatch"), bool):
        mismatch = bool(payload.get("session_checkpoint_mismatch"))
    else:
        session_id = str(langfuse.get("session_id") or "").strip()
        thread_id = str(checkpoint.get("thread_id") or "").strip()
        mismatch = bool(session_id and thread_id and session_id != thread_id)
    if "langfuse.session_checkpoint_thread" in missing:
        mismatch = True
    return linked, mismatch


def _langfuse_audit_url(workspace: str, review_id: str, artifact_format: str) -> str | None:
    workspace_value = str(workspace or "")
    review_id_value = str(review_id or "")
    if not workspace_value or not review_id_value:
        return None
    if redact_text(workspace_value) != workspace_value:
        return None
    if redact_text(review_id_value) != review_id_value:
        return None
    return (
        "/api/review/langfuse-audits/"
        f"{quote(workspace_value, safe='')}/"
        f"{quote(review_id_value, safe='')}"
        f"?format={quote(str(artifact_format or 'json'), safe='')}"
    )


def _dict_value(payload: Dict[str, Any], key: str) -> Dict[str, Any]:
    value = payload.get(key) if isinstance(payload, dict) else None
    return value if isinstance(value, dict) else {}


def _score_snapshot_failure(
    snapshot: Dict[str, Any],
    *,
    missing: List[str],
    missing_prefix: str,
) -> bool:
    if any(str(item).startswith(missing_prefix) for item in missing):
        return True
    if not snapshot:
        return False
    status = str(snapshot.get("status") or "")
    if status and status != "recorded":
        return True
    if (
        _safe_int(snapshot.get("scored_items")) > 0
        and _safe_int(snapshot.get("scores_sent")) <= 0
    ):
        return True
    return snapshot.get("trace_linked") is False


def _load_rule_impact_reports(project_root: Path, *, limit: int = 4) -> List[Dict[str, Any]]:
    report_dir = project_root / "eval_reports"
    if not report_dir.is_dir():
        return []
    rows: List[Dict[str, Any]] = []
    for path in sorted(report_dir.glob("rule_impact_*.md")):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        title = lines[0].lstrip("# ").strip() if lines else path.stem
        preview = " ".join(line for line in lines[1:4] if not line.startswith("|"))
        rows.append(
            {
                "filename": path.name,
                "title": redact_text(title),
                "preview": redact_text(preview)[:240],
                "mtime": path.stat().st_mtime,
            }
        )
    rows.sort(key=lambda row: float(row.get("mtime") or 0), reverse=True)
    return rows[: max(1, limit)]


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
    context_manager = telemetry.get("context_manager") if isinstance(telemetry.get("context_manager"), dict) else {}
    context_paths = context_manager.get("paths") if isinstance(context_manager.get("paths"), dict) else {}
    context_manager_nudges = 0
    for path_stats in context_paths.values():
        if isinstance(path_stats, dict):
            context_manager_nudges += _safe_int(path_stats.get("nudges"))
    decisions = draft.get("item_decisions") if isinstance(draft.get("item_decisions"), dict) else {}
    action_counts: Dict[str, int] = {"accept": 0, "reject": 0, "edit": 0}
    for decision in decisions.values():
        if isinstance(decision, dict):
            action = str(decision.get("action") or "")
            if action in action_counts:
                action_counts[action] += 1
    phase = _safe_int(draft.get("phase"))
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
        "orchestrator": redact_text(str(telemetry.get("orchestrator") or "")),
        "failed_workers": _safe_int(resilience.get("failed_workers")),
        "recovered_workers": _safe_int(resilience.get("recovered_workers")),
        "context_packet_workers": _safe_int(resilience.get("context_packet_workers")),
        "max_context_packet_chars": _safe_int(resilience.get("max_context_packet_chars")),
        "context_manager_calls": _safe_int(context_manager.get("total_calls")),
        "context_manager_tokens_saved": _safe_int(context_manager.get("total_tokens_saved")),
        "context_manager_nudges": context_manager_nudges,
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
