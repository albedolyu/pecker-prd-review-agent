"""R16: review_fixer 单测 - 覆盖 evidence_type 推断 + verify 调用

review_fixer.py 是 P1-6 识别的零覆盖模块之一。核心功能是在 worker 输出后
为 items 做工程化修复（补 evidence_type / 调 verify_evidence / 失败降权）。
"""
import pytest
from unittest.mock import patch

from review_fixer import infer_evidence_type, fix_review_items


# ==========================================================
# infer_evidence_type
# ==========================================================

def test_infer_a_from_wiki_syntax():
    """[[wiki-link]] 语法应判为 A 类"""
    assert infer_evidence_type("参考 [[概念-排序规则]] 第 2 节") == "A"
    assert infer_evidence_type("wiki: [[entity-foo]]") == "A"


def test_infer_b_from_rule_id():
    """包含 RC-xxx / V-xx / BMAD V-xx 判为 B 类"""
    assert infer_evidence_type("见评审规则 RC-009") == "B"
    assert infer_evidence_type("违反 V-07 字段定义") == "B"
    assert infer_evidence_type("BMAD V-10 要求") == "B"


def test_infer_c_from_industry_keywords():
    """提到竞品/行业/惯例 判为 C 类"""
    assert infer_evidence_type("竞品企查查也是这样做的") == "C"
    assert infer_evidence_type("行业惯例") == "C"
    assert infer_evidence_type("同类产品惯例") == "C"


def test_infer_empty_when_ambiguous():
    """没法归类返回空串"""
    assert infer_evidence_type("这是一个普通的句子") == ""
    assert infer_evidence_type("") == ""
    assert infer_evidence_type(None) == ""


def test_infer_priority_a_before_b():
    """A 类 [[...]] 优先级高于 B 类 RC-xx"""
    ev = "[[wiki-page]] 对应 RC-009"
    assert infer_evidence_type(ev) == "A"


# ==========================================================
# fix_review_items
# ==========================================================

def test_fix_returns_empty_stats_for_empty_input():
    items, stats = fix_review_items([], "workspace-test")
    assert items == []
    assert stats["total"] == 0
    assert stats["verified"] == 0


def test_fix_infers_missing_evidence_type():
    """evidence_type 为空时自动推断"""
    items = [
        {
            "id": "R-001",
            "evidence_type": "",
            "evidence_content": "参考规则 RC-009",
        }
    ]
    # mock verify_evidence 返回空 details,避免真的调 wiki
    with patch("cuckoo_scorer.verify_evidence", return_value=([], [], [])):
        fixed, stats = fix_review_items(items, "workspace-test")
    assert fixed[0]["evidence_type"] == "B"
    assert stats["inferred_type"] == 1


def test_fix_marks_verified_on_success():
    items = [{
        "id": "R-001",
        "evidence_type": "B",
        "evidence_content": "RC-009",
    }]
    fake_details = [{"item_id": "R-001", "verified": True, "reason": ""}]
    with patch("cuckoo_scorer.verify_evidence", return_value=([], [], fake_details)):
        fixed, stats = fix_review_items(items, "workspace-test")
    assert fixed[0]["verification_status"] == "verified"
    assert stats["verified"] == 1
    assert stats["failed"] == 0


def test_fix_marks_failed_and_downgrades_confidence_for_ab():
    """A/B 类依据验证失败时 confidence 降权 50%"""
    items = [{
        "id": "R-001",
        "evidence_type": "A",
        "evidence_content": "[[不存在的wiki页]]",
        "confidence_score": 0.9,
    }]
    fake_details = [{"item_id": "R-001", "verified": False, "reason": "wiki page not found"}]
    with patch("cuckoo_scorer.verify_evidence", return_value=([], [], fake_details)):
        fixed, stats = fix_review_items(items, "workspace-test")
    assert fixed[0]["verification_status"] == "failed"
    assert stats["failed"] == 1
    assert stats["downgraded"] == 1
    # 0.9 * 0.5 = 0.45
    assert fixed[0]["confidence_score"] == 0.45


def test_fix_does_not_downgrade_c_class():
    """C 类失败不降权(因为 C 本就标记为 待确定)"""
    items = [{
        "id": "R-001",
        "evidence_type": "C",
        "evidence_content": "竞品企查查",
        "confidence_score": 0.5,
    }]
    fake_details = [{"item_id": "R-001", "verified": False, "reason": "c-class never auto-verifies"}]
    with patch("cuckoo_scorer.verify_evidence", return_value=([], [], fake_details)):
        fixed, stats = fix_review_items(items, "workspace-test")
    assert stats["downgraded"] == 0
    # confidence_score 不变
    assert fixed[0]["confidence_score"] == 0.5


def test_fix_marks_unchecked_when_no_evidence():
    """既无 evidence_type 又无 evidence_content → unchecked"""
    items = [{
        "id": "R-001",
        "evidence_type": "",
        "evidence_content": "",
    }]
    with patch("cuckoo_scorer.verify_evidence", return_value=([], [], [])):
        fixed, stats = fix_review_items(items, "workspace-test")
    assert fixed[0]["verification_status"] == "unchecked"
    assert stats["unchecked"] == 1


def test_fix_handles_verify_exception():
    """verify_evidence 抛异常时全部标 unchecked 不崩"""
    items = [{"id": "R-001", "evidence_type": "B", "evidence_content": "RC-009"}]
    with patch("cuckoo_scorer.verify_evidence", side_effect=RuntimeError("wiki broken")):
        fixed, stats = fix_review_items(items, "workspace-test")
    assert fixed[0]["verification_status"] == "unchecked"
    assert stats["unchecked"] == 1
