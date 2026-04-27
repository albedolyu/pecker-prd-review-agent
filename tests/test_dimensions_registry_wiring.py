"""dimensions.py 内部接 SchemaRegistry 后的行为锁定 (step 3.2, 2026-04-27).

设计 doc: docs/schema_registry_design_2026_04_27.md Part 3 step 2.

step 3.2 关键改动:
1. dimensions._DEFAULT_REVIEW_DIMENSIONS / _DEFAULT_DIMENSION_WIKI_KEYWORDS 删了 (反模式根因).
2. load_review_dimensions() 内部走 SchemaRegistry, 不再返回硬编码 fallback.
3. yaml 加载失败行为变化 (老: silent fallback 硬编码; 新: 返回空 dict + warn,
   或 PECKER_STRICT_YAML=1 raise / PECKER_SCHEMA_FALLBACK=1 强制空 dict).

本测试锁死:
- 老 API 签名 0 break (load/get/get_wiki_keywords 仍返回 (dict, dict) / dict / dict).
- 内部确实走 SchemaRegistry (registry.all_rule_ids() ⊆ load_review_dimensions checklist).
- yaml 缺失场景:返回空 dict + warn (不再硬编码 fallback).
- _DEFAULT_REVIEW_DIMENSIONS / _DEFAULT_DIMENSION_WIKI_KEYWORDS 模块属性已删.
"""
from __future__ import annotations

import logging
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture(autouse=True)
def _clear_caches(monkeypatch):
    """每个 test 前清 dimensions / registry 双 cache, 防 yaml 路径污染."""
    from review import dimensions as dim_mod
    from review.schema_registry import SchemaRegistry

    dim_mod._cached_load.cache_clear()
    SchemaRegistry._cached_get.cache_clear()
    yield
    dim_mod._cached_load.cache_clear()
    SchemaRegistry._cached_get.cache_clear()


# ============================================================
# 1. 老 API 签名/返回结构不破坏
# ============================================================


def test_load_review_dimensions_returns_tuple_of_dicts():
    """load_review_dimensions(workspace=None) 仍返回 (dimensions_dict, wiki_keywords_dict)."""
    from review.dimensions import load_review_dimensions

    result = load_review_dimensions(workspace=None)
    assert isinstance(result, tuple)
    assert len(result) == 2
    dims, wiki = result
    assert isinstance(dims, dict)
    assert isinstance(wiki, dict)


def test_get_review_dimensions_returns_dict_with_expected_dims():
    """get_review_dimensions() 仍返回 dict, key 是 4 个维度 codename."""
    from review.dimensions import get_review_dimensions

    dims = get_review_dimensions()
    assert isinstance(dims, dict)
    # 4 个维度都在 (来自 yaml, 不是硬编码)
    for k in ("structure", "quality", "ai_coding", "data_quality"):
        assert k in dims, f"{k} 维度缺, 实际 {list(dims.keys())}"


def test_dim_dict_shape_compat():
    """dim dict 仍是老 shape: name/codename/rules/checklist/model 都有."""
    from review.dimensions import get_review_dimensions

    dims = get_review_dimensions()
    structure = dims["structure"]
    assert "name" in structure
    assert "codename" in structure
    assert "rules" in structure
    assert "checklist" in structure
    assert "model" in structure
    # checklist 仍是 list of {rule_id, name}
    for item in structure["checklist"]:
        assert "rule_id" in item
        assert "name" in item


# ============================================================
# 2. 内部确实接 SchemaRegistry (rule_id 集合一致)
# ============================================================


