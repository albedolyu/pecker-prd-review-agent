"""P0-2 worker 软上限 + WORKER_SEED 单测 (2026-04-26 sprint Day3).

spec: docs/sprint-real-prd-calibration-evidence-governance.md (后续追加 P0-2 章节)

测试矩阵:
- 软上限 = MAX_ITEMS * 1.5 (默认 22), 低于此不截
- 高于软上限按 severity (must 优先) + confidence (高优) 排序截 top N
- WORKER_SEED 非空时 tie-break 用 hash, 同输入 deterministic
- 不带 seed 行为兼容老逻辑 (按 severity+confidence 双排序)

测试隔离: 直接 monkeypatch.setattr 改 agent_config 模块属性,
避免 env+importlib.reload 在 pytest 跨测试的副作用.
"""
from __future__ import annotations

import pytest


def _make_items(n, severity="should", confidence=0.5, prefix="R"):
    """生成 n 条 fake items, 同 severity 同 confidence.

    2026-04-28 P1: rule_id 必须 rotate registry 真 ID, 否则 anti-corruption drop 会截掉.
    structure 维度真 rule_id 用 V-02..V-06 / EV-01 / FN-09 这些, 循环用.
    本测试关心的是 soft_cap 截断逻辑, 不关心 cross_boundary 标记 — 用 structure 维度的真 ID
    避免触发 P1 drop.
    """
    from review.schema_registry import SchemaRegistry
    reg = SchemaRegistry.get(workspace=None)
    structure_ids = sorted(r.rule_id for r in reg.dimension_rules("structure"))
    if not structure_ids:
        # 兜底: registry 空时退到原 fixture (单测兼容 PECKER_SCHEMA_FALLBACK 模式)
        structure_ids = [f"V-{i:03d}" for i in range(n)]
    return [
        {"id": f"{prefix}-{i:03d}",
         "rule_id": structure_ids[i % len(structure_ids)],
         "issue": f"问题 {i}",
         "severity": severity, "confidence_score": confidence}
        for i in range(n)
    ]


def _make_dim(checklist_ids=None):
    return {
        "name": "结构层",
        "checklist": [{"rule_id": rid} for rid in (checklist_ids or [])],
    }


@pytest.fixture
def patch_worker_config(monkeypatch):
    """直接 patch agent_config 模块的 MAX_ITEMS_PER_WORKER / WORKER_SOFT_CAP_MULTIPLIER / WORKER_SEED.

    返回 setter 函数, 调用 patch(max_items=10, multiplier=1.5, seed='').
    """
    import agent_config

    def setter(max_items=15, multiplier=1.5, seed=""):
        monkeypatch.setattr(agent_config, "MAX_ITEMS_PER_WORKER", max_items)
        monkeypatch.setattr(agent_config, "WORKER_SOFT_CAP_MULTIPLIER", multiplier)
        monkeypatch.setattr(agent_config, "WORKER_SEED", seed)
    return setter


# ============================================================
# 软上限触发条件
# ============================================================

class TestSoftCap:
    def test_below_soft_cap_keeps_all(self, patch_worker_config):
        """N0=18 < soft_cap 22 → 全保留."""
        patch_worker_config(max_items=15, multiplier=1.5)
        from review.worker import _postprocess_items
        out, _ = _postprocess_items(_make_items(18), _make_dim(), "structure")
        assert len(out) == 18, f"18 < soft_cap (22), 应全保留, 实际 {len(out)}"

    def test_at_soft_cap_keeps_all(self, patch_worker_config):
        patch_worker_config(max_items=15, multiplier=1.5)
        from review.worker import _postprocess_items
        out, _ = _postprocess_items(_make_items(22), _make_dim(), "structure")
        assert len(out) == 22

    def test_above_soft_cap_truncates(self, patch_worker_config):
        """N0=30 > 22 → 截到 22."""
        patch_worker_config(max_items=15, multiplier=1.5)
        from review.worker import _postprocess_items
        out, _ = _postprocess_items(_make_items(30), _make_dim(), "structure")
        assert len(out) == 22

    def test_must_priority_over_should(self, patch_worker_config):
        """20 条 (10 must + 10 should), soft_cap=15 → 保留 10 must + 5 should."""
        patch_worker_config(max_items=10, multiplier=1.5)
        from review.worker import _postprocess_items
        items = _make_items(10, severity="must", prefix="M") + _make_items(10, severity="should", prefix="S")
        out, _ = _postprocess_items(items, _make_dim(), "structure")
        assert len(out) == 15
        must_count = sum(1 for x in out if x["severity"] == "must")
        assert must_count == 10, f"10 must 应全保, 实际 {must_count}"

    def test_confidence_desc_within_severity(self, patch_worker_config):
        """同 severity 内, 高 confidence 优先."""
        patch_worker_config(max_items=10, multiplier=1.5)
        from review.worker import _postprocess_items
        from review.schema_registry import SchemaRegistry
        # 2026-04-28 P1: rule_id 必须 rotate registry 真 ID 防 anti-corruption drop
        reg = SchemaRegistry.get(workspace=None)
        valid_ids = sorted(r.rule_id for r in reg.dimension_rules("structure"))
        if not valid_ids:
            valid_ids = [f"V-{i:03d}" for i in range(20)]
        # 20 should items, confidence 1.0 → 0.05
        items = [
            {"id": f"R-{i:03d}", "rule_id": valid_ids[i % len(valid_ids)], "issue": "x",
             "severity": "should", "confidence_score": round(1.0 - i * 0.05, 2)}
            for i in range(20)
        ]
        out, _ = _postprocess_items(items, _make_dim(), "structure")
        assert len(out) == 15
        # 应保留 confidence 最高的 R-000~R-014
        kept_ids = sorted(x["id"] for x in out)
        assert kept_ids == [f"R-{i:03d}" for i in range(15)]


