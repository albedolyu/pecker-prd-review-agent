"""worker.py SUBMIT_REVIEW_ITEMS_TOOL 动态 enum 注入 + valid_rule_ids 单点 (step 3.3, 2026-04-27).

设计 doc: docs/schema_registry_design_2026_04_27.md Part 3 step 3.

step 3.3 关键改动:
1. SUBMIT_REVIEW_ITEMS_TOOL 静态结构保留 (rule_id 仍是裸 string, 不加 enum) —
   静态 export 给 P0-B 防回归测试用.
2. dim_constrained_tool (per-dimension 实例) 在 _prepare_worker_context 内由 registry
   按当前 dim_key 注入 rule_id.enum, 让 LLM tool call 在 schema 层就被挡.
3. _postprocess_items 的 valid_rule_ids 改用 registry.dimension_rules(dim_key)
   作 defense-in-depth (registry enum 已挡, 这里仅作监控用).

本测试覆盖 5 类断言:
- dim_constrained_tool.rule_id 真含 registry 给的 V/RC/EV/FN id (per-dimension)
- data_quality 维度的 enum 不含 quality 维度的 rule_id (per-dimension 互斥)
- _postprocess_items valid 来源是 registry 不是 dim["checklist"] 现算
- 模拟 LLM 出 'DQ-XX' 幻觉 ID 时 → cross_boundary 标 + emit warning (defense)
- 4 worker 跑同 PRD, registry 单例命中 (lru_cache)
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture(autouse=True)
def _clear_registry_cache():
    """每个 test 前清 cache, 防互相污染."""
    from review.schema_registry import SchemaRegistry
    from review.dimensions import _cached_load
    SchemaRegistry._cached_get.cache_clear()
    _cached_load.cache_clear()
    yield
    SchemaRegistry._cached_get.cache_clear()
    _cached_load.cache_clear()


# ============================================================
# 1. dim_constrained_tool.rule_id enum 真含 registry id (per-dimension)
# ============================================================


class TestDimConstrainedToolEnumFromRegistry:
    """_prepare_worker_context 构出的 dim_constrained_tool 的 rule_id 字段
    应含 registry 给的 dim 维度规则 id, 不再裸 string."""

    def test_structure_dim_enum_includes_v_ev_fn(self):
        """structure 维度的 dim_constrained_tool.rule_id.enum 应含 V-02 / EV-01 / FN-09."""
        from review.worker import _prepare_worker_context
        ctx = _prepare_worker_context(
            dim_key="structure",
            model_tiers={"sonnet": "claude-sonnet-4-5"},
            rule_perf_history=None,
            wiki_path=None,
            wiki_pages={},
            prd_content="测试 PRD",
        )
        tool = ctx["dim_constrained_tool"]
        rule_id_schema = (
            tool["input_schema"]["properties"]["items"]
                ["items"]["properties"]["rule_id"]
        )
        # P0-B 修法: rule_id 字段必须有 enum 约束 (registry 注入)
        assert "enum" in rule_id_schema, (
            "step 3.3 修法: dim_constrained_tool.rule_id 应有 registry 注入的 enum, "
            "不再裸 string. 否则 LLM 可幻觉 ID 绕开."
        )
        enum_ids = set(rule_id_schema["enum"])
        # structure 维度真规则 (registry 来源)
        assert "V-02" in enum_ids, f"structure dim enum 应含 V-02, 实际 {enum_ids}"
        assert "EV-01" in enum_ids, f"structure dim enum 应含 EV-01"
        assert "FN-09" in enum_ids, f"structure dim enum 应含 FN-09"

    def test_data_quality_enum_excludes_quality_rules(self):
        """data_quality 维度的 enum 不应含 quality 维度的 rule_id (per-dimension 互斥)."""
        from review.worker import _prepare_worker_context
        ctx_dq = _prepare_worker_context(
            dim_key="data_quality",
            model_tiers={"sonnet": "claude-sonnet-4-5"},
            rule_perf_history=None,
            wiki_path=None,
            wiki_pages={},
            prd_content="测试",
        )
        ctx_q = _prepare_worker_context(
            dim_key="quality",
            model_tiers={"sonnet": "claude-sonnet-4-5"},
            rule_perf_history=None,
            wiki_path=None,
            wiki_pages={},
            prd_content="测试",
        )
        dq_enum = set(
            ctx_dq["dim_constrained_tool"]["input_schema"]["properties"]
                ["items"]["items"]["properties"]["rule_id"]["enum"]
        )
        q_enum = set(
            ctx_q["dim_constrained_tool"]["input_schema"]["properties"]
                ["items"]["items"]["properties"]["rule_id"]["enum"]
        )
        # 互斥: V-07 / V-08 是 quality 维度, 不应在 data_quality enum
        # FN-01 / RC-009 是 data_quality, 不应在 quality enum
        assert "V-07" in q_enum
        assert "V-07" not in dq_enum, (
            f"V-07 是 quality 维度, 不应在 data_quality enum: {dq_enum}"
        )
        assert "FN-01" in dq_enum
        assert "FN-01" not in q_enum, (
            f"FN-01 是 data_quality 维度, 不应在 quality enum"
        )


# ============================================================
# 2. _postprocess_items valid_rule_ids 走 registry, 不再现算 dim["checklist"]
# ============================================================


class TestValidRuleIdsUsesRegistry:
    """_postprocess_items 的越界判定改用 registry, 不再依赖 dim['checklist'] 现算.

    关键: 真 worker 拿到的 dim 来自 dimensions (step 3.2 已 registry-backed),
    所以 dim['checklist'] 与 registry 同步. 但若 caller 传合成 dim (test fixture),
    registry 仍是 SoT — fixture 不再能伪造 valid 集合.
    """

    def test_unknown_rule_id_dropped_via_registry(self):
        """传 dim_key='structure', items 含 V-02 (registry 真有) + DQ-99 (幻觉 id).
        P1 修法 (任务 2 R3 暴露): DQ-99 ∉ registry.all_rule_ids() → drop, 不再仅打标.
        V-02 ∈ registry 且属于 structure → 留, 0 标.
        """
        from review.worker import _postprocess_items
        from review.dimensions import get_review_dimensions
        dim = get_review_dimensions()["structure"]
        items = [
            {"id": "R-1", "rule_id": "V-02", "issue": "in", "severity": "must",
             "confidence_score": 0.9},
            {"id": "R-2", "rule_id": "DQ-99", "issue": "幻觉", "severity": "should",
             "confidence_score": 0.8},
        ]
        out, _tele = _postprocess_items(items, dim, "structure")
        # V-02 留 (合法 + dim 对应)
        v02s = [x for x in out if x["id"] == "R-1"]
        assert len(v02s) == 1, "V-02 是 structure 真规则, 应留下"
        assert "cross_boundary" not in v02s[0]
        # DQ-99 drop (∉ all_rule_ids → 幻觉)
        dq99s = [x for x in out if x["id"] == "R-2"]
        assert len(dq99s) == 0, (
            f"P1 修法: DQ-99 ∉ registry.all_rule_ids() 必须 drop. 实际 out={out}"
        )

    def test_cross_dimension_rule_kept_with_flag(self):
        """V-07 是 quality 维度的真规则, 但传 dim_key='structure' 时:
        ∈ all_rule_ids 但 ∉ dim_rule_ids(structure) → 留 + 加 cross_boundary 标
        (老 defense-in-depth 行为保留: 跨维度合法 ID 不 drop, 只标)."""
        from review.worker import _postprocess_items
        from review.dimensions import get_review_dimensions
        dim = get_review_dimensions()["structure"]
        items = [
            {"id": "R-1", "rule_id": "V-07", "issue": "跨维度",
             "severity": "must", "confidence_score": 0.9},
        ]
        out, _tele = _postprocess_items(items, dim, "structure")
        # V-07 ∈ all_rule_ids (quality 维度), 不 drop, 加 cross_boundary 标
        assert len(out) == 1, "V-07 ∈ all_rule_ids → 留 (跨维度合法 ID)"
        assert out[0].get("cross_boundary") is True

    def test_emits_warning_for_unknown_rule_id(self, caplog):
        """P1 修法: 幻觉 rule_id (∉ all_rule_ids) drop 时应 emit warning,
        让监控能抓到 LLM 出 unknown rule_id 的频率."""
        import logging
        from review.worker import _postprocess_items
        from review.dimensions import get_review_dimensions
        dim = get_review_dimensions()["structure"]
        items = [
            {"id": "R-1", "rule_id": "ZZ-99", "issue": "幻觉",
             "severity": "must", "confidence_score": 0.9},
        ]
        with caplog.at_level(logging.WARNING):
            out, _tele = _postprocess_items(items, dim, "structure")
        # P1 修法: ZZ-99 ∉ all_rule_ids → drop
        assert len(out) == 0, "ZZ-99 ∉ all_rule_ids 必须 drop"
        # warning 真 emit
        msgs = " ".join(r.getMessage() for r in caplog.records)
        assert "ZZ-99" in msgs and ("drop" in msgs.lower() or "幻觉" in msgs or "unknown" in msgs.lower()), (
            f"unknown rule_id 应 emit drop warning, 实际记录: {msgs}"
        )


# ============================================================
# 3. SchemaRegistry singleton 跨 worker 命中 (lru_cache)
# ============================================================


class TestRegistrySingletonAcrossWorkers:
    """4 worker 跑同 PRD 应命中 lru_cache, 不重复 yaml 加载."""

    def test_registry_singleton_across_dim_contexts(self):
        """4 维度依次构 worker context, registry 都应是同一实例 (lru_cache key 命中)."""
        from review.worker import _prepare_worker_context
        from review.schema_registry import SchemaRegistry

        # 4 维度全部走 _prepare_worker_context, registry 应 hit 同一实例
        instances = []
        for dim_key in ("structure", "quality", "ai_coding", "data_quality"):
            _prepare_worker_context(
                dim_key=dim_key,
                model_tiers={"sonnet": "claude-sonnet-4-5",
                             "haiku": "claude-haiku-4-5",
                             "opus": "claude-opus-4-5"},
                rule_perf_history=None,
                wiki_path=None,
                wiki_pages={},
                prd_content="同 PRD",
            )
            instances.append(SchemaRegistry.get())

        # 全是同一 instance (lru_cache 命中)
        assert all(inst is instances[0] for inst in instances), (
            "4 worker 跑同 PRD 应命中 registry lru_cache"
        )


# ============================================================
# 4. 静态 SUBMIT_REVIEW_ITEMS_TOOL 仍保留无 enum (P0-B 防回归)
# ============================================================


class TestStaticToolUnchanged:
    """静态 SUBMIT_REVIEW_ITEMS_TOOL 仍是 export 标识, rule_id 仍是裸 string.
    enum 注入只在 dim_constrained_tool 实例上, 这是 step 3.3 的设计契约."""

    def test_static_export_no_enum(self):
        """老 P0-B test_rule_id_field_no_enum 防回归: 静态 SUBMIT_REVIEW_ITEMS_TOOL
        rule_id 字段不应有 enum. step 3.3 修法只动 dim_constrained_tool 实例."""
        from review.worker import SUBMIT_REVIEW_ITEMS_TOOL
        rule_id_schema = (
            SUBMIT_REVIEW_ITEMS_TOOL["input_schema"]["properties"]["items"]
                ["items"]["properties"]["rule_id"]
        )
        assert "enum" not in rule_id_schema, (
            "step 3.3 设计: 静态 SUBMIT_REVIEW_ITEMS_TOOL 不动 (P0-B 防回归), "
            "enum 注入仅在 dim_constrained_tool 运行时实例."
        )
        assert rule_id_schema.get("type") == "string"


# ============================================================
# 5. P1 anti-corruption drop (任务 2 R3 暴露的 fragility)
# ============================================================
#
# 背景: docs/calibration_multi_run_2026_04_28.md R3 暴露 worker 出 16 条幻觉 ID
# (DQ-XX/AC-XX), anti-corruption 设计为 warn-only 不 drop, 检测 100% / 拦截 0%.
# step 3.3 dim_constrained_tool enum 应是硬挡, 但 R3 实测 LLM 仍能输出非法 ID.
# 修法: _postprocess_items 区分 3 类:
#   ∈ all_rule_ids ∩ dim_rule_ids   → 留 (合法本维度)
#   ∈ all_rule_ids \ dim_rule_ids   → 留 + cross_boundary 标 (跨维度合法)
#   ∉ all_rule_ids                  → drop + log warning (幻觉)


class TestAntiCorruptionDrop:
    """P1 修法 (任务 2 R3 暴露): 幻觉 ID drop, 跨维度合法 ID 留."""

    def test_unknown_rule_id_dropped(self):
        """worker 提交 DQ-XX (不在 registry) → drop, 不进 final."""
        from review.worker import _postprocess_items
        from review.dimensions import get_review_dimensions
        dim = get_review_dimensions()["data_quality"]
        items = [
            {"id": "R-1", "rule_id": "DQ-01", "issue": "假规则",
             "severity": "must", "confidence_score": 0.9},
            {"id": "R-2", "rule_id": "AC-15", "issue": "也是假",
             "severity": "should", "confidence_score": 0.85},
        ]
        out, _tele = _postprocess_items(items, dim, "data_quality")
        # 两条都 drop (DQ-/AC- 不是 registry 注册前缀)
        assert len(out) == 0, (
            f"P1 修法: DQ-01 / AC-15 ∉ registry → 全 drop. 实际剩 {len(out)} 条."
        )

    def test_cross_dimension_rule_id_kept_with_flag(self):
        """worker 提交 V-07 但 dim=data_quality (V-07 是 quality dim) → 留 + 加 cross_boundary 标.
        关键: 区分'跨维度合法' vs '幻觉' — 前者留, 后者 drop."""
        from review.worker import _postprocess_items
        from review.dimensions import get_review_dimensions
        dim = get_review_dimensions()["data_quality"]
        items = [
            {"id": "R-1", "rule_id": "V-07", "issue": "跨维度合法",
             "severity": "must", "confidence_score": 0.9},
        ]
        out, _tele = _postprocess_items(items, dim, "data_quality")
        # V-07 ∈ all_rule_ids (quality dim) → 留, 加 cross_boundary 标
        assert len(out) == 1, "V-07 ∈ all_rule_ids 应留 (不 drop)"
        assert out[0].get("cross_boundary") is True
        # confidence 受 -0.3 惩罚 (老 defense-in-depth 保留)
        assert out[0]["confidence_score"] == round(0.9 - 0.3, 2)

    def test_legit_rule_id_kept_clean(self):
        """worker 提交 V-02 在 structure dim (V-02 是 structure dim 的真规则) → 留, 0 标."""
        from review.worker import _postprocess_items
        from review.dimensions import get_review_dimensions
        dim = get_review_dimensions()["structure"]
        items = [
            {"id": "R-1", "rule_id": "V-02", "issue": "合法本维度",
             "severity": "must", "confidence_score": 0.9},
        ]
        out, _tele = _postprocess_items(items, dim, "structure")
        assert len(out) == 1
        # 不应 cross_boundary, confidence 不受惩罚
        assert "cross_boundary" not in out[0]
        assert out[0]["confidence_score"] == 0.9

    def test_drop_reason_emitted_to_jsonl(self, caplog):
        """drop 时 log 含 drop_unknown_rule_id 关键字 + rule_id, 让 funnel telemetry 能聚合.

        当前 worker 的 telemetry 通过 worker dict 上抛, 上游 funnel_telemetry
        compute_worker_raw_stage 读 w['telemetry'] 聚合. 这测试只验 _postprocess_items
        emit warning 含足够信息让 jsonl event 能记 drop_unknown_rule_id 事件.
        """
        import logging
        from review.worker import _postprocess_items
        from review.dimensions import get_review_dimensions
        dim = get_review_dimensions()["quality"]
        items = [
            {"id": "R-1", "rule_id": "FAKE-X1", "issue": "幻觉",
             "severity": "must", "confidence_score": 0.9},
        ]
        with caplog.at_level(logging.WARNING):
            _postprocess_items(items, dim, "quality")
        msgs = " ".join(r.getMessage() for r in caplog.records)
        # warning 必须含 rule_id (让 PM 看 log 能 trace) + drop 关键词
        assert "FAKE-X1" in msgs, f"drop warning 应含 rule_id, 实际: {msgs}"
        assert "drop" in msgs.lower() or "幻觉" in msgs or "unknown" in msgs.lower(), (
            f"drop warning 应含 drop/幻觉/unknown 关键词, 实际: {msgs}"
        )

    def test_drop_count_in_telemetry(self):
        """funnel telemetry 含 dropped_unknown_rule_count 字段.

        worker 的 telemetry dict (worker_core 返回的 worker['telemetry']) 必须含
        dropped_unknown_rule_count 字段, 让 compute_worker_raw_stage 能聚合并入 jsonl.
        """
        from review.worker import _postprocess_items
        from review.dimensions import get_review_dimensions
        dim = get_review_dimensions()["data_quality"]
        items = [
            {"id": "R-1", "rule_id": "RC-009", "issue": "合法",
             "severity": "must", "confidence_score": 0.9},
            {"id": "R-2", "rule_id": "DQ-XX", "issue": "幻觉",
             "severity": "should", "confidence_score": 0.8},
            {"id": "R-3", "rule_id": "AC-01", "issue": "幻觉 2",
             "severity": "must", "confidence_score": 0.85},
        ]
        # _postprocess_items 改返 (items, drop_telemetry_dict)
        result = _postprocess_items(items, dim, "data_quality")
        # 真改完应返 tuple
        assert isinstance(result, tuple) and len(result) == 2, (
            "P1 修法: _postprocess_items 应返 (items, drop_telemetry) tuple"
        )
        out_items, drop_tele = result
        assert isinstance(drop_tele, dict)
        assert drop_tele.get("dropped_unknown_rule_count") == 2, (
            f"应 drop 2 条 (DQ-XX + AC-01), 实际 {drop_tele}"
        )
        # 顺便验真留 1 条 (RC-009)
        assert len(out_items) == 1
        assert out_items[0]["rule_id"] == "RC-009"

    def test_funnel_telemetry_aggregates_drop_count(self):
        """compute_worker_raw_stage 应聚合各 worker 的 dropped_unknown_rule_count
        并入 funnel jsonl event payload."""
        from review.funnel_telemetry import compute_worker_raw_stage
        # 模拟两个 worker, 各自 telemetry 含 drop count
        workers = [
            {
                "dimension": "data_quality",
                "items": [{"id": "x"}],
                "telemetry": {"dropped_unknown_rule_count": 2, "empty_retry_used": False},
            },
            {
                "dimension": "structure",
                "items": [{"id": "y"}, {"id": "z"}],
                "telemetry": {"dropped_unknown_rule_count": 0, "empty_retry_used": False},
            },
        ]
        stage = compute_worker_raw_stage(workers)
        # P1 修法: stage payload 含 dropped_unknown_rule_count 聚合字段
        assert "dropped_unknown_rule_count" in stage, (
            f"compute_worker_raw_stage 应聚合 drop count 字段, 实际 {stage}"
        )
        assert stage["dropped_unknown_rule_count"] == 2
