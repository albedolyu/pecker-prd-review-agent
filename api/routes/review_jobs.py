"""Background review job endpoints.

These endpoints are the reconnectable Phase 2 path. The existing streaming
endpoint remains unchanged; frontend can switch to this path once the UX is
ready.
"""
from __future__ import annotations

import asyncio
import json
import os
import hashlib
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query

from api.budget_gate import check_budget, record_review_cost
from api.deps import get_current_user, get_project_root, get_workspace_dir, review_semaphore
from api.figma_context import enrich_figma_raw_materials
from api.models import ReviewResult
from api.review_jobs import ReviewJob
from api.review_jobs import RecordingReviewProgressEmitter, review_job_store
from api.routes.drafts import DraftPayload, read_draft_file, write_draft_file
from api.routes.review import ReviewRequest, _copy_request_with_raw_materials, classify_worker_failures
from api.sanitize import redact_text
from api.workspace_acl import is_admin, require_workspace_access

router = APIRouter(tags=["review-jobs"])


async def _run_review_job_pipeline(
    *,
    req: ReviewRequest,
    user: dict,
    ws_abs_path: str,
    emitter: RecordingReviewProgressEmitter,
    project_root: Path,
) -> Dict[str, Any]:
    """Run the core review flow without tying its lifetime to the browser SSE."""
    started_at = time.time()
    context_audit_before = _context_audit_snapshot_for_job()
    if os.environ.get("PECKER_REVIEW_JOB_PIPELINE", "stream") == "stream":
        result = await _run_existing_review_stream_as_job(req=req, user=user, job=emitter.job)
        _attach_context_audit(result, before=context_audit_before)
        if isinstance(result, dict) and result.get("status") != "failed":
            _persist_completed_review_draft(
                req=req,
                reviewer=user["reviewer"],
                project_root=project_root,
                review_result=result,
            )
        return result

    from agent_config import MODEL_TIERS
    enriched_raw_materials = await asyncio.to_thread(enrich_figma_raw_materials, req.raw_materials)
    req = _copy_request_with_raw_materials(req, enriched_raw_materials)

    enhanced_prd = req.prd_content
    if req.raw_materials:
        enhanced_prd += "\n\n---\n## 补充业务资料\n\n" + "\n---\n".join(req.raw_materials)
    if req.user_notes:
        enhanced_prd += f"\n\n---\n## 评审人补充说明\n\n{req.user_notes}"

    emitter.emit("uploaded")
    emitter.emit("wiki_scanned", data={"page_count": len(req.wiki_pages)})
    emitter.emit(
        "review_queued",
        data={"message": "已进入评审队列，等待空闲评审位"},
    )

    async with review_semaphore:
        emitter.emit("workers_started", data={"mode": req.mode})
        def _on_worker_done(dim, result):
            emitter.emit_worker_done(dim, result)

        result = await _parallel_review_for_job(
            None,
            enhanced_prd,
            req.wiki_pages,
            MODEL_TIERS,
            on_worker_done=_on_worker_done,
            workspace=ws_abs_path,
        )

        workers = result.get("workers", [])
        failure_payload = classify_worker_failures(workers)
        if failure_payload is not None:
            emitter.emit("review_failed", data=failure_payload)
            return {"status": "failed", **failure_payload}

        items = result.get("merged_items", [])
        if req.mode == "standard" and items:
            emitter.emit("final_reviewer_started")
            try:
                goshawk_result = await _advisor_review_for_job(
                    None,
                    enhanced_prd,
                    items,
                    req.wiki_pages,
                )
                items = _apply_advisor_result_for_job(
                    items,
                    goshawk_result,
                    wiki_pages=req.wiki_pages,
                    client=None,
                )
                result["merged_items"] = items
                result["goshawk"] = goshawk_result
                emitter.emit(
                    "final_reviewer_done",
                    data={
                        "false_positive": len(goshawk_result.get("flagged_as_false_positive", [])),
                        "additional": len(goshawk_result.get("additional_findings", [])),
                        "verdict": goshawk_result.get("verdict", "UNKNOWN"),
                        "confidence": goshawk_result.get("confidence", 0.0),
                    },
                )
            except Exception as exc:  # noqa: BLE001
                emitter.emit("final_reviewer_done", data={"error": str(exc)[:200]})

    cost_breakdown: Dict[str, float] = {}
    total_cost = 0.0
    for worker in result.get("workers", []):
        dim = worker.get("dimension", "unknown")
        cost = float(worker.get("cost_usd", 0.0) or 0.0)
        cost_breakdown[dim] = round(cost, 6)
        total_cost += cost
    cost_breakdown["total"] = round(total_cost, 6)
    try:
        record_review_cost(project_root, total_cost, user["reviewer"])
    except Exception:
        pass

    worker_telemetry = {}
    for worker in result.get("workers", []):
        dim = worker.get("dimension") or "unknown"
        if isinstance(worker.get("telemetry"), dict):
            worker_telemetry[dim] = worker["telemetry"]
    telemetry = {
        "total_duration_ms": int((time.time() - started_at) * 1000),
        "workers": worker_telemetry,
        "total_cost_usd": cost_breakdown.get("total", 0),
        "orchestrator": result.get("orchestrator"),
        "resilience": result.get("resilience", {}),
        "context_manager": _context_audit_delta_for_job(context_audit_before),
    }

    review_result_handle = ReviewResult.create(
        reviewer=user["reviewer"],
        workspace=req.workspace,
        prd_name=req.prd_name,
        mode=req.mode,
        merged_items=result.get("merged_items", []),
        workers=result.get("workers", []),
        usage=result.get("total_usage", {}),
        goshawk_summary=result.get("goshawk"),
        cost_breakdown=cost_breakdown,
        telemetry=telemetry,
    )
    review_result_payload = review_result_handle.model_dump()
    _persist_completed_review_draft(
        req=req,
        reviewer=user["reviewer"],
        project_root=project_root,
        review_result=review_result_payload,
    )
    return review_result_payload


