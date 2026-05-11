import json

import pytest


@pytest.mark.asyncio
async def test_audit_log_redacts_sensitive_metadata_before_writing(tmp_path):
    from api.routes.audit import AuditEvent, log_audit

    secret = "sk-testsecretvalue1234567890"
    response = await log_audit(
        AuditEvent(
            event="review_assistant_feedback",
            workspace=f"workspace?token={secret}",
            prd_name=f"demo password={secret}",
            extra={
                "answer_preview": f"report failed with bearer {secret}",
                "nested": {"signature": "signed-url-secret"},
            },
        ),
        user={"reviewer": "pm-a"},
        project_root=tmp_path,
    )

    assert response == {"status": "ok"}
    rows = [
        json.loads(line)
        for path in (tmp_path / "logs").glob("user_actions_*.jsonl")
        for line in path.read_text(encoding="utf-8").splitlines()
    ]
    assert len(rows) == 1
    serialized = json.dumps(rows[0], ensure_ascii=False)
    assert secret not in serialized
    assert "signed-url-secret" not in serialized
    assert "[REDACTED_SECRET]" in serialized


@pytest.mark.asyncio
async def test_audit_extra_cannot_override_server_audit_fields(tmp_path):
    from api.routes.audit import AuditEvent, log_audit

    await log_audit(
        AuditEvent(
            event="review_started",
            workspace="workspace-a",
            prd_name="demo.md",
            extra={
                "ts": "2000-01-01T00:00:00",
                "event": "forged_event",
                "reviewer": "forged-reviewer",
                "workspace": "forged-workspace",
                "prd_name": "forged.md",
                "action": "opened",
            },
        ),
        user={"reviewer": "pm-a"},
        project_root=tmp_path,
    )

    rows = [
        json.loads(line)
        for path in (tmp_path / "logs").glob("user_actions_*.jsonl")
        for line in path.read_text(encoding="utf-8").splitlines()
    ]
    assert rows[0]["event"] == "review_started"
    assert rows[0]["reviewer"] == "pm-a"
    assert rows[0]["workspace"] == "workspace-a"
    assert rows[0]["prd_name"] == "demo.md"
    assert rows[0]["action"] == "opened"
    assert rows[0]["ts"] != "2000-01-01T00:00:00"


@pytest.mark.asyncio
async def test_audit_failure_response_redacts_error_detail(monkeypatch, tmp_path):
    from pathlib import Path

    from api.routes.audit import AuditEvent, log_audit

    secret = "sk-auditfailuresecret1234567890"
    original_mkdir = Path.mkdir

    def fail_logs_dir(self, *args, **kwargs):
        if self.name == "logs":
            raise RuntimeError(f"write failed token={secret}")
        return original_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", fail_logs_dir)

    response = await log_audit(
        AuditEvent(event="review_assistant_copied"),
        user={"reviewer": "pm-a"},
        project_root=tmp_path,
    )

    assert response["status"] == "logged_locally"
    assert secret not in response["error"]
    assert "[REDACTED_SECRET]" in response["error"]
