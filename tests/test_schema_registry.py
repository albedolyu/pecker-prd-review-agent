"""schema_registry 骨架单测 (step 3.1).

参考 docs/schema_registry_design_2026_04_27.md.

覆盖:
1. 单例 lru_cache 行为
2. all_rule_ids 含 V/RC/EV/FN 各前缀代表
3. get_rule 返回 frozen RuleDef
4. get_rule 未知 id raise KeyError
5. rule_id_pattern 动态拼接, 命中真规则不命中假前缀
6. dimension_rules 按维度过滤
7. yaml 加载失败默认 raise SchemaRegistryError
8. PECKER_SCHEMA_FALLBACK=1 时返回空 registry (warn)
9. cross_section 字段在 V-05 / V-06 / RC-009 上为 True
10. reload() 清 cache 后重 load 返回新实例
"""

from __future__ import annotations

import os
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from review.schema_registry import (
    RuleDef,
    SchemaRegistry,
    SchemaRegistryError,
)


@pytest.fixture(autouse=True)
def _clear_registry_cache():
    """每个 test 前清 cache, 防互相污染.

    同时 monkeypatch 不到的 dimensions._cached_load 也清一遍 (fallback test 改 yaml 时).
    """
    SchemaRegistry._cached_get.cache_clear()
    from review.dimensions import _cached_load
    _cached_load.cache_clear()
    yield
    SchemaRegistry._cached_get.cache_clear()
    _cached_load.cache_clear()


# ============================================================
# 1. 单例 + lru_cache
# ============================================================


def test_get_returns_singleton():
    """SchemaRegistry.get() 多次调返回同一实例 (lru_cache 命中)."""
    a = SchemaRegistry.get()
    b = SchemaRegistry.get()
    assert a is b


def test_get_different_workspace_returns_different_instance(tmp_path, monkeypatch):
    """不同 workspace 应返回不同 instance (lru_cache key 分桶)."""
    monkeypatch.delenv("WORKSPACE", raising=False)
    a = SchemaRegistry.get()
    b = SchemaRegistry.get(workspace=str(tmp_path))
    # 不同 workspace, b 加载会找不到 ws yaml, 走全局 yaml, 仍是不同 instance
    assert a is not b


# ============================================================
# 2. all_rule_ids 覆盖 4 前缀
# ============================================================


def test_all_rule_ids_includes_v_rc_ev_fn():
    """全局 yaml 应至少含 V/RC/EV/FN 4 个前缀的代表."""
    reg = SchemaRegistry.get()
    ids = reg.all_rule_ids()
    # 来自实际 yaml: V-02 (structure), RC-009 (data_quality), EV-01 (structure), FN-01 (data_quality)
    assert "V-02" in ids
    assert "RC-009" in ids
    assert "EV-01" in ids
    assert "FN-01" in ids
    # 应是 frozenset
    assert isinstance(ids, frozenset)


# ============================================================
# 3. get_rule 返回 frozen RuleDef
# ============================================================


def test_get_rule_returns_frozen_ruledef():
    """get_rule('V-02') 返回 RuleDef instance, 且 frozen."""
    reg = SchemaRegistry.get()
    rule = reg.get_rule("V-02")
    assert isinstance(rule, RuleDef)
    assert rule.rule_id == "V-02"
    assert rule.dimension == "structure"
    # frozen — setattr 应 raise
    with pytest.raises((AttributeError, Exception)):
        rule.name = "改不动"   # type: ignore[misc]


# ============================================================
# 4. get_rule 未知 id raise KeyError
# ============================================================


def test_get_rule_unknown_raises_keyerror():
    """get_rule('ZZ-99') 应 raise KeyError, 不沉默返 None."""
    reg = SchemaRegistry.get()
    with pytest.raises(KeyError):
        reg.get_rule("ZZ-99")


# ============================================================
# 5. rule_id_pattern 单点
# ============================================================


def test_rule_id_pattern_matches_known_ids():
    """rule_id_pattern() 命中真前缀, 不命中 DQ-XX 这种伪前缀."""
    reg = SchemaRegistry.get()
    pattern = reg.rule_id_pattern()
    # 命中已注册前缀
    assert re.match(pattern, "FN-01")
    assert re.match(pattern, "V-02")
    assert re.match(pattern, "RC-009")
    assert re.match(pattern, "EV-01")
    # 不命中
    assert re.match(pattern, "DQ-XX") is None
    assert re.match(pattern, "BMAD-V-01") is None
    assert re.match(pattern, "v-01") is None  # 大小写敏感


# ============================================================
# 6. dimension_rules 按维度过滤
# ============================================================


