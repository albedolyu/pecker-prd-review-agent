from __future__ import annotations

import json
from datetime import datetime

from api.feedback_summary import build_feedback_summary


def _write_ground_truth(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_feedback_summary_reads_pm_decisions_without_prd_body(tmp_path):
    _write_ground_truth(
        tmp_path / "eval" / "ground_truth" / "alpha_lvxinhang_1778205600.json",
        {
            "workspace": "workspace-alpha",
            "reviewer": "lvxinhang",
            "prd_name": "积分抵扣 PRD.md",
            "timestamp": 1778205600,
            "items": [
                {
                    "id": "R-001",
                    "rule_id": "V-05",
                    "dimension": "quality",
                    "location": "第 3 节",
                    "severity": "must",
                    "action": "reject",
                    "reason_category": "false_positive",
                    "correctness_reason": "false_positive",
                    "business_decision": "risk_accepted",
                    "reason_note": "这里其实已经说明",
                    "problem": "验收标准看起来不完整",
                    "suggestion": "补充边界条件",
                    "prd_content": "should not leak",
                    "is_true_positive": False,
                },
                {
                    "id": "R-002",
                    "rule_id": "V-07",
                    "dimension": "risk",
                    "location": "第 5 节",
                    "severity": "should",
                    "action": "accept",
                    "reason_category": "",
                    "reason_note": "",
                    "problem": "异常兜底需要补充",
                    "is_true_positive": True,
                },
            ],
        },
    )

    summary = build_feedback_summary(
        tmp_path,
        days=7,
        now=datetime.fromtimestamp(1778292000),
    )

    assert summary["summary"] == {
        "total_items": 2,
        "accepted": 1,
        "rejected": 1,
        "edited": 0,
        "accept_rate": 0.5,
        "reject_rate": 0.5,
        "feedback_reviewers": 1,
    }
    assert summary["by_reviewer"][0]["reviewer"] == "lvxinhang"
    assert summary["by_reviewer"][0]["rejected"] == 1
    assert summary["records"][0]["action"] == "accept"
    assert summary["records"][1]["reason_category"] == "false_positive"
    assert summary["records"][1]["correctness_reason"] == "false_positive"
    assert summary["records"][1]["business_decision"] == "risk_accepted"
    assert summary["correctness_reasons"] == {"false_positive": 1}
    assert summary["business_decisions"] == {"risk_accepted": 1}
    assert summary["records"][1]["problem"] == "验收标准看起来不完整"
    assert "prd_content" not in json.dumps(summary, ensure_ascii=False)


def test_feedback_summary_filters_by_reviewer_workspace_and_action(tmp_path):
    _write_ground_truth(
        tmp_path / "eval" / "ground_truth" / "alpha_alice_1778205600.json",
        {
            "workspace": "workspace-alpha",
            "reviewer": "alice",
            "timestamp": 1778205600,
            "items": [{"id": "A-1", "action": "reject", "reason_category": "model_noise"}],
        },
    )
    _write_ground_truth(
        tmp_path / "eval" / "ground_truth" / "beta_bob_1778205700.json",
        {
            "workspace": "workspace-beta",
            "reviewer": "bob",
            "timestamp": 1778205700,
            "items": [{"id": "B-1", "action": "accept"}],
        },
    )

    summary = build_feedback_summary(
        tmp_path,
        days=7,
        now=datetime.fromtimestamp(1778292000),
        reviewer="alice",
        workspace="workspace-alpha",
        action="reject",
    )

    assert len(summary["records"]) == 1
    assert summary["records"][0]["reviewer"] == "alice"
    assert summary["records"][0]["workspace"] == "workspace-alpha"
    assert summary["summary"]["rejected"] == 1


def test_feedback_summary_reads_in_progress_draft_decisions(tmp_path):
    _write_ground_truth(
        tmp_path / ".pecker_drafts" / "alice_draft.json",
        {
            "ts": "2026-05-08T10:00:00",
            "reviewer": "alice",
            "phase": 3,
            "workspace": "workspace-alpha",
            "prd_name": "alpha.md",
            "prd_content": "should not leak",
            "review_result": {
                "items": [
                    {
                        "id": "R-1",
                        "dimension": "quality",
                        "problem": "链路说明不清",
                        "suggestion": "补充边界",
                    },
                    {
                        "id": "R-2",
                        "dimension": "risk",
                        "problem": "异常兜底不足",
                    },
                ]
            },
            "item_decisions": {
                "R-1": {"action": "accept"},
                "R-2": {
                    "action": "reject",
                    "reason_category": "impl_detail",
                    "business_decision": "not_this_iteration",
                    "reason": "这条太偏实现",
                },
            },
        },
    )

    summary = build_feedback_summary(
        tmp_path,
        days=7,
        now=datetime.fromtimestamp(1778292000),
    )

    assert summary["summary"]["total_items"] == 2
    assert summary["draft_items"] == 2
    assert summary["records"][0]["source"] == "draft"
    assert summary["records"][0]["reason_category"] == "impl_detail"
    assert summary["records"][0]["business_decision"] == "not_this_iteration"
    assert summary["business_decisions"] == {"not_this_iteration": 1}
    assert "prd_content" not in json.dumps(summary, ensure_ascii=False)


def test_feedback_summary_redacts_public_record_text(tmp_path):
    fake_key = "sk-01234567890abcdefABCDEFghij"
    _write_ground_truth(
        tmp_path / "eval" / "ground_truth" / "alpha_alice_1778205600.json",
        {
            "workspace": f"workspace api_key={fake_key}",
            "reviewer": "alice",
            "prd_name": f"demo {fake_key}.md",
            "timestamp": 1778205600,
            "items": [
                {
                    "id": "R-001",
                    "action": "reject",
                    "reason_category": f"unknown api_key={fake_key}",
                    "reason_note": f"operator note {fake_key}",
                    "problem": f"problem includes {fake_key}",
                    "suggestion": f"suggestion includes Bearer {fake_key}",
                }
            ],
        },
    )

    summary = build_feedback_summary(
        tmp_path,
        days=7,
        now=datetime.fromtimestamp(1778292000),
    )

    serialized = json.dumps(summary, ensure_ascii=False)
    assert fake_key not in serialized
    assert "[REDACTED_SECRET]" in serialized


def test_feedback_summary_redacts_missing_record_owner_fields(tmp_path):
    fake_key = "sk-01234567890abcdefABCDEFghij"
    missing_path = tmp_path / "logs" / "missing_feedback.jsonl"
    missing_path.parent.mkdir(parents=True, exist_ok=True)
    missing_path.write_text(
        json.dumps(
            {
                "timestamp": "2026-05-08T10:00:00",
                "feedback_id": "fb-1",
                "reviewer": "alice",
                "workspace": "workspace-alpha",
                "prd_name": "demo.md",
                "problem": "missing feedback",
                "location": "section 3",
                "responsible_bird_id": f"bird api_key={fake_key}",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    summary = build_feedback_summary(
        tmp_path,
        days=7,
        now=datetime.fromisoformat("2026-05-08T12:00:00"),
    )

    serialized = json.dumps(summary["missing_records"], ensure_ascii=False)
    assert fake_key not in serialized
    assert "api_key=[REDACTED_SECRET]" in serialized
