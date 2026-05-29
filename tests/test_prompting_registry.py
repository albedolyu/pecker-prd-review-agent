"""review/prompting ↔ SchemaRegistry 接通单测 (step 3.5).

参考 docs/schema_registry_design_2026_04_27.md step 3.5.

设计意图:
- 替代 prompting.py 内 2 处散落 ``re.findall(r"(?:RC|V|EV|FN)-\\d+", text)`` 硬编码.
- B 类格式铁律错误提示文本动态从 registry 拉所有合法 prefix + sample, 加新前缀
  时不再需要手动改"扩 EV-/FN-"这种文案 (P0-B 修法的下一代).
- 防 P0-B 漂移再现 — registry 加 V-13 / DQ- 时 prompting 自动同步.

覆盖:
1. _build_real_refs_section 错误提示动态含 registry.valid_prefixes() 全部前缀
2. _build_real_refs_section 含 sample rule_id (从 registry.sample_rule_ids() 取)
3. registry 加新前缀 (V-13 / DQ-) 时错误提示自动列出
4. _build_feedback_section 用 registry 抽 dim_rule_ids
5. anti-corruption: 源码不再含 ``(?:RC|V|EV|FN)-\\d+`` 硬编码
6. valid_prefixes / sample_rule_ids 接口行为
"""

from __future__ import annotations

import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from review.prompting import (
    _b_class_format_hint,
    _build_real_refs_section,
    _extract_rule_ids_via_registry,
)
from review.schema_registry import RuleDef, SchemaRegistry


@pytest.fixture(autouse=True)
def _clear_registry_cache():
    """清 registry cache 防 test 互相污染."""
    SchemaRegistry._cached_get.cache_clear()
    from review.dimensions import _cached_load
    _cached_load.cache_clear()
    yield
    SchemaRegistry._cached_get.cache_clear()
    _cached_load.cache_clear()


# ============================================================
# 1. SchemaRegistry.valid_prefixes / sample_rule_ids 接口
# ============================================================


def test_valid_prefixes_from_real_yaml():
    """全局 yaml 应给出 EV / FN / RC / V 4 个前缀."""
    reg = SchemaRegistry.get()
    prefixes = reg.valid_prefixes()
    assert "V" in prefixes
    assert "RC" in prefixes
    assert "EV" in prefixes
    assert "FN" in prefixes
    # 字母序
    assert list(prefixes) == sorted(prefixes)


def test_valid_prefixes_empty_registry_has_default():
    """空 registry 应返 permissive 默认 (避免 caller 拼出空文本)."""
    empty_reg = SchemaRegistry(rules={}, dimensions=())
    assert empty_reg.valid_prefixes() == ("EV", "FN", "RC", "V")


def test_sample_rule_ids_one_per_prefix():
    """sample_rule_ids 应每个前缀挑首个 rule_id."""
    reg = SchemaRegistry.get()
    samples = reg.sample_rule_ids(n=4)
    # 4 前缀应都有代表
    sampled_prefixes = {s.split("-")[0] for s in samples}
    assert len(samples) == 4
    assert sampled_prefixes == {"V", "RC", "EV", "FN"}


def test_sample_rule_ids_n_limit():
    """sample_rule_ids(n=2) 只返 2 个."""
    reg = SchemaRegistry.get()
    samples = reg.sample_rule_ids(n=2)
    assert len(samples) == 2


def test_sample_rule_ids_empty_registry():
    """空 registry 返空 tuple."""
    empty_reg = SchemaRegistry(rules={}, dimensions=())
    assert empty_reg.sample_rule_ids() == ()


# ============================================================
# 2. _b_class_format_hint 动态从 registry 拉前缀 + sample
# ============================================================


def test_b_class_format_hint_lists_all_4_prefixes():
    """错误提示文本应含 EV / FN / RC / V 全部 4 前缀 (动态从 registry 拉)."""
    hint = _b_class_format_hint()
    assert "V-\\d+" in hint
    assert "RC-\\d+" in hint
    assert "EV-\\d+" in hint
    assert "FN-\\d+" in hint
    # 不应再写死"扩 EV-/FN-"这种文案
    assert "B 类" in hint


