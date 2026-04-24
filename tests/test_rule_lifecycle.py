"""rule_lifecycle 周度 slim 报告单测 (2026-04-24 Week 2).

覆盖 _classify_rule 的 7 种状态分支, _dominant_reject_reason 提取,
slim_workspace 排序, build_report 结构.
"""
from __future__ import annotations

import json
import os
import sys

import pytest


_SCRIPTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "scripts"))
sys.path.insert(0, _SCRIPTS_DIR)


# ============================================================
# _dominant_reject_reason
# ============================================================

class TestDominantRejectReason:
    def test_single_dominant(self):
        from rule_lifecycle import _dominant_reject_reason
        stats = {"reject_by_reason": {"false_positive": 5, "wiki_missing": 1}}
        out = _dominant_reject_reason(stats)
        assert out["reason"] == "false_positive"
        assert out["count"] == 5
        assert out["ratio"] > 0.8

    def test_empty_bucket(self):
        from rule_lifecycle import _dominant_reject_reason
        assert _dominant_reject_reason({}) is None
        assert _dominant_reject_reason({"reject_by_reason": {}}) is None

    def test_tie_picks_any(self):
        """并列时只要返回一个合法值即可."""
        from rule_lifecycle import _dominant_reject_reason
        out = _dominant_reject_reason({"reject_by_reason": {"a": 2, "b": 2}})
        assert out["reason"] in ("a", "b")
        assert out["count"] == 2


# ============================================================
# _classify_rule — 7 种状态
# ============================================================

class TestClassifyRule:
    def test_insufficient_data(self):
        from rule_lifecycle import _classify_rule
        cl = _classify_rule("R-1", {"stats": {"total": 2, "confirmed": 2}})
        assert cl["status"] == "insufficient_data"

    def test_healthy_high_precision(self):
        from rule_lifecycle import _classify_rule
        cl = _classify_rule("R-1", {"stats": {"total": 10, "confirmed": 8, "rejected": 2}})
        assert cl["status"] == "healthy"

    def test_deprecate_candidate_low_impact_high_volume(self):
        from rule_lifecycle import _classify_rule
        cl = _classify_rule("R-1", {
            "stats": {"total": 20, "confirmed": 10, "rejected": 10},   # precision 0.5, borderline
            "impact_score": 0.1,
        })
        # precision 0.5 不进 healthy (需 >=0.7), impact 0.1 + total 20 → deprecate
        assert cl["status"] == "deprecate_candidate"

    def test_rule_problem_false_positive_dominant(self):
        from rule_lifecycle import _classify_rule
        cl = _classify_rule("R-1", {
            "stats": {"total": 10, "confirmed": 3, "rejected": 7,
                      "reject_by_reason": {"false_positive": 6, "wiki_missing": 1}},
            "impact_score": 0.5,
        })
        assert cl["status"] == "rule_problem_demote"
        assert cl["dominant"]["reason"] == "false_positive"

    def test_rule_rewrite_on_rule_too_strict_dominant(self):
        from rule_lifecycle import _classify_rule
        cl = _classify_rule("R-1", {
            "stats": {"total": 10, "confirmed": 3, "rejected": 7,
                      "reject_by_reason": {"rule_too_strict": 5, "model_noise": 2}},
            "impact_score": 0.5,
        })
        assert cl["status"] == "rule_rewrite"

    def test_wiki_gap_preserves_rule(self):
        """主导 wiki_missing → 不降规则, 改补知识库."""
        from rule_lifecycle import _classify_rule
        cl = _classify_rule("R-1", {
            "stats": {"total": 10, "confirmed": 3, "rejected": 7,
                      "reject_by_reason": {"wiki_missing": 5, "false_positive": 2}},
            "impact_score": 0.5,
        })
        assert cl["status"] == "wiki_gap"
        assert "知识库" in cl["reason"]

    def test_scope_narrow_on_impl_detail(self):
        from rule_lifecycle import _classify_rule
        cl = _classify_rule("R-1", {
            "stats": {"total": 10, "confirmed": 3, "rejected": 7,
                      "reject_by_reason": {"impl_detail": 6}},
            "impact_score": 0.5,
        })
        assert cl["status"] == "scope_narrow"

    def test_prompt_iteration_on_model_noise(self):
        from rule_lifecycle import _classify_rule
        cl = _classify_rule("R-1", {
            "stats": {"total": 10, "confirmed": 3, "rejected": 7,
                      "reject_by_reason": {"model_noise": 7}},
            "impact_score": 0.5,
        })
        assert cl["status"] == "prompt_iteration"

    def test_noisy_without_t2_data(self):
        """高驳回但没 T2 reason 字段 → 人工 review 建议."""
        from rule_lifecycle import _classify_rule
        cl = _classify_rule("R-1", {
            "stats": {"total": 10, "confirmed": 3, "rejected": 7},   # 无 reject_by_reason
            "impact_score": 0.5,
        })
        assert cl["status"] == "noisy_needs_investigation"

    def test_monitor_on_mid_precision(self):
        """precision 0.5-0.7 → keep 观察."""
        from rule_lifecycle import _classify_rule
        cl = _classify_rule("R-1", {
            "stats": {"total": 10, "confirmed": 6, "rejected": 4},
        })
        assert cl["status"] == "monitor"