def _context_audit_snapshot_for_job() -> Dict[str, Any]:
    try:
        from context_manager import get_context_audit_snapshot

        return get_context_audit_snapshot()
    except Exception:
        return {"total_calls": 0, "total_tokens_saved": 0, "paths": {}}


def _context_audit_delta_for_job(before: Dict[str, Any]) -> Dict[str, Any]:
    after = _context_audit_snapshot_for_job()
    before_paths = before.get("paths") if isinstance(before.get("paths"), dict) else {}
    after_paths = after.get("paths") if isinstance(after.get("paths"), dict) else {}
    paths: Dict[str, Any] = {}
    metric_keys = {
        "calls",
        "mutations",
        "tokens_saved",
        "nudges",
        "failures",
    }
    for path in sorted(set(before_paths) | set(after_paths)):
        before_stats = before_paths.get(path) if isinstance(before_paths.get(path), dict) else {}
        after_stats = after_paths.get(path) if isinstance(after_paths.get(path), dict) else {}
        path_delta: Dict[str, Any] = {}
        for key in metric_keys:
            path_delta[key] = int(after_stats.get(key) or 0) - int(before_stats.get(key) or 0)
        path_delta["last_before_tokens"] = int(after_stats.get("last_before_tokens") or 0)
        path_delta["last_after_tokens"] = int(after_stats.get("last_after_tokens") or 0)
        paths[path] = path_delta
    return {
        "total_calls": int(after.get("total_calls") or 0) - int(before.get("total_calls") or 0),
        "total_tokens_saved": int(after.get("total_tokens_saved") or 0) - int(before.get("total_tokens_saved") or 0),
        "paths": paths,
    }


def _attach_context_audit(result: Dict[str, Any], *, before: Dict[str, Any]) -> None:
    if not isinstance(result, dict):
        return
    telemetry = result.get("telemetry")
    if not isinstance(telemetry, dict):
        telemetry = {}
        result["telemetry"] = telemetry
    telemetry["context_manager"] = _context_audit_delta_for_job(before)


def _persist_completed_review_draft(
    *,
    req: ReviewRequest,
    reviewer: str,
    project_root: Path,
    review_result: Dict[str, Any],
) -> None:
    """Let PMs resume Phase 3 even if the browser disconnected before result."""
    if not reviewer:
        return
    try:
        existing = read_draft_file(project_root, reviewer)
        existing_prd_name = (existing or {}).get("prd_name") or ""
        existing_workspace = (existing or {}).get("workspace") or ""
        if existing_prd_name and existing_prd_name != req.prd_name:
            return
        if existing_workspace and existing_workspace != req.workspace:
            return

        write_draft_file(
            project_root,
            reviewer,
            DraftPayload(
                phase=3,
                prd_name=req.prd_name,
                prd_content=req.prd_content,
                mode=req.mode,
                raw_materials=req.raw_materials,
                user_notes=req.user_notes,
                review_result=review_result,
                item_decisions={},
                confirmed_report_markdown="",
                workspace=req.workspace,
            ),
        )
    except Exception:
        # Draft persistence is a recovery aid. Do not fail a completed review
        # because the draft directory is temporarily unavailable.
        return


class _NeverDisconnectedRequest:
    async def is_disconnected(self) -> bool:
        return False


