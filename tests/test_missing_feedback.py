from __future__ import annotations

import json


def test_missing_feedback_writes_jsonl_and_admin_summary(tmp_path):
    from api.feedback_summary import build_feedback_summary
    from api.routes.feedback import MissingFeedbackBody, record_missing_feedback

    body = MissingFeedbackBody(
        problem="PRD 漏了支付失败后的返还口径",
        location="第 3 节",
        responsible_bird_id=2,
        workspace="workspace-alpha",
        prd_name="积分抵扣.md",
    )

    result = record_missing_feedback(
        body,
        user={"reviewer": "alice"},
        project_root=tmp_path,
    )

    assert result["status"] == "ok"
    assert result["feedback_id"].startswith("missing_")

    path = tmp_path / "logs" / "missing_feedback.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert rows[0]["reviewer"] == "alice"
    assert rows[0]["problem"] == "PRD 漏了支付失败后的返还口径"
    assert "prd_content" not in rows[0]
    assert "raw_materials" not in rows[0]

    summary = build_feedback_summary(project_root=tmp_path, days=7)
    assert summary["missing_reports"] == 1
    assert summary["missing_records"][0]["problem"] == "PRD 漏了支付失败后的返还口径"
