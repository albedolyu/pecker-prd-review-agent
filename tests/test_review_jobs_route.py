from __future__ import annotations

import asyncio
import json

import pytest


@pytest.mark.asyncio
async def test_start_review_job_returns_queryable_snapshot(monkeypatch, tmp_path):
    from api.routes import review_jobs
    from api.routes.review import ReviewRequest

    workspace = tmp_path / "workspace-alpha"
    workspace.mkdir()

    async def fake_runner(*, req, user, ws_abs_path, emitter, project_root):
        emitter.emit("workers_started", {"mode": req.mode})
        return {
            "review_id": "rev_job_1",
            "reviewer": user["reviewer"],
            "workspace": req.workspace,
            "items": [],
        }

    monkeypatch.setattr(review_jobs, "_run_review_job_pipeline", fake_runner)
    monkeypatch.setattr(review_jobs, "get_workspace_dir", lambda _name: workspace)
    monkeypatch.setattr(review_jobs, "require_workspace_access", lambda _ws, _user: None)
    monkeypatch.setattr(review_jobs, "check_budget", lambda *_args, **_kwargs: {"ok": True})

    req = ReviewRequest(
        prd_content="# Demo",
        workspace="workspace-alpha",
        prd_name="alpha.md",
        reviewer="pm-a",
        mode="standard",
    )

    started = await review_jobs.start_review_job(
        req=req,
        user={"reviewer": "pm-a", "readonly": False},
        project_root=tmp_path,
    )
    job_id = started["job_id"]
    await review_jobs.review_job_store.get_job_ref(job_id, owner="pm-a").wait()

    snapshot = await review_jobs.get_review_job(
        job_id=job_id,
        user={"reviewer": "pm-a", "readonly": False},
    )

    assert snapshot["status"] == "done"
    assert snapshot["result"]["review_id"] == "rev_job_1"
    assert snapshot["events"][0]["event"] == "workers_started"


@pytest.mark.asyncio
async def test_start_review_job_response_redacts_metadata_secrets(monkeypatch, tmp_path):
    from api.routes import review_jobs
    from api.routes.review import ReviewRequest

    workspace = tmp_path / "workspace-alpha"
    workspace.mkdir()
    fake_key = "sk-01234567890abcdefABCDEFghij"

    async def fake_runner(**_kwargs):
        return {"review_id": "rev_secret", "items": []}

    monkeypatch.setattr(review_jobs, "_run_review_job_pipeline", fake_runner)
    monkeypatch.setattr(review_jobs, "get_workspace_dir", lambda _name: workspace)
    monkeypatch.setattr(review_jobs, "require_workspace_access", lambda _ws, _user: None)
    monkeypatch.setattr(review_jobs, "check_budget", lambda *_args, **_kwargs: {"ok": True})

    started = await review_jobs.start_review_job(
        req=ReviewRequest(
            prd_content="# Demo",
            workspace=f"workspace-alpha-{fake_key}",
            prd_name=f"alpha-{fake_key}.md",
            reviewer="pm-a",
            mode="quick",
        ),
        user={"reviewer": "pm-a", "readonly": False},
        project_root=tmp_path,
    )

    serialized = json.dumps(started, ensure_ascii=False)

    assert fake_key not in serialized
    assert started["workspace"] == "workspace-alpha-[REDACTED_SECRET]"
    assert started["prd_name"] == "alpha-[REDACTED_SECRET].md"
    assert started["mode"] == "quick"