def test_b_class_format_hint_includes_sample():
    """错误提示文本应含 sample 例子 — 让模型更直观."""
    hint = _b_class_format_hint()
    # 至少含一个真实 rule_id 样例
    import re as re_mod
    samples_in_hint = re_mod.findall(r"(?:V|RC|EV|FN)-\d+", hint)
    assert len(samples_in_hint) >= 1, f"hint 应含 sample rule_id, 实际: {hint}"


def test_worker_prompt_spells_out_conservative_trigger_boundary():
    """Worker prompt 应把 fire_when 不确定和空 items 出口说透，减少硬凑问题."""
    from review.prompting import _WORKER_SHARED_RULES

    assert "不确定是否触发 fire_when 时按不触发处理" in _WORKER_SHARED_RULES
    assert "空 items 不是失败" in _WORKER_SHARED_RULES
    assert "每条 finding 必须能定位到 PRD 中的具体位置" in _WORKER_SHARED_RULES
    assert "不要把无关业务场景的 wiki" in _WORKER_SHARED_RULES


# ============================================================
# 3. registry 加新前缀 → 错误提示自动列出 (单点 SoT 价值)
# ============================================================


def test_b_class_format_hint_auto_includes_new_prefix():
    """模拟 yaml 加 DQ- 新前缀, 错误提示文本自动列出 ``DQ-\\d+``, 不需要改代码."""
    fake_rules = {
        "V-02": RuleDef(rule_id="V-02", dimension="structure", name="内容自洽",
                        description="", status="active"),
        "DQ-01": RuleDef(rule_id="DQ-01", dimension="data_quality",
                         name="假新前缀", description="", status="experimental"),
    }
    fake_registry = SchemaRegistry(rules=fake_rules, dimensions=("structure", "data_quality"))

    with patch.object(SchemaRegistry, "get", return_value=fake_registry):
        hint = _b_class_format_hint(workspace="any")
        # DQ- 新前缀应出现在 hint 里
        assert "DQ-\\d+" in hint
        # V- 也应保留
        assert "V-\\d+" in hint
        # 没有 EV/FN/RC (fake registry 没注册)
        assert "EV-\\d+" not in hint
        assert "FN-\\d+" not in hint


# ============================================================
# 4. _build_real_refs_section 用动态 hint
# ============================================================


def test_build_real_refs_section_uses_dynamic_hint(tmp_path):
    """_build_real_refs_section 应注入 _b_class_format_hint 输出, 不再写死老文案."""
    # 造最小 workspace: review-rules + wiki
    rules_dir = tmp_path / "review-rules"
    rules_dir.mkdir()
    (rules_dir / "all-rules.md").write_text(
        "## V-02 内容自洽\n## RC-009 物理表\n## EV-01 验收\n## FN-01 字段\n",
        encoding="utf-8",
    )
    wiki_dir = tmp_path / "wiki"
    wiki_dir.mkdir()

    section = _build_real_refs_section(str(tmp_path))
    # 错误提示文本应来自 _b_class_format_hint, 含 4 前缀
    assert "V-\\d+" in section
    assert "RC-\\d+" in section
    assert "EV-\\d+" in section
    assert "FN-\\d+" in section


def test_build_real_refs_section_with_new_prefix(tmp_path):
    """workspace 内含 V-13 新规则时, refs section 应自动列入 (走 registry pattern)."""
    rules_dir = tmp_path / "review-rules"
    rules_dir.mkdir()
    (rules_dir / "rules.md").write_text(
        "## V-02 \n## V-13 假新规则\n",
        encoding="utf-8",
    )

    section = _build_real_refs_section(str(tmp_path))
    # V-02 + V-13 都应出现在 "可用规则编号" 列表
    assert "V-02" in section
    assert "V-13" in section


# ============================================================
# 5. _extract_rule_ids_via_registry 单点入口
# ============================================================


def test_extract_rule_ids_via_registry_returns_list():
    """文本里的 rule_id 应被抽出成 list."""
    text = "V-02 / RC-009 / EV-01 / FN-01 都要看"
    ids = _extract_rule_ids_via_registry(text)
    assert "V-02" in ids
    assert "RC-009" in ids
    assert "EV-01" in ids
    assert "FN-01" in ids