def test_dimensions_rule_ids_subset_of_registry():
    """load_review_dimensions 出的 rule_id 应是 SchemaRegistry.all_rule_ids() 的子集.

    Registry 里可能含 deprecated/disabled rule, 但 dimensions checklist 不能含 registry 不知道的 rule_id.
    """
    from review.dimensions import load_review_dimensions
    from review.schema_registry import SchemaRegistry

    dims, _ = load_review_dimensions(workspace=None)
    reg = SchemaRegistry.get()
    reg_ids = reg.all_rule_ids()

    dim_ids = set()
    for dim in dims.values():
        for item in dim["checklist"]:
            dim_ids.add(item["rule_id"])

    assert dim_ids, "dimensions 维度 checklist 至少要有 1 条 rule"
    missing = dim_ids - reg_ids
    assert not missing, f"dimensions checklist 含 registry 不知道的 rule_id: {missing}"


def test_yaml_loaded_rules_include_v_rc_ev_fn():
    """yaml 真路径加载后, rule_id 应覆盖 V/RC/EV/FN 4 前缀 (真 yaml 已有).

    替代 test_worker_schema_enum_fn.py 里直接 import _DEFAULT_REVIEW_DIMENSIONS 的检查.
    """
    from review.dimensions import load_review_dimensions

    dims, _ = load_review_dimensions(workspace=None)
    all_ids = set()
    for dim in dims.values():
        for item in dim["checklist"]:
            all_ids.add(item["rule_id"])

    # 应能在 yaml 里看到至少一个 EV / FN — 否则 P0-B 又漂了
    assert any(rid.startswith("V-") for rid in all_ids), "yaml 应含 V- 前缀"
    assert any(rid.startswith("RC-") for rid in all_ids), "yaml 应含 RC- 前缀"
    assert any(rid.startswith("EV-") for rid in all_ids), "yaml 应含 EV- 前缀 (P0-B 防回归)"
    assert any(rid.startswith("FN-") for rid in all_ids), "yaml 应含 FN- 前缀 (P0-B 防回归)"


# ============================================================
# 3. _DEFAULT_REVIEW_DIMENSIONS / _DEFAULT_DIMENSION_WIKI_KEYWORDS 已删
# ============================================================


def test_default_review_dimensions_symbol_removed():
    """step 3.2: _DEFAULT_REVIEW_DIMENSIONS 模块属性应已删.

    这是 P0-B 暴露的反模式根因 — 硬编码 fallback 与 yaml 漂移.
    """
    from review import dimensions as dim_mod

    assert not hasattr(dim_mod, "_DEFAULT_REVIEW_DIMENSIONS"), (
        "_DEFAULT_REVIEW_DIMENSIONS 应已删 (step 3.2 反模式清理). "
        "如果还需要 fallback, 请通过 SchemaRegistry + PECKER_SCHEMA_FALLBACK=1 拿空 registry."
    )


def test_default_dimension_wiki_keywords_symbol_removed():
    """同上, _DEFAULT_DIMENSION_WIKI_KEYWORDS 也应已删."""
    from review import dimensions as dim_mod

    assert not hasattr(dim_mod, "_DEFAULT_DIMENSION_WIKI_KEYWORDS"), (
        "_DEFAULT_DIMENSION_WIKI_KEYWORDS 应已删 (step 3.2)."
    )


# ============================================================
# 4. yaml 缺失行为: 默认返回空 dict + warn (不 raise)
# ============================================================


def test_yaml_missing_returns_empty_with_warn(tmp_path, monkeypatch, caplog):
    """workspace 指空目录 + 全局 _BASE_DIR 指空目录 + 没设 STRICT/FALLBACK env →
    返回 (空 dict, 空 dict) + log warn. 老语义是 silent 硬编码 fallback,
    新语义是空 + warn — 这是 step 3.2 的破坏性变化, 必须显式 log.
    """
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    monkeypatch.setattr("review.dimensions._BASE_DIR", str(empty_dir))
    monkeypatch.delenv("PECKER_STRICT_YAML", raising=False)
    monkeypatch.delenv("PECKER_SCHEMA_FALLBACK", raising=False)

    from review.dimensions import load_review_dimensions

    with caplog.at_level(logging.WARNING):
        dims, wiki = load_review_dimensions(workspace=str(tmp_path))

    # 新语义: yaml 找不到时, dimensions 返回空, 不再含硬编码兜底
    assert isinstance(dims, dict)
    assert isinstance(wiki, dict)
    assert dims == {}, f"yaml 缺时应返回空 dict, 实际 {list(dims.keys())}"
    assert wiki == {}
    # 必须 warn (省得 silent 漂移)
    msgs = " ".join(r.getMessage() for r in caplog.records)
    assert "schema" in msgs.lower() or "yaml" in msgs.lower() or "registry" in msgs.lower(), (
        f"yaml 缺时应至少 log 1 条 warn, 实际记录: {msgs}"
    )