# ============================================================
# WORKER_SEED deterministic
# ============================================================

class TestWorkerSeed:
    def test_with_seed_deterministic(self, patch_worker_config):
        """同 seed + 同 items + 同序 → 截断结果一致."""
        patch_worker_config(max_items=10, multiplier=1.5, seed="seed-001")
        from review.worker import _postprocess_items
        items1 = _make_items(20, confidence=0.5)
        items2 = _make_items(20, confidence=0.5)
        out1, _ = _postprocess_items(items1, _make_dim(), "structure")
        out2, _ = _postprocess_items(items2, _make_dim(), "structure")
        assert [x["id"] for x in out1] == [x["id"] for x in out2]

    def test_different_seed_different_result(self, monkeypatch):
        """不同 seed 截不同子集."""
        import agent_config
        from review.worker import _postprocess_items

        items = _make_items(20, confidence=0.5)

        monkeypatch.setattr(agent_config, "MAX_ITEMS_PER_WORKER", 10)
        monkeypatch.setattr(agent_config, "WORKER_SOFT_CAP_MULTIPLIER", 1.5)

        monkeypatch.setattr(agent_config, "WORKER_SEED", "seed-A")
        out_A, _ = _postprocess_items([dict(x) for x in items], _make_dim(), "structure")
        ids_A = set(x["id"] for x in out_A)

        monkeypatch.setattr(agent_config, "WORKER_SEED", "seed-B-totally-different")
        out_B, _ = _postprocess_items([dict(x) for x in items], _make_dim(), "structure")
        ids_B = set(x["id"] for x in out_B)

        assert ids_A != ids_B, f"不同 seed 应选不同子集, A={sorted(ids_A)}, B={sorted(ids_B)}"

    def test_no_seed_uses_legacy_sort(self, patch_worker_config):
        """空 seed → 不引 hash, 兼容老行为."""
        patch_worker_config(max_items=10, multiplier=1.5, seed="")
        from review.worker import _postprocess_items
        # confidence 全 0.5 → 排序仅 severity, 同 severity 保持 stable sort 顺序
        items = _make_items(20, confidence=0.5)
        out, _ = _postprocess_items(items, _make_dim(), "structure")
        assert len(out) == 15
        # stable sort 保持原顺序 → 前 15 个应该是 R-000~R-014
        kept_ids = [x["id"] for x in out]
        assert kept_ids == [f"R-{i:03d}" for i in range(15)]


# ============================================================
# 兼容性: 现有功能不破
# ============================================================

class TestBackwardCompat:
    def test_dict_filter_still_works(self, patch_worker_config):
        patch_worker_config()
        from review.worker import _postprocess_items
        items = _make_items(5) + ["not a dict", 123, None]
        out, _ = _postprocess_items(items, _make_dim(), "structure")
        assert len(out) == 5

    def test_dimension_correction(self, patch_worker_config):
        patch_worker_config()
        from review.worker import _postprocess_items
        items = _make_items(3)
        for i in items:
            i["dimension"] = "错误维度"
        out, _ = _postprocess_items(items, _make_dim(), "structure")
        for i in out:
            assert i["dimension"] == "结构层"

    def test_cross_boundary_marking(self, patch_worker_config):
        """2026-04-28 P1 修法 (任务 2 R3): cross_boundary 仅给跨维度合法 ID,
        幻觉 (∉ all_rule_ids 如 V-99) 改 drop. 本测试用 V-07 (quality 维度) 替代 V-99."""
        patch_worker_config()
        from review.worker import _postprocess_items
        items = [
            {"id": "R-1", "rule_id": "V-02", "issue": "in", "severity": "must", "confidence_score": 0.9},
            # V-07 ∈ registry (quality 维度) → 跨维度合法, 留 + 标 (替代 V-99 幻觉测试)
            {"id": "R-2", "rule_id": "V-07", "issue": "cross", "severity": "should", "confidence_score": 0.8},
        ]
        out, _ = _postprocess_items(items, _make_dim(), "structure")
        v2 = next(x for x in out if x["id"] == "R-1")
        v99 = next(x for x in out if x["id"] == "R-2")
        assert "cross_boundary" not in v2
        assert v99.get("cross_boundary") is True
        assert v99["confidence_score"] == 0.5
