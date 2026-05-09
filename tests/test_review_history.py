from __future__ import annotations

import json
from datetime import datetime

import pytest

from api.usage_summary import build_personal_review_history


def _write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def test_personal_review_history_filters_to_current_reviewer_and_hides_prd_body(tmp_path):
    _write_jsonl(
        tmp_path / "workspace-alpha" / "output" / "sessions" / "run-001.jsonl",
        [
            {
                "type": "review_started",
                "ts": "2026-05-08T09:00:00",
                "reviewer": "pm-a",
                "mode": "deep",
                "prd_name": "积分抵扣 PRD.md",
                "prd_content": "should not leak",
            },
            {
                "type": "review_completed",
                "ts": "2026-05-08T09:07:00",
                "items_count": 8,
                "duration_ms": 420000,
            },
        ],
    )
    _write_jsonl(
        tmp_path / "workspace-beta" / "output" / "sessions" / "run-002.jsonl",
        [
            {
                "type": "review_started",
                "ts": "2026-05-08T10:00:00",
                "reviewer": "pm-b",
                "mode": "deep",
                "prd_name": "同事材料.md",
            },
            {"type": "review_completed", "ts": "2026-05-08T10:07:00"},
        ],
    )
    _write_jsonl(
        tmp_path / "logs" / "user_actions_20260508.jsonl",
        [
            {
                "ts": "2026-05-08T09:00:00",
                "event": "review_started",
                "reviewer": "pm-a",
                "workspace": "workspace-alpha",
                "prd_name": "积分抵扣 PRD.md",
                "prd_content": "should not leak",
            },
            {
                "ts": "2026-05-08T09:09:00",
                "event": "report_downloaded",
                "reviewer": "pm-a",
                "workspace": "workspace-alpha",
                "prd_name": "积分抵扣 PRD.md",
            },
            {
                "ts": "2026-05-08T10:00:00",
                "event": "review_started",
                "reviewer": "pm-b",
                "workspace": "workspace-beta",
                "prd_name": "同事材料.md",
            },
        ],
    )

    history = build_personal_review_history(
        tmp_path,
        reviewer="pm-a",
        days=30,
        now=datetime(2026, 5, 8, 12, 0, 0),
    )

    assert history["reviewer"] == "pm-a"
    assert [row["prd_name"] for row in history["runs"]] == ["积分抵扣 PRD.md"]
    assert [row["event"] for row in history["recent_actions"]] == [
        "report_downloaded",
        "review_started",
    ]
    encoded = json.dumps(history, ensure_ascii=False)
    assert "同事材料" not in encoded
    assert "should not leak" not in encoded


@pytest.mark.asyncio
async def test_review_history_endpoint_uses_logged_in_reviewer(monkeypatch, tmp_path):
    from api.routes import review_history

    _write_jsonl(
        tmp_path / "logs" / "user_actions_20260508.jsonl",
        [
            {
                "ts": "2026-05-08T09:00:00",
                "event": "review_started",
                "reviewer": "pm-a",
                "workspace": "workspace-alpha",
                "prd_name": "积分抵扣 PRD.md",
            },
            {
                "ts": "2026-05-08T10:00:00",
                "event": "review_started",
                "reviewer": "pm-b",
                "workspace": "workspace-beta",
                "prd_name": "别人的 PRD.md",
            },
        ],
    )

    data = await review_history.get_my_review_history(
        days=7,
        limit=20,
        user={"reviewer": "pm-a"},
        project_root=tmp_path,
    )

    assert data["reviewer"] == "pm-a"
    assert data["recent_actions"][0]["prd_name"] == "积分抵扣 PRD.md"
    assert "别人的 PRD" not in json.dumps(data, ensure_ascii=False)