def test_dimension_rules_filters_by_dim():
    """dimension_rules('data_quality') 不应含 V-07 (V-07 是 quality 的)."""
    reg = SchemaRegistry.get()
    dq_rules = reg.dimension_rules("data_quality")
    dq_ids = {r.rule_id for r in dq_rules}
    # data_quality 应有 RC-009 / RC-010 / FN-01
    assert "RC-009" in dq_ids
    # V-07 是 quality 维度, 不该在 data_quality
    assert "V-07" not in dq_ids
    # 全部 dimension 字段都应是 'data_quality'
    for r in dq_rules:
        assert r.dimension == "data_quality"


# ============================================================
# 7. yaml 加载失败默认 raise SchemaRegistryError
# ============================================================


def test_yaml_load_failure_raises_by_default(tmp_path, monkeypatch):
    """workspace 指 tmp_path (不含 yaml) + 临时换 _BASE_DIR 让全局 yaml 也找不到 → raise."""
    # 让 dimensions._BASE_DIR 指到一个空目录, 这样全局 yaml 也找不到
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    monkeypatch.setattr("review.dimensions._BASE_DIR", str(empty_dir))
    monkeypatch.delenv("PECKER_SCHEMA_FALLBACK", raising=False)

    # 清 cache
    SchemaRegistry._cached_get.cache_clear()
    from review.dimensions import _cached_load
    _cached_load.cache_clear()

    with pytest.raises(SchemaRegistryError):
        SchemaRegistry.get(workspace=str(tmp_path))


# ============================================================
# 8. PECKER_SCHEMA_FALLBACK=1 时不 raise (返回空 registry)
# ============================================================


def test_yaml_load_failure_fallback_with_env(tmp_path, monkeypatch):
    """同上 yaml 缺失场景, 但 PECKER_SCHEMA_FALLBACK=1 → 返回空 registry, 不 raise."""
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    monkeypatch.setattr("review.dimensions._BASE_DIR", str(empty_dir))
    monkeypatch.setenv("PECKER_SCHEMA_FALLBACK", "1")

    SchemaRegistry._cached_get.cache_clear()
    from review.dimensions import _cached_load
    _cached_load.cache_clear()

    reg = SchemaRegistry.get(workspace=str(tmp_path))
    # 空 registry: all_rule_ids 应是空 frozenset
    assert reg.all_rule_ids() == frozenset()
    # rule_id_pattern 仍然返回 permissive 默认 (避免 caller 崩)
    assert reg.rule_id_pattern() == r"^(V|RC|EV|FN)-\d+$"


# ============================================================
# 9. cross_section 字段标对了 V-05 / V-06 / RC-009
# ============================================================


def test_cross_section_rules_marked():
    """V-05 / V-06 / RC-009 应被标 cross_section=True, 其余 (如 V-02 / V-03) 应为 False."""
    reg = SchemaRegistry.get()

    # 跨章节规则
    assert reg.get_rule("V-05").cross_section is True
    assert reg.get_rule("V-06").cross_section is True
    assert reg.get_rule("RC-009").cross_section is True

    # 非跨章节规则
    assert reg.get_rule("V-02").cross_section is False
    assert reg.get_rule("V-03").cross_section is False
    assert reg.get_rule("RC-004").cross_section is False


# ============================================================
# 10. reload() 清 cache
# ============================================================


def test_reload_clears_cache():
    """reload() 后 get() 不复用旧实例 (lru_cache 已 clear)."""
    a = SchemaRegistry.get()
    a.reload()
    b = SchemaRegistry.get()
    # reload 清 cache 后, b 是新构造的, 不复用 a
    assert a is not b


# ============================================================
# 额外: status 字段映射 (yaml 'inactive' → 'deprecated')
# ============================================================


def test_status_field_active_default():
    """yaml 没配 status 时默认 'active'."""
    reg = SchemaRegistry.get()
    rule = reg.get_rule("V-02")
    assert rule.status == "active"


def test_status_experimental_preserved():
    """yaml 有 status: experimental (如 EV-01) 应保留."""
    reg = SchemaRegistry.get()
    # EV-01 在 yaml 里标了 experimental
    rule = reg.get_rule("EV-01")
    assert rule.status == "experimental"


# ============================================================
# 额外: with_perf 骨架返回 view 实例
# ============================================================


def test_with_perf_returns_view_skeleton():
    """with_perf 骨架返回 SchemaRegistryWithPerf, precision_7d 暂返 None."""
    from review.schema_registry import SchemaRegistryWithPerf
    reg = SchemaRegistry.get()
    view = SchemaRegistryWithPerf(registry=reg, workspace="test-ws")
    assert isinstance(view, SchemaRegistryWithPerf)
    assert view.precision_7d("V-05") is None
    assert view.reject_rate_7d("V-05") is None