def test_yaml_missing_with_strict_raises(tmp_path, monkeypatch):
    """PECKER_STRICT_YAML=1 时 yaml 缺失应 raise (老行为保留).

    SchemaRegistryError 也算 — caller 看到的是底层报错, 不再 silent fallback.
    """
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    monkeypatch.setattr("review.dimensions._BASE_DIR", str(empty_dir))
    monkeypatch.setenv("PECKER_STRICT_YAML", "1")
    monkeypatch.delenv("PECKER_SCHEMA_FALLBACK", raising=False)

    from review.dimensions import load_review_dimensions
    from review.schema_registry import SchemaRegistryError

    # yaml 缺 + strict → registry raise → dimensions.py 透传或转 ValueError 都接受
    with pytest.raises((SchemaRegistryError, ValueError, FileNotFoundError, OSError)):
        load_review_dimensions(workspace=str(tmp_path))


def test_yaml_missing_with_fallback_env_returns_empty(tmp_path, monkeypatch):
    """PECKER_SCHEMA_FALLBACK=1 时 yaml 缺失返回 (空 dict, 空 dict),
    不是返回硬编码 _DEFAULT_REVIEW_DIMENSIONS (那个已删).

    这是与 step 3.1 SchemaRegistry 行为对齐的兜底逃生口.
    """
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    monkeypatch.setattr("review.dimensions._BASE_DIR", str(empty_dir))
    monkeypatch.delenv("PECKER_STRICT_YAML", raising=False)
    monkeypatch.setenv("PECKER_SCHEMA_FALLBACK", "1")

    from review.dimensions import load_review_dimensions

    dims, wiki = load_review_dimensions(workspace=str(tmp_path))
    assert dims == {}
    assert wiki == {}


# ============================================================
# 5. parallel_review.py 不再 re-export 已删 symbol
# ============================================================


def test_parallel_review_does_not_export_default_dimensions():
    """parallel_review.py 历史 re-export _DEFAULT_REVIEW_DIMENSIONS, step 3.2 删了.

    单测确保 import parallel_review 不崩 (没残留漏改的 import).
    """
    import parallel_review  # noqa: F401  (模块加载即测试)

    # 不应再 re-export 这俩 symbol
    assert not hasattr(parallel_review, "_DEFAULT_REVIEW_DIMENSIONS")
    assert not hasattr(parallel_review, "_DEFAULT_DIMENSION_WIKI_KEYWORDS")


# ============================================================
# 6. wiki_keywords 仍由 yaml 提供 (不再有硬编码 fallback)
# ============================================================


def test_wiki_keywords_from_yaml_or_empty_list():
    """每个维度的 wiki_keywords 应来自 yaml 配置, 没配则返回空 list (不再硬编码 default).

    若 wiki yaml 没配, 之前老 fallback 给 _DEFAULT_DIMENSION_WIKI_KEYWORDS 的中文关键词.
    新语义: yaml 配则用 yaml, 没配则空 list. 真 yaml 已配 (P0-B 同时加进去了).
    """
    from review.dimensions import get_wiki_keywords

    wiki = get_wiki_keywords()
    assert isinstance(wiki, dict)
    # 4 个维度都应有 entry (yaml 实际有配)
    for k in ("structure", "quality", "ai_coding", "data_quality"):
        assert k in wiki, f"{k} 缺 wiki_keywords entry"
        assert isinstance(wiki[k], list)
