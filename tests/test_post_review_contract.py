"""Shared post-review contract tests.

目标: Web / CLI / Feishu 后续都能复用同一组后处理契约,避免各自解释
review items、决策统计和报告字段。
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _review_result(items):
    return {
        "review_id": "rev_test",
        "created_at": 1777344000,
        "reviewer": "alice",
        "workspace": "workspace-demo",
        "prd_name": "demo-prd",
        "mode": "standard",
        "items": items,
        "workers": [],
        "usage": {},
        "signature": "sig",
    }


def test_normalize_review_items_keeps_python_fields_and_adds_web_aliases():
    from review.post_review_contract import normalize_review_items

    item = {
        "id": "R-001",
        "issue": "缺少验收标准",
        "evidence_content": "PRD 第 3 节",
        "confidence_score": 0.85,
        "severity": "must",
    }

    out = normalize_review_items([item])[0]

    assert out["issue"] == "缺少验收标准"
    assert out["problem"] == "缺少验收标准"
    assert out["evidence_content"] == "PRD 第 3 节"
    assert out["evidence"] == "PRD 第 3 节"
    assert out["confidence_score"] == 0.85
    assert out["confidence"] == 0.85
    assert out["implement_convention_version"] == "v1"
    assert "problem" not in item, "源 item 不应被原地改写"


def test_summarize_decisions_counts_pending_and_actions():
    from review.post_review_contract import summarize_decisions

    items = [{"id": "R-001"}, {"id": "R-002"}, {"id": "R-003"}]
    decisions = {
        "R-001": {"action": "accept"},
        "R-002": {"action": "reject", "reason_category": "false_positive"},
    }

    summary = summarize_decisions(items, decisions)

    assert summary == {
        "total": 3,
        "accepted": 1,
        "rejected": 1,
        "edited": 0,
        "pending": 1,
    }


def test_build_confirm_report_markdown_uses_backend_aliases_and_convention():
    from review.post_review_contract import build_confirm_report_markdown

    result = _review_result([
        {
            "id": "R-001",
            "dimension": "structure",
            "issue": "缺少验收标准",
            "suggestion": "补充可执行验收标准",
            "severity": "must",
            "location": "3. 验收",
            "evidence_content": "未看到验收标准",
        },
        {
            "id": "R-002",
            "dimension": "quality",
            "issue": "边界条件不清",
            "suggestion": "补充失败态",
            "severity": "should",
        },
    ])
    decisions = {
        "R-001": {"action": "edit", "edited_problem": "验收标准需量化"},
        "R-002": {
            "action": "reject",
            "reason_category": "known_tradeoff",
            "reason": "业务已接受该取舍",
        },
    }

    report = build_confirm_report_markdown(result, decisions)

    assert "# PRD 评审报告 - demo-prd" in report
    assert "下游实现约定" in report
    assert "implement_convention_version" in report
    assert "验收标准需量化" in report
    assert "原始: 缺少验收标准" in report
    assert "已知取舍" in report
    assert "业务已接受该取舍" in report
