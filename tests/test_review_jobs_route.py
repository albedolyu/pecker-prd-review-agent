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
async def test_start_review_job_uses_resolved_external_workspace(monkeypatch, tmp_path):
    from api.routes import review_jobs
    from api.routes.review import ReviewRequest

    project_root = tmp_path / "project"
    project_root.mkdir()
    workspace = tmp_path / "external" / "workspace-alpha"
    workspace.mkdir(parents=True)
    captured: dict[str, str] = {}

    async def fake_runner(*, req, user, ws_abs_path, emitter, project_root):
        captured["ws_abs_path"] = ws_abs_path
        return {
            "review_id": "rev_job_external",
            "reviewer": user["reviewer"],
            "workspace": req.workspace,
            "items": [],
        }

    monkeypatch.setattr(review_jobs, "_run_review_job_pipeline", fake_runner)
    monkeypatch.setattr(review_jobs, "get_workspace_dir", lambda _name: workspace)
    monkeypatch.setattr(review_jobs, "require_workspace_access", lambda _ws, _user: None)
    monkeypatch.setattr(review_jobs, "check_budget", lambda *_args, **_kwargs: {"ok": True})

    started = await review_jobs.start_review_job(
        req=ReviewRequest(
            prd_content="# Demo",
            workspace="workspace-alpha",
            prd_name="external-alpha.md",
            reviewer="pm-external",
            mode="quick",
        ),
        user={"reviewer": "pm-external", "readonly": False},
        project_root=project_root,
    )

    await review_jobs.review_job_store.get_job_ref(
        started["job_id"],
        owner="pm-external",
    ).wait()

    assert captured["ws_abs_path"] == str(workspace)
    assert not (project_root / "workspace-alpha").exists()


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
        from context_manager import microcompact

        microcompact(
            [
                {"role": "user", "content": "工具执行结果：" + "A" * 3000},
                {"role": "assistant", "content": "ok"},
                {"role": "user", "content": "next"},
                {"role": "assistant", "content": "ok2"},
            ]
        )
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
            "observability": {
                "langfuse": {
                    "enabled": True,
                    "configured": True,
                    "status": "done",
                    "backend": "langfuse",
                }
            },
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
    assert result["telemetry"]["observability"]["langfuse"]["status"] == "done"
    assert result["telemetry"]["observability"]["langgraph_checkpoint"] == {
        "enabled": True,
        "thread_id": "review-job:rjob_default",
        "status": "missing",
        "checkpoint_path": ".pecker_checkpoints/langgraph.pkl",
        "checkpoint_exists": False,
        "thread_found": False,
        "checkpoint_count": 0,
    }
    assert result["telemetry"]["context_manager"]["paths"]["microcompact"]["calls"] == 1
    assert result["telemetry"]["context_manager"]["paths"]["microcompact"]["tokens_saved"] > 0
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
async def test_review_job_completion_persists_langfuse_run_audit(monkeypatch, tmp_path):
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
                "dimension_name": "结构",
                "items": [{"id": "R-1"}],
                "usage": {"input_tokens": 1, "output_tokens": 1},
                "telemetry": {
                    "prompt": {
                            "name": "pecker.worker.structure.system",
                            "source": "langfuse",
                            "status": "ready",
                            "label": "production",
                            "version": 8,
                            "hash": "hash-structure",
                        }
                    },
                },
        )
        return {
            "workers": [
                {
                    "dimension": "structure",
                    "dimension_name": "结构",
                    "items": [{"id": "R-1"}],
                    "usage": {"input_tokens": 1, "output_tokens": 1},
                    "telemetry": {
                        "prompt": {
                                "name": "pecker.worker.structure.system",
                                "source": "langfuse",
                                "status": "ready",
                                "label": "production",
                                "version": 8,
                                "hash": "hash-structure",
                            }
                        },
                    }
            ],
            "merged_items": [
                {
                    "id": "R-1",
                    "dimension": "结构",
                    "severity": "must",
                    "location": "目标",
                    "problem": "raw finding must not leak",
                }
            ],
            "total_usage": {"input_tokens": 1, "output_tokens": 1},
            "orchestrator": "langgraph",
            "graph_trace": [
                "prepare_round",
                "worker.structure",
                "finalize_round",
                "finalize_review",
            ],
            "worker_node_statuses": [
                {"dimension": "structure", "status": "success", "error_type": ""},
            ],
            "resilience": {"failed_workers": 0, "recovered_workers": 1},
            "observability": {
                "langfuse": {
                    "enabled": True,
                    "configured": True,
                    "status": "done",
                    "backend": "langfuse",
                    "session_id": "review-job:rjob_langfuse_audit",
                    "trace_id": "abc123abc123abc123abc123abc123ab",
                    "trace_url": "https://langfuse.example/project/proj/traces/abc123abc123abc123abc123abc123ab",
                },
                "langfuse_evidence": {
                    "status": "recorded",
                    "scored_items": 1,
                    "scores_sent": 2,
                    "trace_id": "abc123abc123abc123abc123abc123ab",
                    "trace_linked": True,
                    "reliability": 1.0,
                },
            },
        }

    monkeypatch.setattr(review_jobs, "_parallel_review_for_job", fake_parallel_review)
    monkeypatch.setattr(review_jobs, "record_review_cost", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        review_jobs,
        "build_langgraph_checkpoint_observability",
        lambda _project_root, *, thread_id: {
            "enabled": True,
            "thread_id": thread_id,
            "status": "ready",
            "checkpoint_path": ".pecker_checkpoints/langgraph.pkl",
            "checkpoint_exists": True,
            "thread_found": True,
            "checkpoint_count": 5,
        },
    )

    job = ReviewJob(
        job_id="rjob_langfuse_audit",
        owner="pm-a",
        workspace="workspace-alpha",
        prd_name="alpha.md",
        mode="quick",
    )
    emitter = RecordingReviewProgressEmitter(job)
    workspace = tmp_path / "workspace-alpha"

    result = await review_jobs._run_review_job_pipeline(
        req=ReviewRequest(
            prd_content="# Demo",
            workspace="workspace-alpha",
            prd_name="alpha.md",
            reviewer="pm-a",
            mode="quick",
        ),
        user={"reviewer": "pm-a"},
        ws_abs_path=str(workspace),
        emitter=emitter,
        project_root=tmp_path,
    )

    audit_snapshot = result["telemetry"]["observability"]["langfuse_audit"]
    json_path = workspace / audit_snapshot["json_path"]
    md_path = workspace / audit_snapshot["markdown_path"]
    audit = json.loads(json_path.read_text(encoding="utf-8"))
    markdown = md_path.read_text(encoding="utf-8")

    assert audit_snapshot["ok"] is True
    assert audit_snapshot["graph_trace_ready"] is True
    assert audit_snapshot["graph_trace_order_ready"] is True
    assert audit_snapshot["worker_nodes_ready"] is True
    assert audit["review_id"] == result["review_id"]
    assert audit["langfuse"]["trace_link_ready"] is True
    assert audit["langgraph"]["graph_trace_ready"] is True
    assert audit["langgraph"]["graph_trace_order_ready"] is True
    assert audit["langgraph"]["worker_nodes_ready"] is True
    assert audit["langgraph"]["recovered_workers"] == 1
    assert audit["langgraph_checkpoint"]["thread_found"] is True
    assert audit["langgraph_checkpoint"]["checkpoint_count"] == 5
    assert audit["langfuse"]["prompt_versions"][0]["version"] == 8
    assert "raw finding must not leak" not in json.dumps(audit, ensure_ascii=False)
    assert "raw finding must not leak" not in markdown


