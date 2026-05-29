from __future__ import annotations

import json

import pytest


class _FakeRequest:
    async def is_disconnected(self) -> bool:
        return False


@pytest.mark.asyncio
async def test_run_review_sse_path_passes_langgraph_checkpoint_and_thread(monkeypatch, tmp_path):
    import api.routes.review as review_route
    import parallel_review as parallel_review_mod
    import review.evidence_verify as evidence_verify

    ws = tmp_path / "workspace-alpha"
    ws.mkdir()
    (ws / "wiki").mkdir()
    captured: dict = {}
    captured_evidence: dict = {}

    monkeypatch.setenv("PECKER_SIGNATURE_SECRET", "test-signature-secret-32-chars")
    monkeypatch.delenv("PECKER_REVIEW_ORCHESTRATOR", raising=False)
    monkeypatch.setattr(review_route, "get_project_root", lambda: tmp_path)
    monkeypatch.setattr(review_route, "get_workspace_dir", lambda _name: ws)
    monkeypatch.setattr(review_route, "require_workspace_access", lambda _ws, _user: None)
    monkeypatch.setattr(review_route, "check_budget", lambda *_args, **_kwargs: {"enabled": True})
    monkeypatch.setattr(review_route, "record_review_cost", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(review_route, "budget_status_snapshot", lambda *_args, **_kwargs: {})

    async def fake_parallel_review(*_args, **kwargs):
        captured.update(kwargs)
        return {
            "workers": [
                {
                    "dimension": "structure",
                    "dimension_name": "structure",
                    "items": [],
                    "usage": {"input_tokens": 0, "output_tokens": 0},
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
                    "id": "R-001",
                    "rule_id": "V-05",
                    "dimension": "structure",
                    "severity": "must",
                    "evidence_type": "A",
                    "evidence_content": "raw evidence must not leak",
                }
            ],
            "total_usage": {"input_tokens": 0, "output_tokens": 0},
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
                    "session_id": kwargs.get("thread_id"),
                    "trace_id": "abc123abc123abc123abc123abc123ab",
                    "trace_url": "https://langfuse.example/project/proj/traces/abc123abc123abc123abc123abc123ab",
                }
            },
        }

    def fake_verify_evidence(items, *_args, **_kwargs):
        verified = [dict(item) for item in items]
        verified[0]["verification_status"] = "verified"
        verified[0]["status"] = "VERIFIED"
        return verified

    def fake_summarize_verification(_verified):
        return {"total": 1, "verified": 1, "caveat": 0, "retracted": 0, "reliability": 1.0}

    def fake_record_evidence_verification_scores(**kwargs):
        captured_evidence.update(kwargs)
        return {
            "enabled": True,
            "configured": True,
            "status": "recorded",
            "scored_items": 1,
            "scores_sent": 2,
            "trace_id": kwargs["review_result"]["telemetry"]["observability"]["langfuse"]["trace_id"],
            "reliability": 1.0,
            "caveat": 0,
            "retracted": 0,
        }

    monkeypatch.setattr(parallel_review_mod, "parallel_review", fake_parallel_review)
    monkeypatch.setattr(evidence_verify, "verify_evidence", fake_verify_evidence)
    monkeypatch.setattr(evidence_verify, "summarize_verification", fake_summarize_verification)
    monkeypatch.setattr(
        review_route,
        "record_evidence_verification_scores",
        fake_record_evidence_verification_scores,
        raising=False,
    )

    response = await review_route.run_review(
        review_route.ReviewRequest(
            prd_content="# Demo",
            workspace="workspace-alpha",
            prd_name="alpha.md",
            reviewer="pm-a",
            mode="quick",
            wiki_pages={},
        ),
        _FakeRequest(),
        user={"reviewer": "pm-a", "readonly": False},
    )

    stream = ""
    async for chunk in response.body_iterator:
        stream += chunk.decode("utf-8") if isinstance(chunk, bytes) else str(chunk)

    assert captured["thread_id"].startswith("review-run:rev_")
    assert captured["checkpointer"].checkpoint_path == tmp_path / ".pecker_checkpoints" / "langgraph.pkl"
    assert "event: langgraph_checkpoint_ready" in stream
    assert captured["thread_id"] in stream

    result_payload = None
    for frame in stream.replace("\r\n", "\n").split("\n\n"):
        if not frame.startswith("event: result"):
            continue
        data_lines = [
            line.split(":", 1)[1].lstrip(" ")
            for line in frame.splitlines()
            if line.startswith("data:")
        ]
        result_payload = json.loads("\n".join(data_lines))["payload"]
        break

    assert result_payload is not None
    assert (
        result_payload["telemetry"]["observability"]["langfuse"]["session_id"]
        == captured["thread_id"]
    )
    assert result_payload["telemetry"]["observability"]["langgraph_checkpoint"] == {
        "enabled": True,
        "thread_id": captured["thread_id"],
        "status": "missing",
        "checkpoint_path": ".pecker_checkpoints/langgraph.pkl",
        "checkpoint_exists": False,
        "thread_found": False,
        "checkpoint_count": 0,
    }
    assert result_payload["telemetry"]["observability"]["langfuse_evidence"]["status"] == "recorded"
    audit_snapshot = result_payload["telemetry"]["observability"]["langfuse_audit"]
    assert audit_snapshot["json_path"].startswith("output/langfuse_audits/")
    audit_path = ws / audit_snapshot["json_path"]
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    assert audit["review_id"] == result_payload["review_id"]
    assert audit["langgraph"]["graph_trace_ready"] is True
    assert audit["langfuse"]["trace_link_ready"] is True
    assert audit["langfuse"]["prompt_versions"][0]["version"] == 8
    assert captured_evidence["review_result"]["telemetry"]["observability"]["langfuse"]["session_id"] == captured["thread_id"]
    assert captured_evidence["verified_items"][0]["verification_status"] == "verified"
    assert captured_evidence["summary"]["reliability"] == 1.0


