from __future__ import annotations

import asyncio
import json

import pytest


@pytest.mark.asyncio
async def test_review_job_store_records_events_and_result():
    from api.review_jobs import ReviewJobStore

    store = ReviewJobStore(max_events=5)

    async def runner(job):
        job.emit("workers_started", {"mode": "standard", "prd_content": "must not leak"})
        job.emit("worker_done", {"dim_key": "structure", "items_count": 2})
        return {"review_id": "rev_1", "items": []}

    job = store.create_job(
        owner="pm-a",
        workspace="workspace-alpha",
        prd_name="alpha.md",
        mode="standard",
        runner=runner,
    )
    await job.wait()

    snapshot = store.get_job(job.job_id, owner="pm-a")

    assert snapshot["status"] == "done"
    assert snapshot["result"] == {"review_id": "rev_1", "items": []}
    assert "request_fingerprint" not in snapshot
    assert [event["event"] for event in snapshot["events"]] == [
        "workers_started",
        "worker_done",
        "result",
    ]
    assert "prd_content" not in str(snapshot)


@pytest.mark.asyncio
async def test_review_job_store_snapshot_redacts_metadata_secrets():
    from api.review_jobs import ReviewJobStore

    store = ReviewJobStore()
    fake_key = "sk-01234567890abcdefABCDEFghij"

    async def runner(_job):
        return {"review_id": "rev_1", "items": []}

    job = store.create_job(
        owner=f"pm-a-{fake_key}",
        workspace=f"workspace-alpha-{fake_key}",
        prd_name=f"alpha-{fake_key}.md",
        mode=f"standard-{fake_key}",
        runner=runner,
    )
    await job.wait()

    snapshot = store.get_job(job.job_id, owner=f"pm-a-{fake_key}")
    serialized = json.dumps(snapshot, ensure_ascii=False)

    assert fake_key not in serialized
    assert snapshot["owner"] == "pm-a-[REDACTED_SECRET]"
    assert snapshot["workspace"] == "workspace-alpha-[REDACTED_SECRET]"
    assert snapshot["prd_name"] == "alpha-[REDACTED_SECRET].md"
    assert snapshot["mode"] == "standard-[REDACTED_SECRET]"


@pytest.mark.asyncio
async def test_review_job_store_snapshot_redacts_result_secrets():
    from api.review_jobs import ReviewJobStore

    store = ReviewJobStore()
    fake_key = "sk-01234567890abcdefABCDEFghij"

    async def runner(_job):
        return {
            "review_id": "rev_1",
            "items": [],
            "telemetry": {
                "duration_ms": 100,
                "provider_api_key": fake_key,
                "error": f"provider failed token={fake_key}",
            },
        }

    job = store.create_job(
        owner="pm-a",
        workspace="workspace-alpha",
        prd_name="alpha.md",
        mode="standard",
        runner=runner,
    )
    await job.wait()

    snapshot = store.get_job(job.job_id, owner="pm-a")
    serialized = json.dumps(snapshot["result"], ensure_ascii=False)

    assert fake_key not in serialized
    assert snapshot["result"]["telemetry"]["duration_ms"] == 100
    assert snapshot["result"]["telemetry"]["provider_api_key"] == "[REDACTED_SECRET]"
    assert "token=[REDACTED_SECRET]" in snapshot["result"]["telemetry"]["error"]


@pytest.mark.asyncio
async def test_review_job_store_reuses_running_job_for_same_reviewer_and_prd():
    from api.review_jobs import ReviewJobStore

    store = ReviewJobStore()
    gate = asyncio.Event()
    calls = 0

    async def runner(_job):
        nonlocal calls
        calls += 1
        await gate.wait()
        return {"review_id": "rev_1", "items": []}

    first = store.create_job(
        owner="pm-a",
        workspace="workspace-alpha",
        prd_name="alpha.md",
        mode="standard",
        runner=runner,
    )
    second = store.create_job(
        owner="pm-a",
        workspace="workspace-alpha",
        prd_name="alpha.md",
        mode="standard",
        runner=runner,
    )

    await asyncio.sleep(0)
    gate.set()
    await first.wait()

    assert second is first
    assert calls == 1