@pytest.mark.asyncio
async def test_review_job_snapshot_is_owner_scoped(monkeypatch, tmp_path):
    from fastapi import HTTPException

    from api.routes import review_jobs
    from api.routes.review import ReviewRequest

    workspace = tmp_path / "workspace-alpha"
    workspace.mkdir()

    async def fake_runner(**_kwargs):
        return {"review_id": "rev_job_2", "items": []}

    monkeypatch.setattr(review_jobs, "_run_review_job_pipeline", fake_runner)
    monkeypatch.setattr(review_jobs, "get_workspace_dir", lambda _name: workspace)
    monkeypatch.setattr(review_jobs, "require_workspace_access", lambda _ws, _user: None)
    monkeypatch.setattr(review_jobs, "check_budget", lambda *_args, **_kwargs: {"ok": True})

    started = await review_jobs.start_review_job(
        req=ReviewRequest(
            prd_content="# Demo",
            workspace="workspace-alpha",
            prd_name="alpha.md",
            reviewer="pm-a",
            mode="quick",
        ),
        user={"reviewer": "pm-a", "readonly": False},
        project_root=tmp_path,
    )

    with pytest.raises(HTTPException) as exc:
        await review_jobs.get_review_job(
            job_id=started["job_id"],
            user={"reviewer": "pm-b", "readonly": False},
        )

    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_start_review_job_marks_reused_running_job(monkeypatch, tmp_path):
    from api.routes import review_jobs
    from api.routes.review import ReviewRequest

    workspace = tmp_path / "workspace-alpha"
    workspace.mkdir()
    gate = asyncio.Event()
    calls = 0

    async def fake_runner(**_kwargs):
        nonlocal calls
        calls += 1
        await gate.wait()
        return {"review_id": "rev_reused", "items": []}

    monkeypatch.setattr(review_jobs, "_run_review_job_pipeline", fake_runner)
    monkeypatch.setattr(review_jobs, "get_workspace_dir", lambda _name: workspace)
    monkeypatch.setattr(review_jobs, "require_workspace_access", lambda _ws, _user: None)
    monkeypatch.setattr(review_jobs, "check_budget", lambda *_args, **_kwargs: {"ok": True})

    req = ReviewRequest(
        prd_content="# Demo",
        workspace="workspace-alpha",
        prd_name=f"{tmp_path.name}-alpha.md",
        reviewer="pm-a",
        mode="standard",
    )

    first = await review_jobs.start_review_job(
        req=req,
        user={"reviewer": "pm-a", "readonly": False},
        project_root=tmp_path,
    )
    second = await review_jobs.start_review_job(
        req=req,
        user={"reviewer": "pm-a", "readonly": False},
        project_root=tmp_path,
    )

    gate.set()
    await review_jobs.review_job_store.get_job_ref(first["job_id"], owner="pm-a").wait()

    assert first["reused"] is False
    assert second["reused"] is True
    assert second["job_id"] == first["job_id"]
    assert calls == 1


@pytest.mark.asyncio
async def test_start_review_job_does_not_reuse_when_wiki_content_changes(monkeypatch, tmp_path):
    from api.routes import review_jobs
    from api.routes.review import ReviewRequest

    workspace = tmp_path / "workspace-alpha"
    workspace.mkdir()
    gate = asyncio.Event()
    calls = 0

    async def fake_runner(**_kwargs):
        nonlocal calls
        calls += 1
        await gate.wait()
        return {"review_id": f"rev_{calls}", "items": []}

    monkeypatch.setattr(review_jobs, "_run_review_job_pipeline", fake_runner)
    monkeypatch.setattr(review_jobs, "get_workspace_dir", lambda _name: workspace)
    monkeypatch.setattr(review_jobs, "require_workspace_access", lambda _ws, _user: None)
    monkeypatch.setattr(review_jobs, "check_budget", lambda *_args, **_kwargs: {"ok": True})

    base_req = ReviewRequest(
        prd_content="# Demo",
        workspace="workspace-alpha",
        prd_name=f"{tmp_path.name}-alpha.md",
        reviewer="pm-a",
        mode="standard",
        wiki_pages={"guide.md": "old guide"},
    )
    changed_req = base_req.model_copy(update={"wiki_pages": {"guide.md": "new guide"}})

    first = await review_jobs.start_review_job(
        req=base_req,
        user={"reviewer": "pm-a", "readonly": False},
        project_root=tmp_path,
    )
    second = await review_jobs.start_review_job(
        req=changed_req,
        user={"reviewer": "pm-a", "readonly": False},
        project_root=tmp_path,
    )

    gate.set()
    await review_jobs.review_job_store.get_job_ref(first["job_id"], owner="pm-a").wait()
    await review_jobs.review_job_store.get_job_ref(second["job_id"], owner="pm-a").wait()

    assert first["reused"] is False
    assert second["reused"] is False
    assert second["job_id"] != first["job_id"]
    assert calls == 2