def test_extract_rule_ids_via_registry_skips_unknown():
    """伪前缀 (DQ-XX / ZZ-99) 不在 registry → 不被抽."""
    text = "DQ-XX 不存在 / V-02 真规则"
    ids = _extract_rule_ids_via_registry(text)
    assert "V-02" in ids
    assert "DQ-XX" not in ids


def test_extract_rule_ids_via_registry_empty():
    """空文本返空 list."""
    assert _extract_rule_ids_via_registry("") == []
    assert _extract_rule_ids_via_registry(None) == []


# ============================================================
# 6. _build_feedback_section 用 registry 抽 dim_rule_ids
# ============================================================


def test_feedback_section_uses_registry_for_dim_rule_ids(tmp_path, monkeypatch):
    """_build_feedback_section 抽 dim_rule_ids 应走 registry pattern."""
    from review.prompting import _build_feedback_section

    fake_dims = {
        "data_quality": {
            "rules": "## RC-009 物理表 / FN-01 字段类型 / DQ-01 假前缀",
        }
    }
    fake_history = {
        "RC-009": {"rejection_rate": 0.5, "name": "物理表"},
        "FN-01": {"rejection_rate": 0.5, "name": "字段类型"},
        "DQ-01": {"rejection_rate": 0.5, "name": "假前缀"},
    }

    # 跑一次默认 registry (DQ- 不在), DQ-01 应被忽略
    section = _build_feedback_section(
        "data_quality", rule_perf_history=fake_history, dimensions=fake_dims,
    )
    # RC-009 / FN-01 在真 registry 应出现
    assert "RC-009" in section
    assert "FN-01" in section
    # DQ-01 不在真 registry → registry 不识别 → 不出现在 dim_rule_ids
    # (如果出现说明走了硬编码 regex, 失败)
    assert "DQ-01" not in section


# ============================================================
# 7. anti-corruption: 源码不再含硬编码 rule_id regex
# ============================================================


def test_prompting_no_hardcoded_rule_id_findall():
    """grep prompting.py 源码, 确保 ``re.findall(r"(?:RC|V|EV|FN)-\\d+", ...)`` 已替换.

    防 P0-B 漂移再现.
    """
    import re as re_mod

    src_path = os.path.join(
        os.path.dirname(__file__), "..", "review", "prompting.py"
    )
    with open(src_path, "r", encoding="utf-8") as f:
        src = f.read()

    # 不允许 re.findall/match/search/compile 上含 (?:RC|V|EV|FN) 字面量
    forbidden = re_mod.findall(
        r're\.(?:findall|match|search|compile|sub|split)\([^)]*\(\?:RC\|V\|EV\|FN\)[^)]*\)',
        src,
    )
    assert not forbidden, (
        f"prompting.py 仍含硬编码 rule_id regex 调用: {forbidden}. "
        "应改用 _extract_rule_ids_via_registry / _b_class_format_hint."
    )


def test_prompting_no_hardcoded_b_class_text():
    """grep prompting.py 源码, 确认 'RC-\\d+ / V-\\d+ / EV-\\d+ / FN-\\d+' 硬列举已替换.

    P0-B 落地版本是 ``"`RC-\\d+` / `V-\\d+` / `EV-\\d+` / `FN-\\d+`"`` 这种手列文案.
    step 3.5 应改成动态从 registry 拼.
    """
    src_path = os.path.join(
        os.path.dirname(__file__), "..", "review", "prompting.py"
    )
    with open(src_path, "r", encoding="utf-8") as f:
        src = f.read()

    # 老的 P0-B 硬列文案: "包含 `RC-\\d+` / `V-\\d+` / `EV-\\d+` / `FN-\\d+`"
    forbidden_text = "`RC-\\d+` / `V-\\d+` / `EV-\\d+` / `FN-\\d+`"
    assert forbidden_text not in src, (
        f"prompting.py 仍含老 P0-B 硬列前缀文案 {forbidden_text!r}. "
        "应改用 _b_class_format_hint(workspace) 动态拼."
    )