@pytest.mark.asyncio
async def test_review_job_store_reports_when_running_job_is_reused():
    from api.review_jobs import ReviewJobStore

    store = ReviewJobStore()
    gate = asyncio.Event()

    async def runner(_job):
        await gate.wait()
        return {"review_id": "rev_1", "items": []}

    first, first_reused = store.create_job_with_reuse_info(
        owner="pm-a",
        workspace="workspace-alpha",
        prd_name="alpha.md",
        mode="standard",
        request_fingerprint="content-a",
        runner=runner,
    )
    second, second_reused = store.create_job_with_reuse_info(
        owner="pm-a",
        workspace="workspace-alpha",
        prd_name="alpha.md",
        mode="standard",
        request_fingerprint="content-a",
        runner=runner,
    )

    gate.set()
    await first.wait()

    assert first_reused is False
    assert second_reused is True
    assert second is first


@pytest.mark.asyncio
async def test_review_job_store_does_not_reuse_same_prd_name_with_different_fingerprint():
    from api.review_jobs import ReviewJobStore

    store = ReviewJobStore()
    gate = asyncio.Event()

    async def runner(_job):
        await gate.wait()
        return {"review_id": "rev_1", "items": []}

    first = store.create_job(
        owner="pm-a",
        workspace="workspace-alpha",
        prd_name="alpha.md",
        mode="standard",
        request_fingerprint="content-a",
        runner=runner,
    )
    second = store.create_job(
        owner="pm-a",
        workspace="workspace-alpha",
        prd_name="alpha.md",
        mode="standard",
        request_fingerprint="content-b",
        runner=runner,
    )

    gate.set()
    await first.wait()
    await second.wait()

    assert second is not first


