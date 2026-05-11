from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from api.feedback_summary import build_feedback_summary
from api.routes.feedback import ReworkAvoidanceBody, record_rework_avoidance_feedback


def test_rework_avoidance_store_summarizes_productive_samples(tmp_path: Path) -> None:
    from review.feedback_store import (
        get_rework_avoidance_summary,
        record_rework_avoidance,
    )

    db_path = tmp_path / "review" / "feedback.db"
    record_rework_avoidance(
        categories=["field_caliber", "implementation_risk"],
        note="少补了一次字段口径说明",
        reviewer="alice",
        workspace="workspace-alpha",
        prd_name="alpha.md",
        db_path=db_path,
    )
    record_rework_avoidance(
        categories=["none"],
        note="",
        reviewer="bob",
        workspace="workspace-alpha",
        prd_name="beta.md",
        db_path=db_path,
    )

    summary = get_rework_avoidance_summary(db_path=db_path, days=7)

    assert summary["total_samples"] == 2
    assert summary["productive_samples"] == 1
    assert summary["productive_rate"] == 0.5
    assert summary["category_counts"]["field_caliber"] == 1
    assert summary["category_counts"]["implementation_risk"] == 1
    assert summary["category_counts"]["none"] == 1
    assert summary["recent_notes"][0]["note"] == "少补了一次字段口径说明"


def test_rework_avoidance_route_uses_current_reviewer_and_project_db(tmp_path: Path) -> None:
    resp = record_rework_avoidance_feedback(
        ReworkAvoidanceBody(
            categories=["experience_flow"],
            note="流程边界这次提前补了",
            workspace="workspace-beta",
            prd_name="beta.md",
        ),
        user={"reviewer": "pm-a"},
        project_root=tmp_path,
    )

    assert resp["status"] == "ok"
    db_path = tmp_path / "review" / "feedback.db"
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT reviewer, workspace, prd_name, categories_json, note FROM pm_rework_avoidance"
        ).fetchone()

    assert row[0] == "pm-a"
    assert row[1] == "workspace-beta"
    assert row[2] == "beta.md"
    assert json.loads(row[3]) == ["experience_flow"]
    assert row[4] == "流程边界这次提前补了"


def test_feedback_summary_includes_rework_avoidance_and_filters_old_rows(tmp_path: Path) -> None:
    from review.feedback_store import record_rework_avoidance

    db_path = tmp_path / "review" / "feedback.db"
    old_id = record_rework_avoidance(
        categories=["field_caliber"],
        note="old",
        reviewer="alice",
        workspace="workspace-alpha",
        prd_name="old.md",
        db_path=db_path,
    )
    record_rework_avoidance(
        categories=["experience_flow"],
        note="本周流程返工少了一次",
        reviewer="alice",
        workspace="workspace-alpha",
        prd_name="new.md",
        db_path=db_path,
    )
    old_ts = (datetime.now() - timedelta(days=20)).isoformat(timespec="seconds")
    with sqlite3.connect(db_path) as conn:
        conn.execute("UPDATE pm_rework_avoidance SET timestamp = ? WHERE id = ?", (old_ts, old_id))
        conn.commit()

    summary = build_feedback_summary(tmp_path, days=7)

    rework = summary["rework_avoidance"]
    assert rework["total_samples"] == 1
    assert rework["productive_samples"] == 1
    assert rework["category_counts"] == {"experience_flow": 1}
    assert rework["recent_notes"][0]["prd_name"] == "new.md"
