from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest

from api.usage_summary import build_usage_summary


def _write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def test_usage_summary_aggregates_review_sessions_and_actions(tmp_path):
    fake_key = "sk-01234567890abcdefABCDEFghij"
    _write_jsonl(
        tmp_path / "workspace-alpha" / "output" / "sessions" / "run-001.jsonl",
        [
            {
                "type": "review_started",
                "ts": "2026-05-08T09:00:00",
                "reviewer": "lvxinhang",
                "mode": "standard",
                "prd_name": f"积分抵扣 {fake_key} PRD.md",
            },
            {
                "type": "review_completed",
                "ts": "2026-05-08T09:08:00",
                "items_count": 6,
                "total_cost_usd": 0.42,
                "duration_ms": 480000,
            },
        ],
    )
    _write_jsonl(
        tmp_path / "logs" / "user_actions_20260508.jsonl",
        [
            {
                "ts": "2026-05-08T09:00:00",
                "event": "review_started",
                "reviewer": "lvxinhang",
                "workspace": "workspace-alpha",
                "prd_name": f"积分抵扣 {fake_key} PRD.md",
                "prd_content": "should not leak",
            },
            {
                "ts": "2026-05-08T09:10:00",
                "event": "report_downloaded",
                "reviewer": "lvxinhang",
                "workspace": "workspace-alpha",
                "prd_name": f"积分抵扣 {fake_key} PRD.md",
            },
        ],
    )

    summary = build_usage_summary(tmp_path, days=30, now=datetime(2026, 5, 8, 12, 0, 0))

    assert summary["summary"]["total_reviews"] == 1
    assert summary["summary"]["active_reviewers"] == 1
    assert summary["summary"]["completed"] == 1
    assert summary["summary"]["failed"] == 0
    assert summary["summary"]["total_cost_usd"] == 0.42
    assert summary["reviewers"][0]["reviewer"] == "lvxinhang"
    assert summary["reviewers"][0]["reviews"] == 1
    assert summary["reviewers"][0]["last_prd_name"] == "积分抵扣 [REDACTED_SECRET] PRD.md"
    assert summary["reviewers"][0]["workspaces"] == {"workspace-alpha": 1}
    assert summary["recent_runs"][0]["items_count"] == 6
    serialized = json.dumps(summary, ensure_ascii=False)
    assert fake_key not in serialized
    assert "[REDACTED_SECRET]" in serialized
    assert "prd_content" not in serialized


def test_usage_summary_redacts_stability_grouping_keys(tmp_path):
    fake_key = "sk-01234567890abcdefABCDEFghij"
    _write_jsonl(
        tmp_path / "workspace-alpha" / "output" / "sessions" / "run-001.jsonl",
        [
            {
                "type": "review_started",
                "ts": "2026-05-08T09:00:00",
                "reviewer": f"lvxinhang {fake_key}",
                "mode": f"standard api_key={fake_key}",
                "prd_name": "alpha.md",
            },
            {
                "type": "review_completed",
                "ts": "2026-05-08T09:08:00",
                "items_count": 6,
                "duration_ms": 480000,
            },
        ],
    )

    summary = build_usage_summary(tmp_path, days=30, now=datetime(2026, 5, 8, 12, 0, 0))

    serialized = json.dumps(summary["stability"], ensure_ascii=False)
    assert fake_key not in serialized
    assert "[REDACTED_SECRET]" in serialized


def test_usage_summary_redacts_budget_snapshot_errors(monkeypatch, tmp_path):
    import api.usage_summary as usage_summary

    fake_key = "sk-01234567890abcdefABCDEFghij"

    def fail_budget_snapshot(project_root):
        raise RuntimeError(f"budget read failed api_key={fake_key}")

    monkeypatch.setattr(usage_summary, "budget_status_snapshot", fail_budget_snapshot)

    summary = build_usage_summary(tmp_path, days=30, now=datetime(2026, 5, 8, 12, 0, 0))

    assert fake_key not in summary["budget"]["error"]
    assert "api_key=[REDACTED_SECRET]" in summary["budget"]["error"]


