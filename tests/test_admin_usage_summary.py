from __future__ import annotations

import json
from datetime import datetime

import pytest

from api.usage_summary import build_usage_summary


def _write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def test_usage_summary_aggregates_review_sessions_and_actions(tmp_path):
    _write_jsonl(
        tmp_path / "workspace-alpha" / "output" / "sessions" / "run-001.jsonl",
        [
            {
                "type": "review_started",
                "ts": "2026-05-08T09:00:00",
                "reviewer": "lvxinhang",
                "mode": "standard",
                "prd_name": "积分抵扣 PRD.md",
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
                "prd_name": "积分抵扣 PRD.md",
                "prd_content": "should not leak",
            },
            {
                "ts": "2026-05-08T09:10:00",
                "event": "report_downloaded",
                "reviewer": "lvxinhang",
                "workspace": "workspace-alpha",
                "prd_name": "积分抵扣 PRD.md",
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
    assert summary["reviewers"][0]["last_prd_name"] == "积分抵扣 PRD.md"
    assert summary["reviewers"][0]["workspaces"] == {"workspace-alpha": 1}
    assert summary["recent_runs"][0]["items_count"] == 6
    assert "prd_content" not in json.dumps(summary, ensure_ascii=False)


@pytest.mark.asyncio
async def test_admin_usage_endpoint_includes_reconnectable_jobs(monkeypatch, tmp_path):
    from api.review_jobs import ReviewJobStore
    from api.routes import admin_usage

    store = ReviewJobStore()

    async def runner(job):
        job.emit("workers_started", {"prd_content": "should not leak"})
        return {"review_id": "rev_1", "items": []}

    job = store.create_job(
        owner="lvxinhang",
        workspace="workspace-alpha",
        prd_name="alpha.md",
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
                "error": "Request timed out.",
                "duration_ms": 1200,
                "tokens_in": 9000,
                "tokens_out": 600,
                "input_tokens": 9000,
                "output_tokens": 600,
                "prd_context_packet_chars": 8000,
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
                "ts": "2026-05-08T10:00:00",
                "reviewer": "pm-a",
                "phase": 3,
                "workspace": "workspace-alpha",
                "prd_name": "alpha.md",
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
    assert "prd_content" not in json.dumps(data["active_jobs"], ensure_ascii=False)
    assert data["recent_job_events"][0]["job_id"] == "rjob_old"
    assert data["recent_job_events"][0]["dim_key"] == "quality"
    assert data["recent_job_events"][0]["duration_ms"] == 1200
    assert data["recent_job_events"][0]["prd_context_packet_chars"] == 8000
    assert "tokens_in" not in data["recent_job_events"][0]
    assert "tokens_out" not in data["recent_job_events"][0]
    assert "input_tokens" not in data["recent_job_events"][0]
    assert "output_tokens" not in data["recent_job_events"][0]
    serialized_events = json.dumps(data["recent_job_events"], ensure_ascii=False)
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
    serialized_drafts = json.dumps(data["active_drafts"], ensure_ascii=False)
    assert "should not leak" not in serialized_drafts
    assert "derived text" not in serialized_drafts
    assert "internal detail" not in serialized_drafts
