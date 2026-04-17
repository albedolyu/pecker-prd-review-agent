"""
review_fixer.infer_evidence_type 覆盖测试 (Round 10)

fix_review_items 已经有 test_review_fixer.py 覆盖,但 infer_evidence_type 作为
纯函数入口只有间接测试。补齐显式测试,也顺便验证:
- 多种 evidence_content 格式都能正确推断
- A/B/C 优先级的正确性 (A > B > C)
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestInferEvidenceType:
    def test_empty_content_returns_empty(self):
        from review_fixer import infer_evidence_type
        assert infer_evidence_type("") == ""

    def test_none_content_returns_empty(self):
        from review_fixer import infer_evidence_type
        assert infer_evidence_type(None) == ""

    def test_wiki_link_returns_a(self):
        from review_fixer import infer_evidence_type
        assert infer_evidence_type("见 [[PRD模板.md]] 第 3 节") == "A"

    def test_wiki_link_with_alias_returns_a(self):
        from review_fixer import infer_evidence_type
        assert infer_evidence_type("参考 [[foo#section|bar]]") == "A"

    def test_rc_rule_returns_b(self):
        from review_fixer import infer_evidence_type
        assert infer_evidence_type("参考规则 RC-042") == "B"

    def test_v_rule_returns_b(self):
        from review_fixer import infer_evidence_type
        assert infer_evidence_type("遵循 V-001 规范") == "B"

    def test_bmad_rule_returns_b(self):
        from review_fixer import infer_evidence_type
        assert infer_evidence_type("BMAD V-007") == "B"
        assert infer_evidence_type("BMAD-V-007") == "B"

    def test_competitor_returns_c(self):
        from review_fixer import infer_evidence_type
        assert infer_evidence_type("参考竞品 foo 的做法") == "C"

    def test_industry_returns_c(self):
        from review_fixer import infer_evidence_type
        assert infer_evidence_type("行业通行做法") == "C"

    def test_convention_returns_c(self):
        from review_fixer import infer_evidence_type
        assert infer_evidence_type("按惯例应该") == "C"

    def test_a_priority_over_b(self):
        """同时出现 wiki link 和 rule ref → 应返回 A。"""
        from review_fixer import infer_evidence_type
        assert infer_evidence_type("见 [[foo.md]] 并参考 RC-001") == "A"

    def test_b_priority_over_c(self):
        """同时出现 rule ref 和竞品 → 应返回 B。"""
        from review_fixer import infer_evidence_type
        assert infer_evidence_type("RC-001 同竞品做法") == "B"

    def test_unknown_format_returns_empty(self):
        from review_fixer import infer_evidence_type
        assert infer_evidence_type("完全没有引用的纯描述") == ""

    def test_partial_wiki_bracket_not_match(self):
        """只有左括号 [[ 没有右 ]] → 不算 A。"""
        from review_fixer import infer_evidence_type
        assert infer_evidence_type("参考 [[未完成") == ""


class TestFixReviewItemsStatsShape:
    """验证 fix_review_items 返回的 stats 结构稳定性。"""

    def test_empty_items_zero_stats(self, tmp_path):
        from review_fixer import fix_review_items
        items, stats = fix_review_items([], str(tmp_path))
        assert items == []
        assert stats == {
            "total": 0, "inferred_type": 0, "verified": 0,
            "failed": 0, "unchecked": 0, "downgraded": 0,
        }

    def test_none_items_handled(self, tmp_path):
        from review_fixer import fix_review_items
        items, stats = fix_review_items(None, str(tmp_path))
        assert items is None
        assert stats["total"] == 0

    def test_inferred_type_counted(self, tmp_path, monkeypatch):
        """无 evidence_type 但 content 里有 wiki link → 应该自动推断为 A。"""
        from review_fixer import fix_review_items
        # mock verify_evidence 返回空 details,避免真 IO
        monkeypatch.setattr(
            "cuckoo_scorer.verify_evidence",
            lambda items, ws: (0, 0, []),
        )
        items = [{"id": "R-001", "evidence_type": "",
                  "evidence_content": "见 [[foo.md]]"}]
        fixed, stats = fix_review_items(items, str(tmp_path))
        assert stats["inferred_type"] == 1
        assert fixed[0]["evidence_type"] == "A"

    def test_verify_exception_marks_all_unchecked(self, tmp_path, monkeypatch):
        from review_fixer import fix_review_items
        monkeypatch.setattr(
            "cuckoo_scorer.verify_evidence",
            lambda items, ws: (_ for _ in ()).throw(RuntimeError("verify crashed")),
        )
        items = [{"id": f"R-{i:03d}", "evidence_content": "x"} for i in range(3)]
        fixed, stats = fix_review_items(items, str(tmp_path))
        assert stats["unchecked"] == 3
        for it in fixed:
            assert it["verification_status"] == "unchecked"