@pytest.mark.asyncio
async def test_review_job_store_writes_sanitized_audit_log(tmp_path):
    from api.review_jobs import ReviewJobStore

    store = ReviewJobStore(max_events=5)
    audit_path = tmp_path / "logs" / "review_jobs.jsonl"
    fake_key = "sk-01234567890abcdefABCDEFghij"

    async def runner(job):
        job.emit("workers_started", {"mode": "standard", "prd_content": "secret prd"})
        job.emit(
            "worker_done",
            {
                "dim_key": "quality",
                "items_count": 1,
                "error": "Request timed out.",
                "telemetry": {
                    "duration_ms": 1200,
                    "prd_context_packet_chars": 8000,
                    "cost_usd": 0.037,
                },
                "raw_materials": ["must not leak"],
            },
        )
        return {
            "review_id": "rev_1",
            "items": [{"problem": "PRD derived text must not be logged"}],
        }

    job = store.create_job(
        owner=f"pm-a-{fake_key}",
        workspace=f"workspace-alpha-{fake_key}",
        prd_name=f"alpha-{fake_key}.md",
        mode="standard",
        runner=runner,
        audit_path=audit_path,
    )
    await job.wait()

    rows = [
        json.loads(line)
        for line in audit_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    assert [row["event"] for row in rows] == [
        "workers_started",
        "worker_done",
        "result",
    ]
    assert rows[1]["dim_key"] == "quality"
    assert rows[1]["items_count"] == 1
    assert rows[1]["duration_ms"] == 1200
    assert rows[1]["prd_context_packet_chars"] == 8000
    assert rows[1]["cost_usd"] == 0.037
    assert rows[-1]["result_review_id"] == "rev_1"
    assert rows[-1]["result_items_count"] == 1
    serialized = json.dumps(rows, ensure_ascii=False)
    assert fake_key not in serialized
    assert "[REDACTED_SECRET]" in serialized
    assert "secret prd" not in serialized
    assert "must not leak" not in serialized
    assert "PRD derived text" not in serialized


@pytest.mark.asyncio
async def test_review_job_store_keeps_failed_job_queryable():
    from api.review_jobs import ReviewJobStore

    store = ReviewJobStore()

    async def runner(_job):
        raise RuntimeError("gateway timeout")

    job = store.create_job(
        owner="pm-a",
        workspace="workspace-alpha",
        prd_name="alpha.md",
        mode="standard",
        runner=runner,
    )
    await job.wait()

    snapshot = store.get_job(job.job_id, owner="pm-a")

    assert snapshot["status"] == "error"
    assert snapshot["error"] == "gateway timeout"
    assert snapshot["events"][-1]["event"] == "error"


def test_review_job_store_restores_done_job_from_audit_log(tmp_path):
    import json

    from api.review_jobs import ReviewJobStore

    audit_path = tmp_path / "logs" / "review_jobs.jsonl"
    audit_path.parent.mkdir(parents=True)
    rows = [
        {
            "job_id": "rjob_restore",
            "owner": "pm-a",
            "workspace": "workspace-alpha",
            "prd_name": "alpha.md",
            "mode": "quick",
            "status": "running",
            "event": "workers_started",
            "index": 0,
            "ts": 10,
            "progress": 15,
        },
        {
            "job_id": "rjob_restore",
            "owner": "pm-a",
            "workspace": "workspace-alpha",
            "prd_name": "alpha.md",
            "mode": "quick",
            "status": "done",
            "event": "result",
            "index": 1,
            "ts": 20,
            "result_review_id": "rev_restore",
            "result_items_count": 2,
        },
    ]
    audit_path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows),
        encoding="utf-8",
    )

    store = ReviewJobStore()
    restored = store.restore_from_audit_log(audit_path)
    snapshot = store.get_job("rjob_restore", owner="pm-a")

    assert restored == 1
    assert snapshot["status"] == "done"
    assert snapshot["result"] == {
        "review_id": "rev_restore",
        "items_count": 2,
        "restored_from": "audit_log",
    }
    assert [event["event"] for event in snapshot["events"]] == ["workers_started", "result"]


