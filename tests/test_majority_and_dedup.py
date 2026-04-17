"""
majority_vote + merge_and_deduplicate 覆盖测试 (Round 9)

这两个函数是 parallel_review 的后处理关键:
- merge_and_deduplicate: 4 worker 的 items 合并去重,错一次放过重复项或误杀真阳
- majority_vote: 多轮投票,太宽松放过不稳定 item,太严格筛掉真阳

测试覆盖:
- 空输入
- 完全不同的 items
- 高度相似的 items (>80% 相似 → 去重,保留严重度高的)
- majority_vote: min_votes 门槛 / 文本长度优先 / 严重度排序
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _item(id_, issue, severity="should", location="第1章", rule_id=""):
    return {
        "id": id_, "issue": issue, "severity": severity,
        "location": location, "rule_id": rule_id,
        "suggestion": "建议" + id_, "evidence_type": "A",
        "evidence_content": "", "confidence_score": 0.9,
    }


class TestMergeAndDeduplicate:
    def test_empty_input_returns_empty(self):
        from parallel_review import merge_and_deduplicate
        assert merge_and_deduplicate([]) == []

    def test_single_item_preserved(self):
        from parallel_review import merge_and_deduplicate
        items = [_item("R-001", "缺少错误码")]
        result = merge_and_deduplicate(items)
        assert len(result) == 1
        assert result[0]["issue"] == "缺少错误码"

    def test_distinct_items_all_kept(self):
        """四个明显不同的 items → 全保留,重编号。"""
        from parallel_review import merge_and_deduplicate
        items = [
            _item("R-001", "字段类型缺失"),
            _item("R-002", "接口文档不全"),
            _item("R-003", "性能指标未定义"),
            _item("R-004", "缓存策略未说明"),
        ]
        result = merge_and_deduplicate(items)
        assert len(result) == 4
        assert [it["id"] for it in result] == ["R-001", "R-002", "R-003", "R-004"]

    def test_similar_items_deduplicated(self):
        """两条 location+issue 相似度 > 80% → 去重。"""
        from parallel_review import merge_and_deduplicate
        items = [
            _item("R-001", "缺少错误码定义和异常处理说明", location="第3章"),
            _item("R-002", "缺少错误码定义和异常处理说明", location="第3章"),
        ]
        result = merge_and_deduplicate(items)
        assert len(result) == 1

    def test_dedup_prefers_higher_severity(self):
        """重复 items 中,must 严重度应替换 should。"""
        from parallel_review import merge_and_deduplicate
        items = [
            _item("R-001", "字段缺失问题需要补充说明和示例", severity="should"),
            _item("R-002", "字段缺失问题需要补充说明和示例", severity="must"),
        ]
        result = merge_and_deduplicate(items)
        assert len(result) == 1
        assert result[0]["severity"] == "must"

    def test_result_sorted_must_first(self):
        from parallel_review import merge_and_deduplicate
        items = [
            _item("R-001", "问题A", severity="should"),
            _item("R-002", "问题B", severity="must"),
            _item("R-003", "问题C", severity="should"),
            _item("R-004", "问题D", severity="must"),
        ]
        result = merge_and_deduplicate(items)
        # must 在前
        severities = [it["severity"] for it in result]
        must_indices = [i for i, s in enumerate(severities) if s == "must"]
        should_indices = [i for i, s in enumerate(severities) if s == "should"]
        if must_indices and should_indices:
            assert max(must_indices) < min(should_indices)

    def test_renumbered_sequentially(self):
        from parallel_review import merge_and_deduplicate
        items = [
            _item("R-099", "字段类型缺失导致前端渲染异常"),
            _item("R-042", "接口限流策略未定义"),
        ]
        result = merge_and_deduplicate(items)
        assert [it["id"] for it in result] == ["R-001", "R-002"]


class TestMajorityVote:
    def test_empty_input(self):
        from parallel_review import majority_vote
        assert majority_vote([]) == []

    def test_single_run_yields_nothing_at_default_votes(self):
        """min_votes=2 默认,只一轮 → 什么也不过。"""
        from parallel_review import majority_vote
        single_run = [[_item("R-001", "foo", rule_id="RC-1")]]
        assert majority_vote(single_run) == []

    def test_single_run_min_votes_1(self):
        from parallel_review import majority_vote
        single_run = [[_item("R-001", "foo", rule_id="RC-1")]]
        result = majority_vote(single_run, min_votes=1)
        assert len(result) == 1

    def test_rule_id_exact_match_across_runs(self):
        """同 rule_id + 相似 location 出现在 2 轮 → 保留。"""
        from parallel_review import majority_vote
        run1 = [_item("R-001", "问题 a", rule_id="RC-1", location="第3章")]
        run2 = [_item("R-002", "问题 b", rule_id="RC-1", location="第3章")]  # 同 rule_id
        result = majority_vote([run1, run2], min_votes=2)
        assert len(result) == 1

    def test_issue_similarity_fallback(self):
        """没 rule_id,但 issue 相似度高 → 也合并。"""
        from parallel_review import majority_vote
        run1 = [_item("R-001", "缺少错误码定义和异常处理说明")]
        run2 = [_item("R-002", "缺少错误码定义和异常处理说明的补充")]
        result = majority_vote([run1, run2], min_votes=2)
        assert len(result) >= 1  # 至少合并为 1 条

    def test_below_min_votes_dropped(self):
        """只在 1 轮出现 → min_votes=2 时被丢弃。"""
        from parallel_review import majority_vote
        run1 = [_item("R-001", "问题 A", rule_id="RC-1")]
        run2 = [_item("R-002", "完全无关的问题 B", rule_id="RC-2")]
        result = majority_vote([run1, run2], min_votes=2)
        assert result == []  # 都不达阈值

    def test_keeps_longest_item_on_merge(self):
        """合并到同一 cluster 时,保留 issue+suggestion 最长的那条。"""
        from parallel_review import majority_vote
        short = _item("R-001", "短", rule_id="RC-1", location="第3章")
        short["suggestion"] = "短"
        long_ = _item("R-002", "这是一个长得多的问题描述", rule_id="RC-1", location="第3章")
        long_["suggestion"] = "这是一个更详细的建议文本"
        result = majority_vote([[short], [long_]], min_votes=2)
        assert len(result) == 1
        # 最长的那条被保留
        assert "长得多" in result[0]["issue"]

    def test_renumbering_after_vote(self):
        from parallel_review import majority_vote
        run1 = [
            _item("R-099", "a", rule_id="RC-1"),
            _item("R-042", "b", rule_id="RC-2"),
        ]
        run2 = [
            _item("R-001", "aa", rule_id="RC-1"),
            _item("R-002", "bb", rule_id="RC-2"),
        ]
        result = majority_vote([run1, run2], min_votes=2)
        assert len(result) == 2
        # 重新编号,从 R-001 开始
        ids = [it["id"] for it in result]
        assert "R-001" in ids and "R-002" in ids

    def test_must_sorted_first(self):
        from parallel_review import majority_vote
        run1 = [
            _item("R-001", "a", severity="should", rule_id="RC-1"),
            _item("R-002", "b", severity="must", rule_id="RC-2"),
        ]
        run2 = [
            _item("R-003", "aa", severity="should", rule_id="RC-1"),
            _item("R-004", "bb", severity="must", rule_id="RC-2"),
        ]
        result = majority_vote([run1, run2], min_votes=2)
        assert result[0]["severity"] == "must"