# ============================================================
# slim_workspace — 读文件 + 排序
# ============================================================

class TestSlimWorkspace:
    def test_empty_workspace(self, tmp_path):
        from rule_lifecycle import slim_workspace
        assert slim_workspace(str(tmp_path)) == []

    def test_sorted_by_priority(self, tmp_path):
        """problem 优先于 healthy."""
        from rule_lifecycle import slim_workspace
        output = tmp_path / "output"
        output.mkdir()
        data = {
            "__meta__": {"schema_version": 1},
            "R-healthy": {
                "stats": {"total": 10, "confirmed": 9, "rejected": 1},
                "impact_score": 0.9,
            },
            "R-problem": {
                "stats": {"total": 10, "confirmed": 2, "rejected": 8,
                          "reject_by_reason": {"false_positive": 7}},
                # impact_score > 0.3 避免先触发 deprecate_candidate 分支
                "impact_score": 0.4,
            },
        }
        (output / "rule_performance_history.json").write_text(
            json.dumps(data), encoding="utf-8",
        )
        rules = slim_workspace(str(tmp_path))
        # problem 应该在前
        assert rules[0][0] == "R-problem"
        assert rules[0][1]["status"] == "rule_problem_demote"
        assert rules[1][0] == "R-healthy"

    def test_skip_meta_key(self, tmp_path):
        """__meta__ key 不当成规则."""
        from rule_lifecycle import slim_workspace
        output = tmp_path / "output"
        output.mkdir()
        (output / "rule_performance_history.json").write_text(
            json.dumps({"__meta__": {"x": 1}, "R-001": {"stats": {"total": 5, "confirmed": 4}}}),
            encoding="utf-8",
        )
        rules = slim_workspace(str(tmp_path))
        rule_ids = [r[0] for r in rules]
        assert "__meta__" not in rule_ids
        assert "R-001" in rule_ids


# ============================================================
# build_report 结构
# ============================================================

class TestBuildReport:
    def test_markdown_has_sections_and_emoji(self):
        from rule_lifecycle import build_report
        all_results = {
            "workspace-x": [
                ("R-001", {
                    "status": "rule_problem_demote", "total": 10, "precision": 0.3,
                    "reject_rate": 0.7, "impact_score": 0.4,
                    "action": "建议降级", "reason": "false_positive 主导",
                    "dominant": {"reason": "false_positive", "count": 7, "ratio": 0.7},
                }),
                ("R-002", {
                    "status": "healthy", "total": 15, "precision": 0.8,
                    "reject_rate": 0.2, "impact_score": 0.8,
                    "action": "keep active", "reason": "precision >= 0.7",
                    "dominant": None,
                }),
            ],
        }
        md = build_report(all_results, "2026-W17")
        assert "# 规则生命周期" in md
        assert "2026-W17" in md
        assert "workspace-x" in md
        assert "R-001" in md
        assert "R-002" in md
        assert "🔻" in md   # rule_problem_demote 的 emoji
        assert "✓" in md    # healthy 的 emoji
        # 建议动作汇总 section
        assert "建议动作汇总" in md
        # 待动作规则详情 (problem 类)
        assert "待动作规则详情" in md

    def test_empty_result_still_has_header(self):
        from rule_lifecycle import build_report
        md = build_report({}, "2026-W17")
        assert "# 规则生命周期" in md
        # 0 条规则也不 crash
