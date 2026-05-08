from __future__ import annotations

import json
from datetime import datetime

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