@pytest.mark.asyncio
async def test_default_review_job_runner_returns_signed_review_result(monkeypatch, tmp_path):
    from api.review_jobs import RecordingReviewProgressEmitter, ReviewJob
    from api.routes import review_jobs
    from api.routes.review import ReviewRequest

    monkeypatch.setenv("PECKER_SIGNATURE_SECRET", "unit-test-signature-secret-32-chars")
    monkeypatch.setenv("PECKER_REVIEW_JOB_PIPELINE", "lightweight")

    async def fake_parallel_review(*_args, **kwargs):
        assert kwargs["thread_id"] == "review-job:rjob_default"
        assert kwargs["checkpointer"].checkpoint_path.parent.name == ".pecker_checkpoints"
        on_worker_done = kwargs["on_worker_done"]
        on_worker_done(
            "structure",
            {
                "dimension": "structure",
                "dimension_name": "业务完整性",
                "items": [{"id": "R-1"}],
                "usage": {"input_tokens": 1, "output_tokens": 1},
                "telemetry": {"duration_ms": 800, "recovered": True},
            },
        )
        return {
            "workers": [
                {
                    "dimension": "structure",
                    "dimension_name": "业务完整性",
                    "items": [{"id": "R-1"}],
                    "usage": {"input_tokens": 1, "output_tokens": 1},
                    "telemetry": {"duration_ms": 800, "recovered": True},
                }
            ],
            "merged_items": [
                {
                    "id": "R-1",
                    "dimension": "业务完整性",
                    "severity": "must",
                    "location": "目标",
                    "problem": "目标不清楚",
                }
            ],
            "total_usage": {"input_tokens": 1, "output_tokens": 1},
            "orchestrator": "langgraph",
            "resilience": {"failed_workers": 0, "recovered_workers": 1},
        }

    monkeypatch.setattr(review_jobs, "_parallel_review_for_job", fake_parallel_review)
    monkeypatch.setattr(review_jobs, "record_review_cost", lambda *_args, **_kwargs: None)

    job = ReviewJob(
        job_id="rjob_default",
        owner="pm-a",
        workspace="workspace-alpha",
        prd_name="alpha.md",
        mode="quick",
    )
    emitter = RecordingReviewProgressEmitter(job)

    result = await review_jobs._run_review_job_pipeline(
        req=ReviewRequest(
            prd_content="# Demo",
            workspace="workspace-alpha",
            prd_name="alpha.md",
            reviewer="pm-a",
            mode="quick",
        ),
        user={"reviewer": "pm-a"},
        ws_abs_path=str(tmp_path / "workspace-alpha"),
        emitter=emitter,
        project_root=tmp_path,
    )

    assert result["reviewer"] == "pm-a"
    assert result["workspace"] == "workspace-alpha"
    assert result["items"][0]["id"] == "R-1"
    assert result["signature"]
    assert result["telemetry"]["workers"]["structure"]["duration_ms"] == 800
    assert result["telemetry"]["workers"]["structure"]["recovered"] is True
    assert result["telemetry"]["orchestrator"] == "langgraph"
    assert result["telemetry"]["resilience"]["recovered_workers"] == 1
    assert [event["event"] for event in job.snapshot()["events"]][:4] == [
        "uploaded",
        "wiki_scanned",
        "review_queued",
        "workers_started",
    ]


