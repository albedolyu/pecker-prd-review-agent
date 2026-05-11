"""In-memory background review jobs for reconnectable Phase 2 runs.

The store intentionally keeps only progress events, metadata, result handles,
and short errors. Uploaded PRD body and raw materials must stay out of snapshots.
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Deque, Dict, List, Optional

from fastapi import HTTPException, status

from api.sanitize import redact_sensitive, redact_text
from api.stream import MILESTONES, WORKER_PROGRESS_STEP, ReviewProgressEmitter


ReviewJobRunner = Callable[["ReviewJob"], Awaitable[Dict[str, Any]]]


def _now() -> float:
    return time.time()


@dataclass
class ReviewJob:
    job_id: str
    owner: str
    workspace: str
    prd_name: str
    mode: str
    request_fingerprint: str = ""
    max_events: int = 200
    created_at: float = field(default_factory=_now)
    updated_at: float = field(default_factory=_now)
    status: str = "queued"
    result: Optional[Dict[str, Any]] = None
    error: str = ""
    recovery: Dict[str, Any] = field(default_factory=dict)
    audit_path: Optional[Path] = None
    _events: Deque[Dict[str, Any]] = field(default_factory=deque)
    _event_index: int = 0
    _condition: asyncio.Condition = field(default_factory=asyncio.Condition)
    _task: Optional[asyncio.Task] = None

    def attach_task(self, task: asyncio.Task) -> None:
        self._task = task

    def cancel(self) -> None:
        if self.status in {"done", "error", "cancelled"}:
            return
        self.status = "cancelled"
        self.error = "cancelled"
        self.updated_at = _now()
        self.emit("error", {"message": "评审任务已取消"})
        if self._task is not None and not self._task.done():
            self._task.cancel()

    async def wait(self) -> None:
        if self._task is not None:
            try:
                await asyncio.shield(self._task)
            except asyncio.CancelledError:
                if self.status == "cancelled":
                    return
                raise

    def emit(self, event: str, data: Optional[Dict[str, Any]] = None) -> None:
        payload = {
            "index": self._event_index,
            "event": event,
            "ts": _now(),
            **_scrub_event_payload(data or {}),
        }
        self._event_index += 1
        self.updated_at = payload["ts"]
        self._events.append(payload)
        while len(self._events) > self.max_events:
            self._events.popleft()
        self._append_audit_record(payload)
        try:
            asyncio.get_running_loop().create_task(self._notify_waiters())
        except RuntimeError:
            pass

    def _append_audit_record(self, event: Dict[str, Any]) -> None:
        if self.audit_path is None:
            return
        try:
            self.audit_path.parent.mkdir(parents=True, exist_ok=True)
            record = _build_audit_record(self, event)
            with self.audit_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError:
            return

    async def _notify_waiters(self) -> None:
        async with self._condition:
            self._condition.notify_all()

    async def wait_for_event(
        self,
        *,
        after_index: int,
        timeout: float = 30.0,
    ) -> Optional[Dict[str, Any]]:
        deadline = _now() + max(0.1, timeout)
        async with self._condition:
            while True:
                event = self.first_event_after(after_index)
                if event is not None:
                    return event
                if self.status in {"done", "error", "cancelled"}:
                    return None
                remaining = deadline - _now()
                if remaining <= 0:
                    return None
                try:
                    await asyncio.wait_for(self._condition.wait(), timeout=remaining)
                except asyncio.TimeoutError:
                    return None

    def first_event_after(self, after_index: int) -> Optional[Dict[str, Any]]:
        for event in self._events:
            if int(event.get("index", -1)) > after_index:
                return dict(event)
        return None

    def snapshot(self) -> Dict[str, Any]:
        return {
            "job_id": self.job_id,
            "status": self.status,
            "owner": redact_text(str(self.owner)),
            "workspace": redact_text(str(self.workspace)),
            "prd_name": redact_text(str(self.prd_name)),
            "mode": redact_text(str(self.mode)),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "events": [dict(event) for event in self._events],
            "result": redact_sensitive(self.result),
            "error": redact_text(str(self.error)),
            "recovery": redact_sensitive(self.recovery),
        }


class ReviewJobStore:
    def __init__(
        self,
        *,
        max_events: int = 200,
        max_jobs: int = 200,
        ttl_seconds: float = 24 * 60 * 60,
    ):
        self.max_events = max_events
        self.max_jobs = max(1, int(max_jobs))
        self.ttl_seconds = max(60.0, float(ttl_seconds))
        self._jobs: Dict[str, ReviewJob] = {}

    def create_job(
        self,
        *,
        owner: str,
        workspace: str,
        prd_name: str,
        mode: str,
        request_fingerprint: str = "",
        runner: ReviewJobRunner,
        audit_path: Optional[Path] = None,
    ) -> ReviewJob:
        job, _reused = self.create_job_with_reuse_info(
            owner=owner,
            workspace=workspace,
            prd_name=prd_name,
            mode=mode,
            request_fingerprint=request_fingerprint,
            runner=runner,
            audit_path=audit_path,
        )
        return job

    def create_job_with_reuse_info(
        self,
        *,
        owner: str,
        workspace: str,
        prd_name: str,
        mode: str,
        request_fingerprint: str = "",
        runner: ReviewJobRunner,
        audit_path: Optional[Path] = None,
    ) -> tuple[ReviewJob, bool]:
        self._prune_jobs()
        for existing in self._jobs.values():
            if (
                existing.status in {"queued", "running"}
                and existing.owner == owner
                and existing.workspace == workspace
                and existing.prd_name == prd_name
                and existing.mode == mode
                and (existing.request_fingerprint or "") == (request_fingerprint or "")
            ):
                return existing, True

        job = ReviewJob(
            job_id=f"rjob_{int(_now())}_{uuid.uuid4().hex[:8]}",
            owner=owner,
            workspace=workspace,
            prd_name=prd_name,
            mode=mode,
            request_fingerprint=request_fingerprint,
            max_events=self.max_events,
            audit_path=audit_path,
        )
        self._jobs[job.job_id] = job
        job.attach_task(asyncio.create_task(self._run_job(job, runner)))
        return job, False

    def get_job(self, job_id: str, *, owner: str, admin: bool = False) -> Dict[str, Any]:
        self._prune_jobs()
        job = self._jobs.get(job_id)
        if job is None or (not admin and job.owner != owner):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="评审任务不存在或无权访问",
            )
        return job.snapshot()

    def get_job_ref(self, job_id: str, *, owner: str, admin: bool = False) -> ReviewJob:
        self._prune_jobs()
        job = self._jobs.get(job_id)
        if job is None or (not admin and job.owner != owner):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="评审任务不存在或无权访问",
            )
        return job

    def list_jobs(
        self,
        *,
        owner: str = "",
        admin: bool = False,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        self._prune_jobs()
        jobs = [
            job
            for job in self._jobs.values()
            if admin or (owner and job.owner == owner)
        ]
        jobs.sort(key=lambda job: job.updated_at, reverse=True)
        return [job.snapshot() for job in jobs[: max(1, limit)]]

    def cancel_job(self, job_id: str, *, owner: str, admin: bool = False) -> Dict[str, Any]:
        job = self.get_job_ref(job_id, owner=owner, admin=admin)
        job.cancel()
        return job.snapshot()

    def restore_from_audit_log(self, audit_path: Path) -> int:
        if not audit_path.is_file():
            return 0
        by_job: Dict[str, List[Dict[str, Any]]] = {}
        try:
            for line in audit_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(row, dict) and isinstance(row.get("job_id"), str):
                    by_job.setdefault(str(row["job_id"]), []).append(row)
        except OSError:
            return 0

        restored = 0
        for job_id, rows in by_job.items():
            if job_id in self._jobs:
                continue
            rows.sort(key=lambda row: int(row.get("index") or 0))
            first = rows[0]
            last = rows[-1]
            job = ReviewJob(
                job_id=job_id,
                owner=str(first.get("owner") or ""),
                workspace=str(first.get("workspace") or ""),
                prd_name=str(first.get("prd_name") or ""),
                mode=str(first.get("mode") or ""),
                max_events=self.max_events,
                created_at=_now(),
                updated_at=_now(),
                audit_path=audit_path,
            )
            job._events = deque(
                _event_from_audit_row(row)
                for row in rows[-self.max_events :]
                if isinstance(row.get("event"), str)
            )
            job._event_index = _next_event_index(job._events)
            last_status = str(last.get("status") or "error")
            if last_status in {"done", "error", "cancelled"}:
                job.status = last_status
            else:
                job.status = "error"
                job.error = "评审服务重启，后台任务已中断；请从草稿恢复或重新评审"
                job.recovery = {"restored_from": "audit_log", "interrupted": True}

            review_id = last.get("result_review_id")
            if job.status == "done" and isinstance(review_id, str):
                job.result = {
                    "review_id": review_id,
                    "items_count": int(last.get("result_items_count") or 0),
                    "restored_from": "audit_log",
                }
                job.recovery = {"restored_from": "audit_log", "interrupted": False}
            if job.status == "error" and not job.error:
                job.error = redact_text(str(last.get("message") or last.get("error") or "review failed"))[:500]
            self._jobs[job_id] = job
            restored += 1
        return restored

    def _prune_jobs(self) -> None:
        now = _now()
        terminal = {"done", "error", "cancelled"}
        for job_id, job in list(self._jobs.items()):
            if job.status in terminal and now - job.updated_at > self.ttl_seconds:
                self._jobs.pop(job_id, None)

        if len(self._jobs) <= self.max_jobs:
            return

        removable = sorted(
            (job for job in self._jobs.values() if job.status in terminal),
            key=lambda job: job.updated_at,
        )
        for job in removable:
            if len(self._jobs) <= self.max_jobs:
                break
            self._jobs.pop(job.job_id, None)

    async def _run_job(self, job: ReviewJob, runner: ReviewJobRunner) -> None:
        job.status = "running"
        job.updated_at = _now()
        try:
            result = await runner(job)
        except asyncio.CancelledError:
            if job.status != "cancelled":
                job.status = "cancelled"
                job.error = "cancelled"
                job.emit("error", {"message": "评审任务已取消"})
            return
        except Exception as exc:  # noqa: BLE001
            job.status = "error"
            job.error = redact_text(str(exc))[:500]
            job.emit("error", {"message": job.error})
            return

        job.result = result
        if isinstance(result, dict) and result.get("status") == "failed":
            job.status = "error"
            job.error = redact_text(str(result.get("message") or result.get("reason") or "review failed"))[:500]
            last_event = job._events[-1]["event"] if job._events else None
            if last_event not in {"review_failed", "error"}:
                job.emit("review_failed", result)
            return

        job.status = "done"
        last_event = job._events[-1]["event"] if job._events else None
        if last_event != "result":
            job.emit("result", {"payload": result})


class RecordingReviewProgressEmitter(ReviewProgressEmitter):
    """ReviewProgressEmitter that also stores every public event on a job."""

    def __init__(self, job: ReviewJob):
        super().__init__()
        self.job = job

    def emit(self, event: str, data: Optional[Dict[str, Any]] = None):
        milestone = MILESTONES.get(event, {"progress": None, "label": event})
        self.job.emit(
            event,
            {
                "progress": milestone.get("progress"),
                "label": milestone.get("label"),
                **(data or {}),
            },
        )
        return super().emit(event, data=data)

    def emit_worker_done(self, dim_key: str, result: Dict[str, Any]):
        super().emit_worker_done(dim_key, result)
        progress = int(15 + self._workers_done_count * WORKER_PROGRESS_STEP)
        event = {
            "progress": progress,
            "label": f"评审方向 {self._workers_done_count}/4 完成",
            "dim_key": dim_key,
            "success": "error" not in result,
            "items_count": len(result.get("items", [])),
            "dim_name": result.get("dimension_name", dim_key),
        }
        if "error" in result:
            event["error"] = redact_text(str(result["error"]))[:200]
        if result.get("telemetry"):
            event["telemetry"] = result["telemetry"]
        self.job.emit("worker_done", event)

    def emit_error(self, error: str):
        return super().emit_error(error)


def _scrub_event_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    blocked = {"prd_content", "raw_materials", "wiki_pages", "user_notes"}
    return {
        key: redact_sensitive(value)
        for key, value in payload.items()
        if key not in blocked
    }


def _event_from_audit_row(row: Dict[str, Any]) -> Dict[str, Any]:
    blocked = {
        "job_id",
        "owner",
        "workspace",
        "prd_name",
        "mode",
        "status",
        "result_review_id",
        "result_items_count",
        "result_status",
    }
    return redact_sensitive({key: value for key, value in row.items() if key not in blocked})


def _next_event_index(events: Deque[Dict[str, Any]]) -> int:
    max_index = -1
    for event in events:
        try:
            max_index = max(max_index, int(event.get("index", -1)))
        except (TypeError, ValueError):
            continue
    return max_index + 1


def _build_audit_record(job: ReviewJob, event: Dict[str, Any]) -> Dict[str, Any]:
    record: Dict[str, Any] = {
        "job_id": job.job_id,
        "owner": redact_text(str(job.owner)),
        "workspace": redact_text(str(job.workspace)),
        "prd_name": redact_text(str(job.prd_name)),
        "mode": redact_text(str(job.mode)),
        "status": job.status,
        "event": event.get("event"),
        "index": event.get("index"),
        "ts": event.get("ts"),
    }
    allowed_event_fields = (
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
    )
    for key in allowed_event_fields:
        if key in event:
            record[key] = event[key]

    telemetry = event.get("telemetry")
    if isinstance(telemetry, dict):
        for key in (
            "duration_ms",
            "tokens_in",
            "tokens_out",
            "input_tokens",
            "output_tokens",
            "cost_usd",
            "prd_context_packet_chars",
        ):
            value = telemetry.get(key)
            if isinstance(value, (int, float)):
                record[key] = value

    payload = event.get("payload")
    if isinstance(payload, dict):
        review_id = payload.get("review_id")
        if isinstance(review_id, str):
            record["result_review_id"] = review_id
        items = payload.get("items")
        if isinstance(items, list):
            record["result_items_count"] = len(items)
        status_value = payload.get("status")
        if isinstance(status_value, str):
            record["result_status"] = status_value
    return record


review_job_store = ReviewJobStore()
