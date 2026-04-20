"""
Harness 级约束守卫测试 (2026-04-16 audit 落地)

覆盖:
- Fix 1: confidence_score 字段统一,越界惩罚真作用到下游
- Fix 2: 苍鹰 MAX_FALSE_POSITIVE_RATIO 硬上限
- Fix 3: EMA PER_SESSION_DELTA_CAP 过拟合保护
- Fix 4: Scratchpad 读写契约 — orchestrator 写,worker 只返回 found_rule_ids

这些测试是拓扑不变量的"合同",未来破坏会立刻 red。
"""

import os
import sys
import ast
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ============================================================
# Fix 1: confidence_score 字段统一
# ============================================================

class TestConfidenceFieldUnified:
    """越界惩罚必须作用到 confidence_score (下游消费字段),不是 confidence。"""

    def test_cross_boundary_penalty_on_confidence_score(self, tmp_path):
        """Worker item 的 rule_id 不在 checklist 时,confidence_score 应 -0.3。

        这是真 bug 的回归测: 之前改的是 confidence 字段,下游完全无感。
        """
        import parallel_review as pr

        # 构造最小 _worker_core 环境
        fake_dim = {
            "name": "测试维度",
            "model": "sonnet",
            "effort": "medium",
            "checklist": [{"rule_id": "RC-001"}],  # 只允许 RC-001
        }
        with patch("review.worker.get_review_dimensions",
                   return_value={"test_dim": fake_dim}), \
             patch("review.worker.get_wiki_keywords", return_value=[]), \
             patch("review.worker._build_worker_system", return_value="sys"), \
             patch("review.worker._build_worker_messages",
                   return_value=[{"role": "user", "content": "prd"}]), \
             patch("review.worker.PromptCacheMonitor", MagicMock, create=True), \
             patch("api_adapter.compute_call_cost_usd", return_value=0.001), \
             patch("review.worker.time.sleep", lambda _: None), \
             patch("review.worker.random.uniform", lambda a, b: 0):

            # model 返回一条越界的 item (rule_id 不在 checklist)
            from types import SimpleNamespace
            cross_boundary_item = {
                "id": "R-001",
                "rule_id": "RC-999",  # 不在 checklist!
                "issue": "foo",
                "severity": "must",
                "confidence_score": 0.9,  # 初始高置信度
            }
            response = SimpleNamespace(
                content=[SimpleNamespace(
                    type="tool_use", name="submit_review_items",
                    id="t1", input={"items": [cross_boundary_item]},
                )],
                stop_reason="end_turn",
                usage={"input_tokens": 100, "output_tokens": 50,
                       "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0},
            )
            client = MagicMock()
            client.create.return_value = response

            result = pr._worker_core(
                client=client, dim_key="test_dim",
                prd_content="PRD", wiki_pages={}, model_tiers={"sonnet": "s"},
            )

        assert len(result["items"]) == 1
        item = result["items"][0]
        assert item["cross_boundary"] is True
        # 关键断言: confidence_score 被下调到 0.9 - 0.3 = 0.6
        assert abs(item["confidence_score"] - 0.6) < 1e-6, (
            f"越界惩罚应作用到 confidence_score,实际 = {item.get('confidence_score')}。"
            f"如果这个测试失败,说明有人又把字段名改回 confidence 了。"
        )

    def test_no_penalty_when_rule_id_in_checklist(self, tmp_path):
        """合法 rule_id 不触发越界惩罚。"""
        import parallel_review as pr

        fake_dim = {
            "name": "测试维度",
            "model": "sonnet", "effort": "medium",
            "checklist": [{"rule_id": "RC-001"}],
        }
        with patch("review.worker.get_review_dimensions",
                   return_value={"test_dim": fake_dim}), \
             patch("review.worker.get_wiki_keywords", return_value=[]), \
             patch("review.worker._build_worker_system", return_value="sys"), \
             patch("review.worker._build_worker_messages",
                   return_value=[{"role": "user", "content": "prd"}]), \
             patch("review.worker.PromptCacheMonitor", MagicMock, create=True), \
             patch("api_adapter.compute_call_cost_usd", return_value=0.001):

            from types import SimpleNamespace
            ok_item = {
                "id": "R-001", "rule_id": "RC-001", "issue": "foo",
                "severity": "must", "confidence_score": 0.9,
            }
            response = SimpleNamespace(
                content=[SimpleNamespace(
                    type="tool_use", name="submit_review_items",
                    id="t1", input={"items": [ok_item]},
                )],
                stop_reason="end_turn",
                usage={"input_tokens": 100, "output_tokens": 50,
                       "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0},
            )
            client = MagicMock()
            client.create.return_value = response

            result = pr._worker_core(
                client=client, dim_key="test_dim",
                prd_content="PRD", wiki_pages={}, model_tiers={"sonnet": "s"},
            )

        item = result["items"][0]
        assert item.get("cross_boundary") is not True  # False or missing
        assert item["confidence_score"] == 0.9


# ============================================================
# Fix 2: MAX_FALSE_POSITIVE_RATIO
# ============================================================

class TestMaxFalsePositiveRatio:
    def test_constant_is_defined(self):
        from goshawk_advisor import MAX_FALSE_POSITIVE_RATIO
        assert 0 < MAX_FALSE_POSITIVE_RATIO <= 1.0
        # 拓扑语义:meta-reviewer 不应否定大多数 worker 输出
        assert MAX_FALSE_POSITIVE_RATIO <= 0.5, (
            "MAX_FALSE_POSITIVE_RATIO > 0.5 违反'meta-reviewer 只审不重审'"
        )

    def test_fp_capped_when_over_ratio(self):
        """苍鹰 flag 超过 30% items 时应被截断。

        注: apply_advisor_result 返回 active_items (已过滤掉 REMOVED_BY_ADVISOR),
        所以用"原有多少 item 被从返回列表里去掉"来衡量 flag 生效数。
        """
        from goshawk_advisor import apply_advisor_result, MAX_FALSE_POSITIVE_RATIO

        items = [
            {"id": f"R-{i:03d}", "severity": "must",
             "confidence_score": 0.5 + i * 0.04}
            for i in range(1, 11)
        ]
        original_ids = {it["id"] for it in items}

        # 模型试图 flag 7 条 (超出 ceil(10*0.3)=3 条上限)
        advisor = {
            "flagged_as_false_positive": [
                {"item_id": f"R-{i:03d}",
                 "reason": "x", "recommendation": "移除"}
                for i in range(1, 8)
            ],
            "additional_findings": [], "conflict_resolutions": [], "confidence": 0.8,
        }

        result = apply_advisor_result(items, advisor)
        surviving_ids = {it["id"] for it in result}
        removed_ids = original_ids - surviving_ids
        import math
        max_expected = math.ceil(10 * MAX_FALSE_POSITIVE_RATIO)
        assert len(removed_ids) <= max_expected, (
            f"被 flag 移除的 items {len(removed_ids)} > 硬上限 {max_expected}"
        )

    def test_fp_low_conf_items_prioritized(self):
        """超限截断时,应优先 flag 低 confidence 的 item。"""
        from goshawk_advisor import apply_advisor_result

        items = [
            {"id": "R-001", "severity": "must", "confidence_score": 0.9},
            {"id": "R-002", "severity": "must", "confidence_score": 0.3},
            {"id": "R-003", "severity": "must", "confidence_score": 0.85},
            {"id": "R-004", "severity": "must", "confidence_score": 0.2},
        ]
        advisor = {
            "flagged_as_false_positive": [
                {"item_id": f"R-{i:03d}", "reason": "x", "recommendation": "移除"}
                for i in range(1, 5)
            ],
            "additional_findings": [], "conflict_resolutions": [], "confidence": 0.5,
        }
        result = apply_advisor_result(items, advisor)
        surviving = {it["id"] for it in result}
        # 硬上限 ceil(4*0.3)=2,低 conf 的 R-004(0.2) / R-002(0.3) 应被优先 flag 移除
        assert "R-004" not in surviving
        assert "R-002" not in surviving
        # 高 conf 的 R-001 / R-003 应被保留
        assert "R-001" in surviving
        assert "R-003" in surviving

    def test_fp_within_limit_not_truncated(self):
        """不超限时不截断。"""
        from goshawk_advisor import apply_advisor_result
        items = [{"id": f"R-{i:03d}", "severity": "must",
                  "confidence_score": 0.5} for i in range(1, 11)]
        advisor = {
            "flagged_as_false_positive": [
                {"item_id": "R-001", "reason": "x", "recommendation": "移除"},
                {"item_id": "R-002", "reason": "x", "recommendation": "移除"},
            ],
            "additional_findings": [], "conflict_resolutions": [], "confidence": 0.8,
        }
        result = apply_advisor_result(items, advisor)
        surviving = {it["id"] for it in result}
        # R-001 和 R-002 被移除,剩下 8 条
        assert "R-001" not in surviving
        assert "R-002" not in surviving
        assert len(surviving) == 8


# ============================================================
# Fix 3: EMA PER_SESSION_DELTA_CAP
# ============================================================

class TestEMASessionDeltaCap:
    def _make_rules_file(self, tmp_path, rules):
        import yaml
        p = tmp_path / "rules.yaml"
        p.write_text(yaml.safe_dump(rules, allow_unicode=True), encoding="utf-8")
        return str(p)

    def _outcome(self, rule_id="RC-001", outcome_type="effective_catch", conf=1.0):
        """构造 _extract_rule_id 能匹配的 outcome (从 location 字段抓 RC-xxx)."""
        return {
            "outcome": outcome_type,
            "confidence": conf,
            "location": f"第3章 参考 {rule_id}",
        }

    def test_single_outcome_within_cap(self, tmp_path):
        """单条 outcome,未超过 cap → 正常更新。"""
        from feedback import update_rule_scores
        import yaml

        rules_file = self._make_rules_file(tmp_path, [
            {"id": "RC-001", "impact_score": 0.5},
        ])
        update_rule_scores([self._outcome()], rules_file, workspace=str(tmp_path))

        updated = yaml.safe_load(open(rules_file, encoding="utf-8"))
        score = updated[0]["impact_score"]
        # alpha=0.15, effective_alpha=0.15, new=0.15*1 + 0.85*0.5 = 0.575
        assert 0.57 <= score <= 0.58

    def test_many_outcomes_capped_at_delta_limit(self, tmp_path):
        """10 条 outcome 都指向同一 rule,累计 delta 不超过 0.15。"""
        from feedback import update_rule_scores
        import yaml

        rules_file = self._make_rules_file(tmp_path, [
            {"id": "RC-001", "impact_score": 0.5},
        ])
        outcomes = [self._outcome() for _ in range(10)]
        update_rule_scores(outcomes, rules_file, workspace=str(tmp_path))

        updated = yaml.safe_load(open(rules_file, encoding="utf-8"))
        score = updated[0]["impact_score"]
        # 从 0.5 起,累计变动不应超过 +0.15
        assert score <= 0.65 + 1e-6, (
            f"累计 delta 超出 cap, score={score} 应 <= 0.65"
        )
        # 但确实上涨了,不应退回 0.5
        assert score > 0.5


# ============================================================
# Fix 4: Scratchpad 读写契约 (单测守卫)
# ============================================================

class TestScratchpadContract:
    """scratchpad 只能由 orchestrator 构造,worker 只返回 found_rule_ids。

    用 AST 静态分析防止未来有人在 _worker_core 里引入 scratchpad 读写。
    """

    def test_worker_core_does_not_touch_scratchpad(self):
        """_worker_core 函数体不应出现 'scratchpad' 字样 (字符串或名称)。"""
        from review import worker as _worker_mod
        source = open(_worker_mod.__file__, encoding="utf-8").read()
        tree = ast.parse(source)

        worker_core_node = None
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_worker_core":
                worker_core_node = node
                break
        assert worker_core_node is not None, "_worker_core not found"

        body_src = ast.unparse(worker_core_node)
        # 核心 worker 逻辑不应该读/写 scratchpad
        # (注释和 docstring 可以提,但不允许代码访问)
        # 我们通过扫描 ast 里的 Name/Attribute 来严格检查
        violations = []
        for n in ast.walk(worker_core_node):
            if isinstance(n, ast.Name) and n.id == "scratchpad":
                violations.append(f"Name reference at line {n.lineno}")
            elif isinstance(n, ast.Attribute) and n.attr == "scratchpad":
                violations.append(f"Attribute .scratchpad at line {n.lineno}")

        assert not violations, (
            "_worker_core 不应直接访问 scratchpad,违反拓扑契约"
            " (orchestrator 单向写,worker 只返回 found_rule_ids)。违规:"
            + ", ".join(violations)
        )

    def test_worker_returns_found_rule_ids(self):
        """Worker return dict 必须含 found_rule_ids (供 orchestrator 构造 scratchpad)。"""
        from review import worker as _worker_mod
        source = open(_worker_mod.__file__, encoding="utf-8").read()
        # 简单字符串匹配:_worker_core 的 return 块里应有 found_rule_ids
        # 更严格做法用 ast,这里够用
        core_start = source.index("def _worker_core")
        core_end = source.index("\ndef ", core_start + 10)
        core_body = source[core_start:core_end]
        assert '"found_rule_ids"' in core_body, (
            "_worker_core 必须返回 found_rule_ids,供 orchestrator 构造 scratchpad"
        )

    def test_scratchpad_only_in_orchestrator_functions(self):
        """scratchpad 变量名只能出现在 _single_round_* 或 parallel_review* 里。"""
        from review import orchestration as _orch_mod
        source = open(_orch_mod.__file__, encoding="utf-8").read()
        tree = ast.parse(source)

        # 收集每个顶层函数的 scratchpad 使用
        functions_using_scratchpad = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                for n in ast.walk(node):
                    if isinstance(n, ast.Name) and n.id == "scratchpad":
                        functions_using_scratchpad.add(node.name)

        # 白名单:只允许 orchestrator 层
        allowed_prefixes = ("_single_round", "parallel_review")
        for fn in functions_using_scratchpad:
            assert any(fn.startswith(p) for p in allowed_prefixes), (
                f"scratchpad 出现在非 orchestrator 函数 {fn},违反拓扑契约"
            )