@pytest.mark.asyncio
async def test_review_job_completion_persists_phase3_draft(monkeypatch, tmp_path):
    import json

    from api.review_jobs import RecordingReviewProgressEmitter, ReviewJob
    from api.routes import review_jobs
    from api.routes.review import ReviewRequest

    monkeypatch.setenv("PECKER_SIGNATURE_SECRET", "unit-test-signature-secret-32-chars")
    monkeypatch.setenv("PECKER_REVIEW_JOB_PIPELINE", "lightweight")

    async def fake_parallel_review(*_args, **kwargs):
        kwargs["on_worker_done"](
            "structure",
            {
                "dimension": "structure",
                "dimension_name": "业务完整性",
                "items": [{"id": "R-1"}],
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
        )
        return {
            "workers": [
                {
                    "dimension": "structure",
                    "dimension_name": "业务完整性",
                    "items": [{"id": "R-1"}],
                    "usage": {"input_tokens": 1, "output_tokens": 1},
                }
            ],
            "merged_items": [
                {
                    "id": "R-1",
                    "dimension": "业务完整性",
                    "severity": "must",
                    "location": "目标",
                    "problem": "目标不清楚",
                }
            ],
            "total_usage": {"input_tokens": 1, "output_tokens": 1},
        }

    monkeypatch.setattr(review_jobs, "_parallel_review_for_job", fake_parallel_review)
    monkeypatch.setattr(review_jobs, "record_review_cost", lambda *_args, **_kwargs: None)

    job = ReviewJob(
        job_id="rjob_default",
        owner="pm-a",
        workspace="workspace-alpha",
        prd_name="alpha.md",
        mode="quick",
    )
    emitter = RecordingReviewProgressEmitter(job)

    result = await review_jobs._run_review_job_pipeline(
        req=ReviewRequest(
            prd_content="# Demo",
            raw_materials=["补充材料"],
            user_notes="重点看字段",
            workspace="workspace-alpha",
            prd_name="alpha.md",
            reviewer="pm-a",
            mode="quick",
        ),
        user={"reviewer": "pm-a"},
        ws_abs_path=str(tmp_path / "workspace-alpha"),
        emitter=emitter,
        project_root=tmp_path,
    )

    draft_path = tmp_path / ".pecker_drafts" / "pm-a_draft.json"
    draft = json.loads(draft_path.read_text(encoding="utf-8"))

    assert result["review_id"] == draft["review_result"]["review_id"]
    assert draft["phase"] == 3
    assert draft["prd_content"] == "# Demo"
    assert draft["raw_materials"] == ["补充材料"]
    assert draft["user_notes"] == "重点看字段"
    assert draft["item_decisions"] == {}
    assert draft["workspace"] == "workspace-alpha"


@pytest.mark.asyncio
async def test_stream_review_job_pipeline_persists_phase3_draft(monkeypatch, tmp_path):
    import json

    from api.review_jobs import RecordingReviewProgressEmitter, ReviewJob
    from api.routes import review as review_route
    from api.routes import review_jobs
    from api.routes.review import ReviewRequest

    monkeypatch.delenv("PECKER_REVIEW_JOB_PIPELINE", raising=False)

    class FakeResponse:
        async def body_iterator(self):
            yield 'event: uploaded\ndata: {"event":"uploaded","progress":0}\n\n'
            yield (
                'event: result\n'
                'data: {"event":"result","progress":100,"payload":{"review_id":"rev_stream","reviewer":"pm-a","workspace":"workspace-alpha","prd_name":"alpha.md","mode":"standard","items":[],"workers":[],"usage":{},"goshawk_summary":null,"signature":"sig"}}\n\n'
            )

    async def fake_run_review(req, request, user):
        assert await request.is_disconnected() is False
        response = FakeResponse()
        response.body_iterator = response.body_iterator()
        return response

    monkeypatch.setattr(review_route, "run_review", fake_run_review)

    job = ReviewJob(
        job_id="rjob_stream",
        owner="pm-a",
        workspace="workspace-alpha",
        prd_name="alpha.md",
        mode="standard",
    )
    emitter = RecordingReviewProgressEmitter(job)

    result = await review_jobs._run_review_job_pipeline(
        req=ReviewRequest(
            prd_content="# Stream PRD",
            workspace="workspace-alpha",
            prd_name="alpha.md",
            reviewer="pm-a",
            mode="standard",
        ),
        user={"reviewer": "pm-a"},
        ws_abs_path=str(tmp_path / "workspace-alpha"),
        emitter=emitter,
        project_root=tmp_path,
    )

    draft = json.loads(
        (tmp_path / ".pecker_drafts" / "pm-a_draft.json").read_text(encoding="utf-8")
    )

    assert result["review_id"] == "rev_stream"
    assert draft["phase"] == 3
    assert draft["review_result"]["review_id"] == "rev_stream"
    assert draft["prd_content"] == "# Stream PRD"


def test_completed_job_draft_does_not_overwrite_another_prd(tmp_path):
    import json

    from api.routes import review_jobs
    from api.routes.drafts import DraftPayload, write_draft_file
    from api.routes.review import ReviewRequest

    write_draft_file(
        tmp_path,
        "pm-a",
        DraftPayload(
            phase=1,
            prd_name="beta.md",
            prd_content="# Beta",
            workspace="workspace-beta",
        ),
    )

    review_jobs._persist_completed_review_draft(
        req=ReviewRequest(
            prd_content="# Alpha",
            workspace="workspace-alpha",
            prd_name="alpha.md",
            reviewer="pm-a",
            mode="standard",
        ),
        reviewer="pm-a",
        project_root=tmp_path,
        review_result={"review_id": "rev_alpha", "items": []},
    )

    draft = json.loads(
        (tmp_path / ".pecker_drafts" / "pm-a_draft.json").read_text(encoding="utf-8")
    )

    assert draft["prd_name"] == "beta.md"
    assert draft["prd_content"] == "# Beta"
    assert draft["review_result"] is None


def test_completed_job_draft_does_not_overwrite_same_name_in_another_workspace(tmp_path):
    import json

    from api.routes import review_jobs
    from api.routes.drafts import DraftPayload, write_draft_file
    from api.routes.review import ReviewRequest

    write_draft_file(
        tmp_path,
        "pm-a",
        DraftPayload(
            phase=1,
            prd_name="需求.md",
            prd_content="# Workspace Beta",
            workspace="workspace-beta",
        ),
    )

    review_jobs._persist_completed_review_draft(
        req=ReviewRequest(
            prd_content="# Workspace Alpha",
            workspace="workspace-alpha",
            prd_name="需求.md",
            reviewer="pm-a",
            mode="standard",
        ),
        reviewer="pm-a",
        project_root=tmp_path,
        review_result={"review_id": "rev_alpha", "items": []},
    )

    draft = json.loads(
        (tmp_path / ".pecker_drafts" / "pm-a_draft.json").read_text(encoding="utf-8")
    )

    assert draft["workspace"] == "workspace-beta"
    assert draft["prd_content"] == "# Workspace Beta"
    assert draft["review_result"] is None


def test_completed_job_draft_overwrites_expired_other_prd_draft(tmp_path):
    import json
    from datetime import datetime, timedelta

    from api.routes import review_jobs
    from api.routes.review import ReviewRequest

    draft_dir = tmp_path / ".pecker_drafts"
    draft_dir.mkdir(parents=True)
    (draft_dir / "pm-a_draft.json").write_text(
        json.dumps(
            {
                "ts": (datetime.now() - timedelta(days=4)).strftime("%Y-%m-%dT%H:%M:%S"),
                "reviewer": "pm-a",
                "phase": 1,
                "prd_name": "expired-beta.md",
                "prd_content": "# Expired Beta",
                "mode": "standard",
                "raw_materials": [],
                "user_notes": "",
                "review_result": None,
                "item_decisions": {},
                "confirmed_report_markdown": "",
                "workspace": "workspace-beta",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    review_jobs._persist_completed_review_draft(
        req=ReviewRequest(
            prd_content="# Alpha",
            workspace="workspace-alpha",
            prd_name="alpha.md",
            reviewer="pm-a",
            mode="standard",
        ),
        reviewer="pm-a",
        project_root=tmp_path,
        review_result={"review_id": "rev_alpha", "items": []},
    )

    draft = json.loads(
        (tmp_path / ".pecker_drafts" / "pm-a_draft.json").read_text(encoding="utf-8")
    )

    assert draft["prd_name"] == "alpha.md"
    assert draft["workspace"] == "workspace-alpha"
    assert draft["review_result"]["review_id"] == "rev_alpha"


@pytest.mark.asyncio
async def test_review_job_can_reuse_existing_sse_pipeline(monkeypatch):
    from api.review_jobs import ReviewJob
    from api.routes import review as review_route
    from api.routes import review_jobs
    from api.routes.review import ReviewRequest

    class FakeResponse:
        async def body_iterator(self):
            yield 'event: uploaded\ndata: {"event":"uploaded","progress":0}\n\n'
            yield (
                'event: result\n'
                'data: {"event":"result","progress":100,"payload":{"review_id":"rev_sse","items":[]}}\n\n'
            )

    async def fake_run_review(req, request, user):
        assert req.prd_name == "alpha.md"
        assert user["reviewer"] == "pm-a"
        assert await request.is_disconnected() is False
        response = FakeResponse()
        response.body_iterator = response.body_iterator()
        return response

    monkeypatch.setattr(review_route, "run_review", fake_run_review)

    job = ReviewJob(
        job_id="rjob_stream",
        owner="pm-a",
        workspace="workspace-alpha",
        prd_name="alpha.md",
        mode="standard",
    )

    result = await review_jobs._run_existing_review_stream_as_job(
        req=ReviewRequest(
            prd_content="# Demo",
            workspace="workspace-alpha",
            prd_name="alpha.md",
            reviewer="pm-a",
            mode="standard",
        ),
        user={"reviewer": "pm-a"},
        job=job,
    )

    assert result["review_id"] == "rev_sse"
    assert [event["event"] for event in job.snapshot()["events"]] == ["uploaded", "result"]