@pytest.mark.asyncio
async def test_review_job_lightweight_path_records_langfuse_evidence_scores(monkeypatch, tmp_path):
    import json

    from api.review_jobs import RecordingReviewProgressEmitter, ReviewJob
    from api.routes import review_jobs
    from api.routes.review import ReviewRequest

    monkeypatch.setenv("PECKER_SIGNATURE_SECRET", "unit-test-signature-secret-32-chars")
    monkeypatch.setenv("PECKER_REVIEW_JOB_PIPELINE", "lightweight")
    captured: dict = {}

    async def fake_parallel_review(*_args, **kwargs):
        kwargs["on_worker_done"](
            "structure",
            {
                "dimension": "structure",
                "dimension_name": "structure",
                "items": [{"id": "R-1"}],
                "usage": {"input_tokens": 1, "output_tokens": 1},
                "telemetry": {
                    "prompt": {
                        "name": "pecker.worker.structure.system",
                        "source": "langfuse",
                        "status": "ready",
                        "label": "production",
                        "version": 8,
                        "hash": "hash-structure",
                    }
                },
            },
        )
        return {
            "workers": [
                {
                    "dimension": "structure",
                    "dimension_name": "structure",
                    "items": [{"id": "R-1"}],
                    "usage": {"input_tokens": 1, "output_tokens": 1},
                    "telemetry": {
                        "prompt": {
                            "name": "pecker.worker.structure.system",
                            "source": "langfuse",
                            "status": "ready",
                            "label": "production",
                            "version": 8,
                            "hash": "hash-structure",
                        }
                    },
                }
            ],
            "merged_items": [
                {
                    "id": "R-1",
                    "dimension": "structure",
                    "severity": "must",
                    "location": "target",
                    "problem": "raw finding must not leak",
                }
            ],
            "total_usage": {"input_tokens": 1, "output_tokens": 1},
            "orchestrator": "langgraph",
            "graph_trace": [
                "prepare_round",
                "worker.structure",
                "finalize_round",
                "finalize_review",
            ],
            "worker_node_statuses": [
                {"dimension": "structure", "status": "success", "error_type": ""},
            ],
            "resilience": {"failed_workers": 0, "recovered_workers": 0},
            "observability": {
                "langfuse": {
                    "enabled": True,
                    "configured": True,
                    "status": "done",
                    "backend": "langfuse",
                    "session_id": "review-job:rjob_evidence_score",
                    "trace_id": "abc123abc123abc123abc123abc123ab",
                    "trace_url": "https://langfuse.example/project/proj/traces/abc123abc123abc123abc123abc123ab",
                },
            },
        }

    def fake_verify_evidence(items, *_args, **_kwargs):
        verified = [dict(item) for item in items]
        verified[0]["verification_status"] = "verified"
        return verified

    def fake_summarize_verification(_verified):
        return {"total": 1, "verified": 1, "caveat": 0, "retracted": 0, "reliability": 1.0}

    async def fake_record_evidence_snapshot(review_result, verified_items, summary):
        captured["review_result"] = review_result
        captured["verified_items"] = verified_items
        captured["summary"] = summary
        return {
            "enabled": True,
            "configured": True,
            "status": "recorded",
            "scored_items": len(verified_items),
            "scores_sent": len(verified_items) + 1,
            "trace_id": review_result["telemetry"]["observability"]["langfuse"]["trace_id"],
            "trace_linked": True,
            "reliability": summary["reliability"],
        }

    monkeypatch.setattr(review_jobs, "_parallel_review_for_job", fake_parallel_review)
    monkeypatch.setattr(review_jobs, "record_review_cost", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(review_jobs, "verify_evidence", fake_verify_evidence, raising=False)
    monkeypatch.setattr(
        review_jobs,
        "summarize_verification",
        fake_summarize_verification,
        raising=False,
    )
    monkeypatch.setattr(
        review_jobs,
        "_record_langfuse_evidence_snapshot",
        fake_record_evidence_snapshot,
        raising=False,
    )
    monkeypatch.setattr(
        review_jobs,
        "build_langgraph_checkpoint_observability",
        lambda _project_root, *, thread_id: {
            "enabled": True,
            "thread_id": thread_id,
            "status": "ready",
            "checkpoint_path": ".pecker_checkpoints/langgraph.pkl",
            "checkpoint_exists": True,
            "thread_found": True,
            "checkpoint_count": 5,
        },
    )

    job = ReviewJob(
        job_id="rjob_evidence_score",
        owner="pm-a",
        workspace="workspace-alpha",
        prd_name="alpha.md",
        mode="quick",
    )
    workspace = tmp_path / "workspace-alpha"

    result = await review_jobs._run_review_job_pipeline(
        req=ReviewRequest(
            prd_content="# Demo",
            workspace="workspace-alpha",
            prd_name="alpha.md",
            reviewer="pm-a",
            mode="quick",
        ),
        user={"reviewer": "pm-a"},
        ws_abs_path=str(workspace),
        emitter=RecordingReviewProgressEmitter(job),
        project_root=tmp_path,
    )

    observability = result["telemetry"]["observability"]
    audit_snapshot = observability["langfuse_audit"]
    audit = json.loads((workspace / audit_snapshot["json_path"]).read_text(encoding="utf-8"))

    assert result["items"][0]["verification_status"] == "verified"
    assert observability["langfuse_evidence"]["status"] == "recorded"
    assert captured["review_result"]["telemetry"]["observability"]["langfuse"]["session_id"] == (
        "review-job:rjob_evidence_score"
    )
    assert captured["verified_items"][0]["verification_status"] == "verified"
    assert audit_snapshot["ok"] is True
    assert audit["langfuse"]["evidence_scores"]["scores_sent"] == 2
    assert "langfuse_evidence" not in audit["missing"]


@pytest.mark.asyncio
async def test_review_job_order_mismatch_audit_is_read_by_admin_summary(monkeypatch, tmp_path):
    import json

    from api.review_jobs import RecordingReviewProgressEmitter, ReviewJob
    from api.routes import review_jobs
    from api.routes.admin_usage import _load_recent_langfuse_run_audits
    from api.routes.review import ReviewRequest

    monkeypatch.setenv("PECKER_SIGNATURE_SECRET", "unit-test-signature-secret-32-chars")
    monkeypatch.setenv("PECKER_REVIEW_JOB_PIPELINE", "lightweight")

    async def fake_parallel_review(*_args, **kwargs):
        kwargs["on_worker_done"](
            "structure",
            {
                "dimension": "structure",
                "dimension_name": "structure",
                "items": [{"id": "R-1"}],
                "usage": {"input_tokens": 1, "output_tokens": 1},
                "telemetry": {
                    "prompt": {
                        "name": "pecker.worker.structure.system",
                        "source": "langfuse",
                        "status": "ready",
                        "label": "production",
                        "version": 8,
                        "hash": "hash-structure",
                    }
                },
            },
        )
        return {
            "workers": [
                {
                    "dimension": "structure",
                    "dimension_name": "structure",
                    "items": [{"id": "R-1"}],
                    "usage": {"input_tokens": 1, "output_tokens": 1},
                    "telemetry": {
                        "prompt": {
                            "name": "pecker.worker.structure.system",
                            "source": "langfuse",
                            "status": "ready",
                            "label": "production",
                            "version": 8,
                            "hash": "hash-structure",
                        }
                    },
                }
            ],
            "merged_items": [
                {
                    "id": "R-1",
                    "dimension": "structure",
                    "severity": "must",
                    "location": "target",
                    "problem": "raw finding must not leak",
                }
            ],
            "total_usage": {"input_tokens": 1, "output_tokens": 1},
            "orchestrator": "langgraph",
            "graph_trace": [
                "prepare_round",
                "finalize_round",
                "finalize_review",
                "worker.structure",
            ],
            "worker_node_statuses": [
                {"dimension": "structure", "status": "success", "error_type": ""},
            ],
            "resilience": {"failed_workers": 0, "recovered_workers": 0},
            "observability": {
                "langfuse": {
                    "enabled": True,
                    "configured": True,
                    "status": "done",
                    "backend": "langfuse",
                    "session_id": "review-job:rjob_order_mismatch",
                    "trace_id": "abc123abc123abc123abc123abc123ab",
                    "trace_url": "https://langfuse.example/project/proj/traces/abc123abc123abc123abc123abc123ab",
                },
                "langfuse_evidence": {
                    "status": "recorded",
                    "scored_items": 1,
                    "scores_sent": 2,
                    "trace_id": "abc123abc123abc123abc123abc123ab",
                    "trace_linked": True,
                    "reliability": 1.0,
                },
            },
        }

    monkeypatch.setattr(review_jobs, "_parallel_review_for_job", fake_parallel_review)
    monkeypatch.setattr(review_jobs, "record_review_cost", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        review_jobs,
        "build_langgraph_checkpoint_observability",
        lambda _project_root, *, thread_id: {
            "enabled": True,
            "thread_id": thread_id,
            "status": "ready",
            "checkpoint_path": ".pecker_checkpoints/langgraph.pkl",
            "checkpoint_exists": True,
            "thread_found": True,
            "checkpoint_count": 5,
        },
    )

    job = ReviewJob(
        job_id="rjob_order_mismatch",
        owner="pm-a",
        workspace="workspace-alpha",
        prd_name="alpha.md",
        mode="quick",
    )
    workspace = tmp_path / "workspace-alpha"

    result = await review_jobs._run_review_job_pipeline(
        req=ReviewRequest(
            prd_content="# Demo",
            workspace="workspace-alpha",
            prd_name="alpha.md",
            reviewer="pm-a",
            mode="quick",
        ),
        user={"reviewer": "pm-a"},
        ws_abs_path=str(workspace),
        emitter=RecordingReviewProgressEmitter(job),
        project_root=tmp_path,
    )

    audit_snapshot = result["telemetry"]["observability"]["langfuse_audit"]
    audit = json.loads((workspace / audit_snapshot["json_path"]).read_text(encoding="utf-8"))
    summary = _load_recent_langfuse_run_audits(tmp_path, limit=5)
    row = next(row for row in summary["audits"] if row["workspace"] == "workspace-alpha")

    assert audit_snapshot["ok"] is False
    assert audit_snapshot["status"] == "missing"
    assert audit_snapshot["graph_trace_ready"] is False
    assert audit_snapshot["graph_trace_order_ready"] is False
    assert "langgraph.graph_trace.order" in audit_snapshot["missing"]
    assert audit["langgraph"]["graph_trace_order_ready"] is False
    assert "langgraph.graph_trace.order" in audit["missing"]
    assert summary["graph_order_failures"] == 1
    assert row["graph_order_failure"] is True
    assert row["missing_summary"] == "langgraph.graph_trace, langgraph.graph_trace.order"
    assert "raw finding must not leak" not in json.dumps(audit, ensure_ascii=False)


@pytest.mark.asyncio
async def test_get_langfuse_run_audit_returns_json_and_markdown(monkeypatch, tmp_path):
    import json

    from api.routes import review_jobs

    workspace = tmp_path / "workspace-alpha"
    audit_dir = workspace / "output" / "langfuse_audits"
    audit_dir.mkdir(parents=True)
    (audit_dir / "rev_alpha.json").write_text(
        json.dumps(
            {
                "ok": True,
                "review_id": "rev_alpha",
                "langfuse": {"trace_link_ready": True},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (audit_dir / "rev_alpha.md").write_text("# Langfuse audit\n", encoding="utf-8")
    access_check = {}

    def fake_require_workspace_access(ws_dir, user):
        access_check["ws_dir"] = ws_dir
        access_check["user"] = user

    monkeypatch.setattr(review_jobs, "get_workspace_dir", lambda _name: workspace)
    monkeypatch.setattr(review_jobs, "require_workspace_access", fake_require_workspace_access)

    payload = await review_jobs.get_langfuse_run_audit(
        workspace="workspace-alpha",
        review_id="rev_alpha",
        artifact_format="json",
        user={"reviewer": "pm-a"},
    )
    markdown = await review_jobs.get_langfuse_run_audit(
        workspace="workspace-alpha",
        review_id="rev_alpha",
        artifact_format="markdown",
        user={"reviewer": "pm-a"},
    )

    assert payload["review_id"] == "rev_alpha"
    assert payload["langfuse"]["trace_link_ready"] is True
    assert markdown.media_type == "text/markdown; charset=utf-8"
    assert markdown.body.decode("utf-8") == "# Langfuse audit\n"
    assert access_check["ws_dir"] == workspace
    assert access_check["user"]["reviewer"] == "pm-a"


@pytest.mark.asyncio
async def test_get_langfuse_run_audit_returns_compact_snapshot(monkeypatch, tmp_path):
    import json

    from api.routes import review_jobs

    workspace = tmp_path / "workspace-alpha"
    audit_dir = workspace / "output" / "langfuse_audits"
    audit_dir.mkdir(parents=True)
    (audit_dir / "rev_alpha.json").write_text(
        json.dumps(
            {
                "ok": True,
                "status": "ready",
                "missing_count": 0,
                "review_id": "rev_alpha",
                "langfuse": {"trace_link_ready": True},
                "langgraph": {
                    "graph_trace_ready": True,
                    "graph_trace_order_ready": True,
                    "worker_nodes_ready": True,
                },
                "langgraph_checkpoint": {
                    "status": "ready",
                    "thread_found": True,
                    "checkpoint_exists": True,
                },
                "missing": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(review_jobs, "get_workspace_dir", lambda _name: workspace)
    monkeypatch.setattr(review_jobs, "require_workspace_access", lambda _ws, _user: None)

    snapshot = await review_jobs.get_langfuse_run_audit(
        workspace="workspace-alpha",
        review_id="rev_alpha",
        artifact_format="snapshot",
        user={"reviewer": "pm-a"},
    )

    assert snapshot["ok"] is True
    assert snapshot["status"] == "ready"
    assert snapshot["json_path"] == "output/langfuse_audits/rev_alpha.json"
    assert snapshot["markdown_path"] == "output/langfuse_audits/rev_alpha.md"
    assert snapshot["trace_link_ready"] is True
    assert snapshot["graph_trace_order_ready"] is True
    assert snapshot["checkpoint_ready"] is True


@pytest.mark.asyncio
async def test_get_langfuse_run_audit_does_not_read_outside_audit_dir(monkeypatch, tmp_path):
    from fastapi import HTTPException

    from api.routes import review_jobs

    workspace = tmp_path / "workspace-alpha"
    (workspace / "output" / "langfuse_audits").mkdir(parents=True)
    (workspace / "secret.json").write_text('{"ok": false}', encoding="utf-8")

    monkeypatch.setattr(review_jobs, "get_workspace_dir", lambda _name: workspace)
    monkeypatch.setattr(review_jobs, "require_workspace_access", lambda _ws, _user: None)

    with pytest.raises(HTTPException) as exc:
        await review_jobs.get_langfuse_run_audit(
            workspace="workspace-alpha",
            review_id="../secret",
            artifact_format="json",
            user={"reviewer": "pm-a"},
        )

    assert exc.value.status_code == 404


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
        from context_manager import microcompact

        assert await request.is_disconnected() is False
        microcompact(
            [
                {"role": "user", "content": "工具执行结果：" + "B" * 3000},
                {"role": "assistant", "content": "ok"},
                {"role": "user", "content": "next"},
                {"role": "assistant", "content": "ok2"},
            ]
        )
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
    assert result["telemetry"]["context_manager"]["paths"]["microcompact"]["calls"] == 1
    assert result["telemetry"]["context_manager"]["paths"]["microcompact"]["tokens_saved"] > 0
    assert draft["phase"] == 3
    assert draft["review_result"]["review_id"] == "rev_stream"
    assert draft["prd_content"] == "# Stream PRD"
    audit_snapshot = result["telemetry"]["observability"]["langfuse_audit"]
    assert audit_snapshot["json_path"].startswith("output/langfuse_audits/")
    assert (tmp_path / "workspace-alpha" / audit_snapshot["json_path"]).is_file()


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


def test_completed_job_draft_preserves_existing_decisions_for_same_prd(tmp_path):
    import json

    from api.routes import review_jobs
    from api.routes.drafts import DraftPayload, write_draft_file
    from api.routes.review import ReviewRequest

    write_draft_file(
        tmp_path,
        "pm-a",
        DraftPayload(
            phase=3,
            prd_name="alpha.md",
            prd_content="# Alpha",
            workspace="workspace-alpha",
            item_decisions={"I-1": {"action": "accept"}},
            review_result={
                "review_id": "rev_preliminary",
                "items": [{"id": "I-1"}],
                "goshawk_summary": {"status": "pending", "mode": "async_patch"},
            },
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
        review_result={
            "review_id": "rev_final",
            "items": [{"id": "I-1"}, {"id": "G-1"}],
            "goshawk_summary": {"verdict": "REVIEWED"},
        },
    )

    draft = json.loads(
        (tmp_path / ".pecker_drafts" / "pm-a_draft.json").read_text(encoding="utf-8")
    )

    assert draft["phase"] == 3
    assert draft["review_result"]["review_id"] == "rev_final"
    assert draft["item_decisions"] == {"I-1": {"action": "accept"}}


def test_completed_job_draft_does_not_overwrite_confirmed_report(tmp_path):
    import json

    from api.routes import review_jobs
    from api.routes.drafts import DraftPayload, write_draft_file
    from api.routes.review import ReviewRequest

    write_draft_file(
        tmp_path,
        "pm-a",
        DraftPayload(
            phase=4,
            prd_name="alpha.md",
            prd_content="# Alpha",
            workspace="workspace-alpha",
            item_decisions={"I-1": {"action": "accept"}},
            confirmed_report_markdown="# Final report",
            review_result={"review_id": "rev_confirmed", "items": [{"id": "I-1"}]},
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
        review_result={"review_id": "rev_late_patch", "items": [{"id": "G-1"}]},
    )

    draft = json.loads(
        (tmp_path / ".pecker_drafts" / "pm-a_draft.json").read_text(encoding="utf-8")
    )

    assert draft["phase"] == 4
    assert draft["review_result"]["review_id"] == "rev_confirmed"
    assert draft["confirmed_report_markdown"] == "# Final report"


def test_completed_job_draft_does_not_overwrite_different_mode_draft(tmp_path):
    import json

    from api.routes import review_jobs
    from api.routes.drafts import DraftPayload, write_draft_file
    from api.routes.review import ReviewRequest

    write_draft_file(
        tmp_path,
        "pm-a",
        DraftPayload(
            phase=3,
            prd_name="alpha.md",
            prd_content="# Alpha quick",
            mode="quick",
            workspace="workspace-alpha",
            review_result={"review_id": "rev_quick", "items": [{"id": "Q-1"}]},
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
        review_result={"review_id": "rev_standard", "items": [{"id": "S-1"}]},
    )

    draft = json.loads(
        (tmp_path / ".pecker_drafts" / "pm-a_draft.json").read_text(encoding="utf-8")
    )

    assert draft["mode"] == "quick"
    assert draft["review_result"]["review_id"] == "rev_quick"


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