@pytest.mark.asyncio
async def test_admin_usage_endpoint_includes_reconnectable_jobs(monkeypatch, tmp_path):
    from api.review_jobs import ReviewJobStore
    from api.routes import admin_usage

    store = ReviewJobStore()
    fake_key = "sk-01234567890abcdefABCDEFghij"

    async def runner(job):
        job.emit("workers_started", {"prd_content": "should not leak"})
        return {"review_id": "rev_1", "items": []}

    job = store.create_job(
        owner="lvxinhang",
        workspace=f"workspace-alpha-{fake_key}",
        prd_name=f"alpha-{fake_key}.md",
        mode="standard",
        runner=runner,
    )
    await job.wait()
    monkeypatch.setattr(admin_usage, "review_job_store", store)
    _write_jsonl(
        tmp_path / "logs" / "review_jobs.jsonl",
        [
            {
                "job_id": "rjob_old",
                "owner": "pm-a",
                "workspace": "workspace-alpha",
                "prd_name": "alpha.md",
                "event": "worker_done",
                "dim_key": "quality",
                "items_count": 1,
                "error": f"Request timed out with api_key={fake_key}",
                "message": f"upstream leaked Bearer {fake_key}",
                "duration_ms": 1200,
                "tokens_in": 9000,
                "tokens_out": 600,
                "input_tokens": 9000,
                "output_tokens": 600,
                "prd_context_packet_chars": 8000,
                "cost_usd": 0.037,
                "context_manager_calls": 3,
                "context_manager_tokens_saved": 2048,
                "context_manager_nudges": 1,
                "context_manager_failures": 1,
                "ts": 1,
                "prd_content": "should not leak",
                "payload": {"items": [{"problem": "derived text should not leak"}]},
            }
        ],
    )
    (tmp_path / ".pecker_drafts").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".pecker_drafts" / "pm-a_draft.json").write_text(
        json.dumps(
            {
                "ts": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
                "reviewer": "pm-a",
                "phase": 3,
                "workspace": "workspace-alpha",
                "prd_name": f"alpha {fake_key}.md",
                "mode": "standard",
                "prd_content": "should not leak",
                "review_result": {
                    "review_id": "rev_draft",
                    "items": [{"problem": "derived text should not leak"}],
                    "telemetry": {
                        "total_duration_ms": 182000,
                        "orchestrator": "langgraph",
                        "resilience": {
                            "failed_workers": 1,
                            "recovered_workers": 1,
                            "context_packet_workers": 3,
                            "max_context_packet_chars": 8192,
                        },
                        "context_manager": {
                            "total_calls": 4,
                            "total_tokens_saved": 1536,
                            "paths": {
                                "microcompact": {
                                    "calls": 2,
                                    "tokens_saved": 1024,
                                    "mutations": 2,
                                },
                                "check_convergence": {
                                    "calls": 2,
                                    "nudges": 1,
                                },
                            },
                        },
                        "workers": {
                            "quality": {
                                "duration_ms": 800,
                                "error": "internal detail should not leak",
                            }
                        },
                    },
                },
                "item_decisions": {
                    "I-1": {"action": "accept"},
                    "I-2": {"action": "reject"},
                },
                "confirmed_report_markdown": "should not leak",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    data = await admin_usage.get_admin_usage(
        days=7,
        _user={"reviewer": "lvxinhang"},
        project_root=tmp_path,
    )

    assert data["active_jobs"][0]["job_id"] == job.job_id
    assert data["active_jobs"][0]["owner"] == "lvxinhang"
    assert data["active_jobs"][0]["last_event"] == "result"
    serialized_jobs = json.dumps(data["active_jobs"], ensure_ascii=False)
    assert fake_key not in serialized_jobs
    assert "[REDACTED_SECRET]" in serialized_jobs
    assert "prd_content" not in serialized_jobs
    assert data["recent_job_events"][0]["job_id"] == "rjob_old"
    assert data["recent_job_events"][0]["dim_key"] == "quality"
    assert data["recent_job_events"][0]["duration_ms"] == 1200
    assert data["recent_job_events"][0]["input_tokens"] == 9000
    assert data["recent_job_events"][0]["output_tokens"] == 600
    assert data["recent_job_events"][0]["prd_context_packet_chars"] == 8000
    assert data["recent_job_events"][0]["cost_usd"] == 0.037
    assert data["recent_job_events"][0]["context_manager_calls"] == 3
    assert data["recent_job_events"][0]["context_manager_tokens_saved"] == 2048
    assert data["recent_job_events"][0]["context_manager_nudges"] == 1
    assert data["recent_job_events"][0]["context_manager_failures"] == 1
    assert "tokens_in" not in data["recent_job_events"][0]
    assert "tokens_out" not in data["recent_job_events"][0]
    serialized_events = json.dumps(data["recent_job_events"], ensure_ascii=False)
    assert fake_key not in serialized_events
    assert "[REDACTED_SECRET]" in serialized_events
    assert "should not leak" not in serialized_events
    assert "derived text" not in serialized_events
    assert data["active_drafts"][0]["reviewer"] == "pm-a"
    assert data["active_drafts"][0]["phase"] == 3
    assert data["active_drafts"][0]["phase_label"] == "逐条确认"
    assert data["active_drafts"][0]["items_count"] == 1
    assert data["active_drafts"][0]["decisions_count"] == 2
    assert data["active_drafts"][0]["duration_ms"] == 182000
    assert data["active_drafts"][0]["orchestrator"] == "langgraph"
    assert data["active_drafts"][0]["failed_workers"] == 1
    assert data["active_drafts"][0]["recovered_workers"] == 1
    assert data["active_drafts"][0]["context_packet_workers"] == 3
    assert data["active_drafts"][0]["max_context_packet_chars"] == 8192
    assert data["active_drafts"][0]["context_manager_calls"] == 4
    assert data["active_drafts"][0]["context_manager_tokens_saved"] == 1536
    assert data["active_drafts"][0]["context_manager_nudges"] == 1
    serialized_drafts = json.dumps(data["active_drafts"], ensure_ascii=False)
    assert fake_key not in serialized_drafts
    assert "[REDACTED_SECRET]" in serialized_drafts
    assert "should not leak" not in serialized_drafts
    assert "derived text" not in serialized_drafts
    assert "internal detail" not in serialized_drafts


def test_admin_usage_active_drafts_excludes_expired_drafts(tmp_path):
    from api.routes.admin_usage import _load_active_drafts

    draft_dir = tmp_path / ".pecker_drafts"
    draft_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now()
    (draft_dir / "old_draft.json").write_text(
        json.dumps(
            {
                "ts": (now - timedelta(days=4)).strftime("%Y-%m-%dT%H:%M:%S"),
                "reviewer": "pm-old",
                "phase": 3,
                "workspace": "workspace-alpha",
                "prd_name": "old.md",
                "review_result": {"items": []},
                "item_decisions": {},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (draft_dir / "fresh_draft.json").write_text(
        json.dumps(
            {
                "ts": now.strftime("%Y-%m-%dT%H:%M:%S"),
                "reviewer": "pm-fresh",
                "phase": 3,
                "workspace": "workspace-alpha",
                "prd_name": "fresh.md",
                "review_result": {"items": []},
                "item_decisions": {},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    rows = _load_active_drafts(tmp_path)

    assert [row["reviewer"] for row in rows] == ["pm-fresh"]


def test_admin_usage_active_drafts_tolerates_invalid_phase(tmp_path):
    from api.routes.admin_usage import _load_active_drafts

    draft_dir = tmp_path / ".pecker_drafts"
    draft_dir.mkdir(parents=True, exist_ok=True)
    (draft_dir / "bad_phase_draft.json").write_text(
        json.dumps(
            {
                "ts": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
                "reviewer": "pm-bad",
                "phase": "not-a-number",
                "workspace": "workspace-alpha",
                "prd_name": "bad phase.md",
                "review_result": {"items": []},
                "item_decisions": {},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    rows = _load_active_drafts(tmp_path)

    assert rows[0]["reviewer"] == "pm-bad"
    assert rows[0]["phase"] == 0
    assert rows[0]["phase_label"] == "上传 PRD"


def test_admin_usage_active_drafts_redacts_orchestrator(tmp_path):
    from api.routes.admin_usage import _load_active_drafts

    fake_key = "sk-01234567890abcdefABCDEFghij"
    draft_dir = tmp_path / ".pecker_drafts"
    draft_dir.mkdir(parents=True, exist_ok=True)
    (draft_dir / "secret_orchestrator_draft.json").write_text(
        json.dumps(
            {
                "ts": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
                "reviewer": "pm-a",
                "phase": 3,
                "workspace": "workspace-alpha",
                "prd_name": "alpha.md",
                "review_result": {
                    "items": [],
                    "telemetry": {"orchestrator": f"langgraph Bearer {fake_key}"},
                },
                "item_decisions": {},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    rows = _load_active_drafts(tmp_path)

    assert fake_key not in rows[0]["orchestrator"]
    assert "Bearer [REDACTED_SECRET]" in rows[0]["orchestrator"]
