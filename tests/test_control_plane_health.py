from __future__ import annotations

from types import SimpleNamespace

import pytest


@pytest.mark.asyncio
async def test_health_exposes_langgraph_and_langfuse_control_plane_without_secrets(monkeypatch):
    from api.main import health

    monkeypatch.setenv("PECKER_REVIEW_ORCHESTRATOR", "langgraph")
    monkeypatch.setenv("PECKER_LANGFUSE_ENABLED", "1")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test-visible")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test-secret")
    monkeypatch.setenv("LANGFUSE_BASE_URL", "https://langfuse.example")
    monkeypatch.setenv("LANGFUSE_HOST", "https://langfuse.example")
    monkeypatch.setenv("PECKER_LANGFUSE_PROMPTS_ENABLED", "1")
    monkeypatch.setenv("PECKER_LANGFUSE_PROMPT_PREFIX", "pecker")
    monkeypatch.setenv("PECKER_LANGFUSE_PROMPT_LABEL", "production")
    monkeypatch.setenv("PECKER_LANGFUSE_PROMPT_VERSION", "8")

    payload = await health(
        SimpleNamespace(
            app=SimpleNamespace(
                state=SimpleNamespace(
                    llm_auth={"status": "ready"},
                    claude_auth="ready",
                )
            )
        )
    )

    control_plane = payload["control_plane"]
    assert control_plane["orchestrator"]["mode"] == "langgraph"
    assert control_plane["orchestrator"]["checkpointing"] == "file"
    assert control_plane["langfuse"]["enabled"] is True
    assert control_plane["langfuse"]["configured"] is True
    assert control_plane["langfuse"]["host"] == "https://langfuse.example"
    assert control_plane["langfuse"]["prompt_label"] == "production"
    assert control_plane["langfuse"]["prompt_management"] == {
        "configured": True,
        "enabled": True,
        "status": "ready",
        "sdk_available": True,
        "prefix": "pecker",
        "label": "production",
        "version": "8",
    }

    serialized = str(payload)
    assert "pk-test-visible" not in serialized
    assert "sk-test-secret" not in serialized


@pytest.mark.asyncio
async def test_admin_langfuse_smoke_runs_read_only_and_redacts(monkeypatch):
    from api.routes import admin_usage

    calls = {}

    def fake_smoke_check(*, write_score=False):
        calls["write_score"] = write_score
        return {
            "ok": True,
            "configured": True,
            "auth": {"status": "ready"},
            "score_api": {"status": "ready", "write_score": write_score},
            "debug": "sk-1234567890abcdef",
        }

    monkeypatch.setattr(admin_usage, "run_langfuse_smoke_check", fake_smoke_check, raising=False)

    payload = await admin_usage.get_admin_langfuse_smoke(_user={"reviewer": "admin"})

    assert calls["write_score"] is False
    assert payload["score_api"]["write_score"] is False
    assert "sk-1234567890abcdef" not in str(payload)


@pytest.mark.asyncio
async def test_admin_langgraph_checkpoints_returns_safe_summary(monkeypatch, tmp_path):
    from api.routes import admin_usage

    calls = {}

    def fake_summary(project_root):
        calls["project_root"] = project_root
        return {
            "status": "ready",
            "exists": True,
            "checkpoint_path": ".pecker_checkpoints/langgraph.pkl",
            "thread_count": 1,
            "threads": [{"thread_id": "review-job:rjob_001", "checkpoint_count": 5}],
            "debug": "sk-1234567890abcdef",
        }

    monkeypatch.setattr(
        admin_usage,
        "summarize_review_job_checkpoints",
        fake_summary,
        raising=False,
    )

    payload = await admin_usage.get_admin_langgraph_checkpoints(
        _user={"reviewer": "admin"},
        project_root=tmp_path,
    )

    assert calls["project_root"] == tmp_path
    assert payload["status"] == "ready"
    assert payload["thread_count"] == 1
    assert payload["threads"][0]["thread_id"] == "review-job:rjob_001"
    assert "sk-1234567890abcdef" not in str(payload)