def test_review_job_store_marks_interrupted_audit_job_recoverable(tmp_path):
    import json

    from api.review_jobs import ReviewJobStore

    audit_path = tmp_path / "logs" / "review_jobs.jsonl"
    audit_path.parent.mkdir(parents=True)
    audit_path.write_text(
        json.dumps(
            {
                "job_id": "rjob_interrupted",
                "owner": "pm-a",
                "workspace": "workspace-alpha",
                "prd_name": "alpha.md",
                "mode": "standard",
                "status": "running",
                "event": "worker_done",
                "index": 0,
                "ts": 10,
                "dim_key": "structure",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    store = ReviewJobStore()
    store.restore_from_audit_log(audit_path)
    snapshot = store.get_job("rjob_interrupted", owner="pm-a")

    assert snapshot["status"] == "error"
    assert "服务重启" in snapshot["error"]
    assert snapshot["recovery"]["restored_from"] == "audit_log"
    assert snapshot["recovery"]["interrupted"] is True


@pytest.mark.asyncio
async def test_review_job_store_redacts_secrets_from_errors_and_audit(tmp_path):
    from api.review_jobs import ReviewJobStore

    fake_key = "sk-01234567890abcdefABCDEFghij"
    audit_path = tmp_path / "logs" / "review_jobs.jsonl"
    store = ReviewJobStore(max_events=5)

    async def runner(job):
        job.emit("worker_done", {"dim_key": "quality", "error": f"provider rejected {fake_key}"})
        raise RuntimeError(f"upstream leaked Bearer {fake_key}")

    job = store.create_job(
        owner="pm-a",
        workspace="workspace-alpha",
        prd_name="alpha.md",
        mode="standard",
        runner=runner,
        audit_path=audit_path,
    )
    await job.wait()

    snapshot = store.get_job(job.job_id, owner="pm-a")
    rows = [
        json.loads(line)
        for line in audit_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    serialized_snapshot = json.dumps(snapshot, ensure_ascii=False)
    serialized_audit = json.dumps(rows, ensure_ascii=False)

    assert fake_key not in serialized_snapshot
    assert fake_key not in serialized_audit
    assert "[REDACTED_SECRET]" in serialized_snapshot
    assert "[REDACTED_SECRET]" in serialized_audit


def test_review_job_snapshot_redacts_preexisting_error_secret():
    from api.review_jobs import ReviewJob

    fake_key = "sk-01234567890abcdefABCDEFghij"
    job = ReviewJob(
        job_id="rjob_test",
        owner="pm-a",
        workspace="workspace-alpha",
        prd_name="alpha.md",
        mode="standard",
    )
    job.status = "error"
    job.error = f"provider failed with api_key={fake_key}"

    snapshot = job.snapshot()

    assert fake_key not in snapshot["error"]
    assert "api_key=[REDACTED_SECRET]" in snapshot["error"]


@pytest.mark.asyncio
async def test_review_job_failed_payload_does_not_emit_result_event():
    from api.review_jobs import ReviewJobStore

    store = ReviewJobStore()

    async def runner(job):
        job.emit(
            "review_failed",
            {"status": "failed", "message": "评审方向未完整返回", "items": []},
        )
        return {"status": "failed", "message": "评审方向未完整返回", "items": []}

    job = store.create_job(
        owner="pm-a",
        workspace="workspace-alpha",
        prd_name="alpha.md",
        mode="standard",
        runner=runner,
    )
    await job.wait()

    snapshot = store.get_job(job.job_id, owner="pm-a")

    assert snapshot["status"] == "error"
    assert snapshot["error"] == "评审方向未完整返回"
    assert [event["event"] for event in snapshot["events"]] == ["review_failed"]


@pytest.mark.asyncio
async def test_review_job_store_enforces_owner_isolation():
    from fastapi import HTTPException

    from api.review_jobs import ReviewJobStore

    store = ReviewJobStore()

    async def runner(_job):
        return {"ok": True}

    job = store.create_job(
        owner="pm-a",
        workspace="workspace-alpha",
        prd_name="alpha.md",
        mode="quick",
        runner=runner,
    )
    await job.wait()

    with pytest.raises(HTTPException) as exc:
        store.get_job(job.job_id, owner="pm-b")

    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_review_job_store_lists_jobs_with_owner_scope():
    from api.review_jobs import ReviewJobStore

    store = ReviewJobStore()

    async def runner(_job):
        return {"ok": True}

    job_a = store.create_job(
        owner="pm-a",
        workspace="workspace-alpha",
        prd_name="alpha.md",
        mode="standard",
        runner=runner,
    )
    job_b = store.create_job(
        owner="pm-b",
        workspace="workspace-beta",
        prd_name="beta.md",
        mode="quick",
        runner=runner,
    )
    await job_a.wait()
    await job_b.wait()

    owner_jobs = store.list_jobs(owner="pm-a")
    admin_jobs = store.list_jobs(admin=True)

    assert [job["owner"] for job in owner_jobs] == ["pm-a"]
    assert {job["owner"] for job in admin_jobs} == {"pm-a", "pm-b"}


@pytest.mark.asyncio
async def test_review_job_store_prunes_old_terminal_jobs_without_dropping_running_jobs():
    from api.review_jobs import ReviewJobStore

    store = ReviewJobStore(ttl_seconds=1, max_jobs=2)
    gate = asyncio.Event()

    async def done_runner(_job):
        return {"ok": True}

    async def running_runner(_job):
        await gate.wait()
        return {"ok": True}

    old_done = store.create_job(
        owner="pm-a",
        workspace="workspace-alpha",
        prd_name="old.md",
        mode="standard",
        runner=done_runner,
    )
    fresh_done = store.create_job(
        owner="pm-a",
        workspace="workspace-alpha",
        prd_name="fresh.md",
        mode="standard",
        runner=done_runner,
    )
    running = store.create_job(
        owner="pm-a",
        workspace="workspace-alpha",
        prd_name="running.md",
        mode="standard",
        runner=running_runner,
    )
    await old_done.wait()
    await fresh_done.wait()
    old_done.updated_at -= 3600

    jobs = store.list_jobs(owner="pm-a", limit=10)
    gate.set()
    await running.wait()

    assert {job["prd_name"] for job in jobs} == {"fresh.md", "running.md"}


@pytest.mark.asyncio
async def test_review_job_store_can_wait_for_future_events():
    from api.review_jobs import ReviewJobStore

    store = ReviewJobStore()
    gate = asyncio.Event()

    async def runner(job):
        await gate.wait()
        job.emit("worker_done", {"dim_key": "quality"})
        return {"ok": True}

    job = store.create_job(
        owner="pm-a",
        workspace="workspace-alpha",
        prd_name="alpha.md",
        mode="standard",
        runner=runner,
    )

    waiter = asyncio.create_task(job.wait_for_event(after_index=-1, timeout=1))
    gate.set()
    event = await waiter
    await job.wait()

    assert event is not None
    assert event["event"] == "worker_done"


@pytest.mark.asyncio
async def test_review_job_store_can_cancel_running_job():
    from api.review_jobs import ReviewJobStore

    store = ReviewJobStore()
    gate = asyncio.Event()

    async def runner(_job):
        await gate.wait()
        return {"ok": True}

    job = store.create_job(
        owner="pm-a",
        workspace="workspace-alpha",
        prd_name="alpha.md",
        mode="standard",
        runner=runner,
    )

    store.cancel_job(job.job_id, owner="pm-a")
    await asyncio.sleep(0)
    await job.wait()

    snapshot = store.get_job(job.job_id, owner="pm-a")
    assert snapshot["status"] == "cancelled"
    assert [event["event"] for event in snapshot["events"]].count("error") == 1


def test_recording_emitter_writes_job_events():
    from api.review_jobs import RecordingReviewProgressEmitter, ReviewJob

    job = ReviewJob(
        job_id="rjob_test",
        owner="pm-a",
        workspace="workspace-alpha",
        prd_name="alpha.md",
        mode="standard",
    )
    emitter = RecordingReviewProgressEmitter(job)

    emitter.emit("workers_started", {"mode": "standard", "prd_content": "must not leak"})
    emitter.emit_worker_done(
        "structure",
        {"dimension_name": "业务", "items": [{"id": "R-1"}]},
    )

    snapshot = job.snapshot()
    assert [event["event"] for event in snapshot["events"]] == [
        "workers_started",
        "worker_done",
    ]
    assert snapshot["events"][0]["progress"] == 15
    assert snapshot["events"][1]["progress"] > 15
    assert snapshot["events"][1]["dim_key"] == "structure"
    assert "worker" not in snapshot["events"][1]["label"].lower()
    assert "prd_content" not in str(snapshot)


def test_recording_emitter_records_single_error_event():
    from api.review_jobs import RecordingReviewProgressEmitter, ReviewJob

    job = ReviewJob(
        job_id="rjob_test",
        owner="pm-a",
        workspace="workspace-alpha",
        prd_name="alpha.md",
        mode="standard",
    )
    emitter = RecordingReviewProgressEmitter(job)

    emitter.emit_error("gateway timeout")

    snapshot = job.snapshot()
    assert [event["event"] for event in snapshot["events"]] == ["error"]
    assert snapshot["events"][0]["message"] == "gateway timeout"