async def _run_existing_review_stream_as_job(
    *,
    req: ReviewRequest,
    user: dict,
    job: ReviewJob,
) -> Dict[str, Any]:
    """Reuse /api/review/run so reconnectable jobs stay quality-equivalent."""
    from api.routes.review import run_review

    response = await run_review(req=req, request=_NeverDisconnectedRequest(), user=user)
    buffer = ""
    result_payload: Optional[Dict[str, Any]] = None
    failed_payload: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None

    async for chunk in response.body_iterator:
        text = chunk.decode("utf-8") if isinstance(chunk, bytes) else str(chunk)
        buffer += text
        frames, buffer = _split_sse_frames(buffer)
        for frame in frames:
            parsed = _parse_sse_frame(frame)
            if parsed is None:
                continue
            event_name, raw_data = parsed
            try:
                data = json.loads(raw_data)
            except json.JSONDecodeError:
                continue
            if not isinstance(data, dict):
                continue
            job.emit(event_name, data)
            if event_name == "result" and isinstance(data.get("payload"), dict):
                result_payload = data["payload"]
            elif event_name == "review_failed":
                failed_payload = data
            elif event_name == "error":
                error_message = str(data.get("message") or "review failed")

    if result_payload is not None:
        return result_payload
    if failed_payload is not None:
        return {"status": "failed", **failed_payload}
    if error_message:
        raise RuntimeError(error_message)
    raise RuntimeError("review stream ended without result")


def _split_sse_frames(buffer: str) -> Tuple[list[str], str]:
    normalized = buffer.replace("\r\n", "\n")
    parts = normalized.split("\n\n")
    return parts[:-1], parts[-1] if parts else ""


def _parse_sse_frame(frame: str) -> Optional[Tuple[str, str]]:
    event_name = "message"
    data_lines: list[str] = []
    for raw in frame.split("\n"):
        if not raw or raw.startswith(":"):
            continue
        if ":" not in raw:
            continue
        field, value = raw.split(":", 1)
        value = value.lstrip(" ")
        if field.strip() == "event":
            event_name = value
        elif field.strip() == "data":
            data_lines.append(value)
    if not data_lines:
        return None
    return event_name, "\n".join(data_lines)


async def _parallel_review_for_job(*args, **kwargs) -> Dict[str, Any]:
    from parallel_review import parallel_review

    return await parallel_review(*args, **kwargs)


async def _advisor_review_for_job(*args, **kwargs) -> Dict[str, Any]:
    from goshawk_advisor import advisor_review_default_async

    return await advisor_review_default_async(*args, **kwargs)


def _apply_advisor_result_for_job(*args, **kwargs):
    from goshawk_advisor import apply_advisor_result

    return apply_advisor_result(*args, **kwargs)


@router.post("/review/jobs")
async def start_review_job(
    req: ReviewRequest,
    user: dict = Depends(get_current_user),
    project_root: Path = Depends(get_project_root),
) -> Dict[str, Any]:
    ws_dir = get_workspace_dir(req.workspace)
    require_workspace_access(ws_dir, user)
    check_budget(project_root, reviewer=user["reviewer"])
    ws_abs_path = str(project_root / req.workspace)

    async def runner(job):
        emitter = RecordingReviewProgressEmitter(job)
        return await _run_review_job_pipeline(
            req=req,
            user=user,
            ws_abs_path=ws_abs_path,
            emitter=emitter,
            project_root=project_root,
        )

    job, reused = review_job_store.create_job_with_reuse_info(
        owner=user["reviewer"],
        workspace=req.workspace,
        prd_name=req.prd_name,
        mode=req.mode,
        request_fingerprint=_review_request_fingerprint(req),
        runner=runner,
        audit_path=project_root / "logs" / "review_jobs.jsonl",
    )
    return {
        "job_id": job.job_id,
        "status": job.status,
        "workspace": redact_text(str(job.workspace)),
        "prd_name": redact_text(str(job.prd_name)),
        "mode": redact_text(str(job.mode)),
        "reused": reused,
    }


def _review_request_fingerprint(req: ReviewRequest) -> str:
    payload = {
        "workspace": req.workspace,
        "prd_name": req.prd_name,
        "mode": req.mode,
        "prd_content": req.prd_content,
        "raw_materials": req.raw_materials,
        "user_notes": req.user_notes,
        "wiki_pages": {
            key: req.wiki_pages[key]
            for key in sorted(req.wiki_pages.keys())
        },
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


@router.get("/review/jobs/{job_id}")
async def get_review_job(
    job_id: str,
    user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    return review_job_store.get_job(
        job_id,
        owner=user.get("reviewer", ""),
        admin=is_admin(user),
    )


@router.get("/review/jobs/{job_id}/next-event")
async def wait_review_job_event(
    job_id: str,
    after_index: int = Query(-1, description="Last event index already seen"),
    timeout: float = Query(25.0, ge=0.1, le=30.0),
    user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    job = review_job_store.get_job_ref(
        job_id,
        owner=user.get("reviewer", ""),
        admin=is_admin(user),
    )
    event = await job.wait_for_event(after_index=after_index, timeout=timeout)
    return {"event": event, "status": job.status}


@router.delete("/review/jobs/{job_id}")
async def cancel_review_job(
    job_id: str,
    user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    snapshot = review_job_store.cancel_job(
        job_id,
        owner=user.get("reviewer", ""),
        admin=is_admin(user),
    )
    return {"status": snapshot["status"], "job_id": job_id}