@pytest.mark.asyncio
async def test_run_review_sse_path_uses_resolved_external_workspace_for_langfuse_audit(monkeypatch, tmp_path):
    import api.routes.review as review_route
    import parallel_review as parallel_review_mod
    import review.evidence_verify as evidence_verify

    project_root = tmp_path / "project"
    external_root = tmp_path / "external"
    project_root.mkdir()
    ws = external_root / "workspace-alpha"
    (ws / "wiki").mkdir(parents=True)
    captured: dict = {}

    monkeypatch.setenv("PECKER_SIGNATURE_SECRET", "test-signature-secret-32-chars")
    monkeypatch.delenv("PECKER_REVIEW_ORCHESTRATOR", raising=False)
    monkeypatch.setattr(review_route, "get_project_root", lambda: project_root)
    monkeypatch.setattr(review_route, "get_workspace_dir", lambda _name: ws)
    monkeypatch.setattr(review_route, "require_workspace_access", lambda _ws, _user: None)
    monkeypatch.setattr(review_route, "check_budget", lambda *_args, **_kwargs: {"enabled": True})
    monkeypatch.setattr(review_route, "record_review_cost", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(review_route, "budget_status_snapshot", lambda *_args, **_kwargs: {})

    async def fake_parallel_review(*_args, **kwargs):
        captured.update(kwargs)
        return {
            "workers": [
                {
                    "dimension": "structure",
                    "dimension_name": "structure",
                    "items": [],
                    "usage": {},
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
            "merged_items": [{"id": "R-001", "rule_id": "V-05", "dimension": "structure"}],
            "total_usage": {},
            "orchestrator": "langgraph",
            "graph_trace": ["prepare_round", "worker.structure", "finalize_review"],
            "worker_node_statuses": [{"dimension": "structure", "status": "success"}],
            "resilience": {"failed_workers": 0, "recovered_workers": 0},
            "observability": {
                "langfuse": {
                    "enabled": True,
                    "configured": True,
                    "status": "done",
                    "session_id": kwargs.get("thread_id"),
                    "trace_id": "abc123abc123abc123abc123abc123ab",
                    "trace_url": "https://langfuse.example/project/proj/traces/abc123abc123abc123abc123abc123ab",
                }
            },
        }

    monkeypatch.setattr(parallel_review_mod, "parallel_review", fake_parallel_review)
    monkeypatch.setattr(evidence_verify, "verify_evidence", lambda items, *_args, **_kwargs: items)
    monkeypatch.setattr(
        evidence_verify,
        "summarize_verification",
        lambda _verified: {"total": 1, "verified": 1, "caveat": 0, "retracted": 0, "reliability": 1.0},
    )
    monkeypatch.setattr(
        review_route,
        "record_evidence_verification_scores",
        lambda **kwargs: {
            "status": "recorded",
            "scores_sent": 1,
            "trace_id": kwargs["review_result"]["telemetry"]["observability"]["langfuse"]["trace_id"],
        },
        raising=False,
    )

    response = await review_route.run_review(
        review_route.ReviewRequest(
            prd_content="# Demo",
            workspace="workspace-alpha",
            prd_name="alpha.md",
            reviewer="pm-a",
            mode="quick",
            wiki_pages={},
        ),
        _FakeRequest(),
        user={"reviewer": "pm-a", "readonly": False},
    )

    stream = ""
    async for chunk in response.body_iterator:
        stream += chunk.decode("utf-8") if isinstance(chunk, bytes) else str(chunk)
    result_frame = next(
        frame for frame in stream.replace("\r\n", "\n").split("\n\n")
        if frame.startswith("event: result")
    )
    data = "\n".join(
        line.split(":", 1)[1].lstrip(" ")
        for line in result_frame.splitlines()
        if line.startswith("data:")
    )
    payload = json.loads(data)["payload"]
    audit_path = ws / payload["telemetry"]["observability"]["langfuse_audit"]["json_path"]

    assert captured["workspace"] == str(ws)
    assert audit_path.is_file()
    assert not (project_root / "workspace-alpha" / "output" / "langfuse_audits").exists()
