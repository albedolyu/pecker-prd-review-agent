"""review_fixer ↔ SchemaRegistry 接通单测 (step 3.5).

参考 docs/schema_registry_design_2026_04_27.md step 3.5.

设计意图:
- 替代 review_fixer.py 内 ``r"(?:RC-\\d+|V-\\d+|BMAD[\\s-]*V-\\d+)"`` 硬编码.
- 加新 yaml 规则前缀 (DQ-/V-13 等) 时 review_fixer 自动同步, 防 P0-B 漂移再现.
- 上一次加 EV/FN 漏改 review_fixer 让 EV/FN evidence_type 推断错失.

覆盖:
1. infer_evidence_type 用 registry pattern 抽 B 类 (V/RC/EV/FN 4 前缀)
2. registry 加新前缀 (V-13) → infer 自动识别
3. registry 不识别的伪前缀 (DQ-XX) → 不判 B 类
4. fix_review_items 透传 workspace 给 infer
5. anti-corruption: 源码不再含硬编码 rule_id regex 字面量
"""

from __future__ import annotations

import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from review.schema_registry import RuleDef, SchemaRegistry
from review_fixer import infer_evidence_type


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
# 1. infer_evidence_type 走 registry pattern (4 前缀全识别)
# ============================================================


def test_infer_evidence_type_b_class_v_prefix():
    """V-XX 应被识别为 B 类."""
    assert infer_evidence_type("依据 V-02 内容自洽") == "B"


def test_infer_evidence_type_b_class_rc_prefix():
    """RC-XXX 应被识别为 B 类."""
    assert infer_evidence_type("参考 RC-009 物理表定义") == "B"


def test_infer_evidence_type_b_class_ev_prefix():
    """EV-XX 应被识别为 B 类 — P0-B 落地行为不变 (registry 后无需手列)."""
    assert infer_evidence_type("见 EV-01 验收标准") == "B"


def test_infer_evidence_type_b_class_fn_prefix():
    """FN-XX 应被识别为 B 类 — P0-B 落地行为不变."""
    assert infer_evidence_type("对应 FN-01 字段类型") == "B"


def test_infer_evidence_type_b_class_bmad_compat():
    """BMAD V-XX 写法仍兼容 (向后兼容 worker 老输出)."""
    assert infer_evidence_type("BMAD V-02 内容自洽") == "B"


# ============================================================
# 2. A 类 / C 类不变
# ============================================================


def test_infer_evidence_type_a_class_takes_priority():
    """[[页面]] 引用 + 规则号同时出现, A 类优先."""
    assert infer_evidence_type("依据 [[wiki 页面]] 和 V-02") == "A"


def test_infer_evidence_type_c_class_keywords():
    """竞品 / 行业 / 惯例 关键词应触发 C 类."""
    assert infer_evidence_type("参考竞品产品 X 的做法") == "C"
    assert infer_evidence_type("行业惯例如此") == "C"


def test_infer_evidence_type_empty():
    """空内容返空字符串."""
    assert infer_evidence_type("") == ""
    assert infer_evidence_type(None) == ""


# ============================================================
# 3. registry 加新前缀 → infer 自动识别 (单点 SoT 价值)
# ============================================================


def test_new_rule_prefix_added_in_registry_auto_recognized():
    """模拟 yaml 加 V-13 / DQ-XX 新规则, infer_evidence_type 不需要改代码就能识别 B 类."""
    fake_rules = {
        "V-02": RuleDef(rule_id="V-02", dimension="structure", name="内容自洽",
                        description="", status="active"),
        "V-13": RuleDef(rule_id="V-13", dimension="structure", name="新加规则",
                        description="", status="experimental"),
        "DQ-01": RuleDef(rule_id="DQ-01", dimension="data_quality",
                         name="假新前缀 (test only)", description="",
                         status="experimental"),
    }
    fake_registry = SchemaRegistry(rules=fake_rules, dimensions=("structure", "data_quality"))

    with patch.object(SchemaRegistry, "get", return_value=fake_registry):
        # V-13 在 fake registry, 应识别为 B
        assert infer_evidence_type("依据 V-13 新规则", workspace="any") == "B"
        # DQ-01 在 fake registry, 应识别为 B (前缀来自 registry, 不再硬列)
        assert infer_evidence_type("依据 DQ-01 数据质量", workspace="any") == "B"


# ============================================================
# 4. registry 不识别的伪前缀 → 不判 B 类
# ============================================================


def test_unknown_prefix_not_b_class():
    """伪前缀 ZZ-99 / AC-XX 不在 registry, 不应识别为 B 类."""
    # ZZ-99 不含 wiki 引用 + 不含竞品关键词 → 应返空字符串 (不是 B 也不是 A/C)
    result = infer_evidence_type("依据 ZZ-99 不存在的规则")
    assert result == ""


# ============================================================
# 5. anti-corruption: 源码不再含硬编码 rule_id regex 字面量
# ============================================================


def test_review_fixer_no_hardcoded_rule_id_regex():
    """grep review_fixer.py 源码, 确认硬编码 ``(?:RC-\\d+|V-\\d+|...)`` 已替换为 registry helper.

    防 P0-B 漂移再现 — 加新 prefix 时漏改 review_fixer.
    白名单允许 docstring 里的描述性文本, 但 re.* 函数调用上不能含此字面量.
    """
    import re as re_mod

    src_path = os.path.join(
        os.path.dirname(__file__), "..", "review_fixer.py"
    )
    with open(src_path, "r", encoding="utf-8") as f:
        src = f.read()

    forbidden = re_mod.findall(
        r're\.(?:findall|match|search|compile|sub|split)\([^)]*\(\?:RC-\\d\+\|V-\\d\+[^)]*\)',
        src,
    )
    assert not forbidden, (
        f"review_fixer.py 仍含硬编码 rule_id regex 调用: {forbidden}. "
        "应改用 _b_class_rule_id_regex(workspace) → SchemaRegistry."
    )


# ============================================================
# 6. fix_review_items 透传 workspace 给 infer (集成)
# ============================================================


def test_fix_review_items_passes_workspace_to_infer(tmp_path, monkeypatch):
    """fix_review_items 应把 workspace 传给 infer_evidence_type, 不丢上下文."""
    from review_fixer import fix_review_items

    # 准备空 workspace (verify_evidence 会因 wiki/rules-dir 不存在走 unchecked, 不影响本测试)
    items = [
        {
            "id": "1",
            "evidence_type": "",  # 强制走 infer 分支
            "evidence_content": "依据 V-02 内容自洽",
        }
    ]

    # patch infer_evidence_type 看 workspace 是否被传进来
    captured = {}

    def fake_infer(ev_content, workspace=None):
        captured["workspace"] = workspace
        return "B"

    monkeypatch.setattr("review_fixer.infer_evidence_type", fake_infer)

    # cuckoo_scorer.verify_evidence 在空 workspace 会 raise, 触发 except 分支也 OK
    fix_review_items(items, str(tmp_path))

    # 必须传到 — 防 review_fixer 走全局 registry 用错 workspace 规则
    assert captured["workspace"] == str(tmp_path)
