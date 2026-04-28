import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_annotate_review_items_adds_convention_without_mutating_source():
    from review.implement_convention import (
        IMPLEMENT_CONVENTION_DOC,
        IMPLEMENT_CONVENTION_VERSION,
        annotate_review_items,
    )

    original = [{"id": "R-001", "issue": "缺少验收标准"}]
    annotated = annotate_review_items(original)

    assert original == [{"id": "R-001", "issue": "缺少验收标准"}]
    assert annotated[0]["implement_convention_version"] == IMPLEMENT_CONVENTION_VERSION
    assert annotated[0]["implement_convention_required"] is True
    assert annotated[0]["implement_convention_doc"] == IMPLEMENT_CONVENTION_DOC


def test_build_actionable_report_includes_downstream_convention_notice():
    from report_builder import build_actionable_report

    items = [{
        "id": "R-001",
        "rule_id": "V-02",
        "location": "1. 背景",
        "issue": "缺少验收标准",
        "suggestion": "补充可执行验收标准",
        "severity": "must",
        "evidence_type": "A",
        "evidence_content": "PRD 第 1 节",
    }]

    report = build_actionable_report(items, "## 1. 背景\n当前描述较粗。", "demo", "reviewer")

    assert "下游实现约定" in report
    assert "implement_convention_version" in report
    assert "v1" in report
