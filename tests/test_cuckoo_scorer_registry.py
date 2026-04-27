"""cuckoo_scorer ↔ SchemaRegistry 接通单测 (step 3.5).

参考 docs/schema_registry_design_2026_04_27.md step 3.5.

设计意图:
- cuckoo_scorer.py 散落 5 处硬编码 ``re.findall(r"(RC-\\d+|V-\\d+)", text)`` 替换为 registry SoT.
- 加新 yaml 规则前缀 (V-13 / EV-XX / FN-XX) 时 cuckoo_scorer 自动同步, 防 P0-B 漂移.
- _extract_rule_id_from_item 之前漏 EV/FN — 现在走 registry pattern 自动覆盖.

覆盖:
1. _verify_type_b 用 registry pattern 抽 rule_id (4 前缀)
2. _extract_rule_id_from_item 用 registry pattern (覆盖 EV/FN, 之前漏)
3. _verify_unknown_type 用 registry 判 B 类
4. calculate_rule_coverage_matrix 用 registry 抽 rules
5. anti-corruption: 源码不再含硬编码 ``(RC-\\d+|V-\\d+)`` 字面量
"""

from __future__ import annotations

import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from cuckoo_scorer import (
    _extract_rule_id_from_item,
    _extract_rule_ids_via_registry,
    _verify_type_b,
    _verify_unknown_type,
    _workspace_from_rules_dir,
    calculate_rule_coverage_matrix,
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


@pytest.fixture
def fake_workspace(tmp_path):
    """造最小 workspace: review-rules 含 V-02/RC-009/EV-01/FN-01."""
    rules_dir = tmp_path / "review-rules"
    rules_dir.mkdir()
    (rules_dir / "all.md").write_text(
        "## V-02 内容自洽\n"
        "## RC-009 物理表定义\n"
        "## EV-01 验收标准\n"
        "## FN-01 字段类型\n",
        encoding="utf-8",
    )
    return tmp_path


# ============================================================
# 1. _workspace_from_rules_dir 反推
# ============================================================


def test_workspace_from_rules_dir_basic():
    """rules_dir = '/ws/review-rules' 应反推 '/ws'."""
    assert _workspace_from_rules_dir("/ws/review-rules") == "/ws"


def test_workspace_from_rules_dir_trailing_sep():
    """带尾分隔符的 path 也应正确反推."""
    assert _workspace_from_rules_dir("/ws/review-rules/") == "/ws"


def test_workspace_from_rules_dir_none():
    """None 返 None."""
    assert _workspace_from_rules_dir(None) is None
    assert _workspace_from_rules_dir("") is None


# ============================================================
# 2. _verify_type_b 用 registry 抽 rule_id (4 前缀)
# ============================================================


def test_verify_type_b_recognizes_v_prefix(fake_workspace):
    """B 类 evidence 含 V-02 应被识别."""
    rules_dir = str(fake_workspace / "review-rules")
    ok, reason = _verify_type_b("依据 V-02 内容自洽", rules_dir)
    assert ok is True
    assert "V-02" in reason


def test_verify_type_b_recognizes_ev_prefix(fake_workspace):
    """EV-01 应被识别 — P0-B 落地行为不变, registry 后无需手列."""
    rules_dir = str(fake_workspace / "review-rules")
    ok, reason = _verify_type_b("见 EV-01 验收标准", rules_dir)
    assert ok is True


def test_verify_type_b_recognizes_fn_prefix(fake_workspace):
    """FN-01 应被识别."""
    rules_dir = str(fake_workspace / "review-rules")
    ok, reason = _verify_type_b("对应 FN-01 字段类型", rules_dir)
    assert ok is True


def test_verify_type_b_no_rule_ref_returns_failed(fake_workspace):
    """不含合法 rule_id 时返 (False, 含 V-XX/RC-XXX/EV-XX/FN-XX 的提示)."""
    rules_dir = str(fake_workspace / "review-rules")
    ok, reason = _verify_type_b("没有规则号的依据", rules_dir)
    assert ok is False
    # 错误提示应含至少一种前缀提示
    assert any(p in reason for p in ["V-XX", "RC-XXX", "EV-XX", "FN-XX"])


def test_verify_type_b_unknown_prefix_rejected(fake_workspace):
    """伪前缀 DQ-XX 不在 registry → 视为无 rule_id, 返 failed."""
    rules_dir = str(fake_workspace / "review-rules")
    ok, reason = _verify_type_b("依据 DQ-XX 假规则", rules_dir)
    # registry 不识别 DQ → rule_refs 空 → 走 "未包含有效规则号" 分支
    assert ok is False


def test_verify_type_b_bmad_compat(fake_workspace):
    """BMAD V-XX 写法仍兼容."""
    rules_dir = str(fake_workspace / "review-rules")
    ok, reason = _verify_type_b("BMAD V-02 内容自洽", rules_dir)
    assert ok is True


# ============================================================
# 3. _extract_rule_id_from_item 用 registry (覆盖 EV/FN)
# ============================================================


def test_extract_rule_id_from_item_v_prefix():
    """rule_id 字段 = 'V-02' 应被抽出."""
    item = {"rule_id": "V-02"}
    assert _extract_rule_id_from_item(item) == "V-02"


def test_extract_rule_id_from_item_ev_prefix():
    """rule_id 字段 = 'EV-01' 应被抽出 (老 hardcoded regex 漏 EV-, 现走 registry 应识别)."""
    item = {"rule_id": "EV-01"}
    # 走默认全局 registry, EV-01 在 yaml 里
    assert _extract_rule_id_from_item(item) == "EV-01"


def test_extract_rule_id_from_item_fn_prefix():
    """rule_id 字段 = 'FN-01' 应被抽出 (老 hardcoded 漏)."""
    item = {"rule_id": "FN-01"}
    assert _extract_rule_id_from_item(item) == "FN-01"


def test_extract_rule_id_from_item_evidence_fallback():
    """rule_id 字段为空时, 从 evidence_content 兜底抽取."""
    item = {"rule_id": "", "evidence_content": "依据 RC-009 物理表"}
    assert _extract_rule_id_from_item(item) == "RC-009"


def test_extract_rule_id_from_item_unknown_returns_unknown():
    """完全无规则号时返 'UNKNOWN'."""
    item = {"rule_id": "", "evidence_content": "随便写写"}
    assert _extract_rule_id_from_item(item) == "UNKNOWN"


# ============================================================
# 4. _verify_unknown_type 用 registry 判 B 类
# ============================================================


def test_verify_unknown_type_infers_b_via_registry(fake_workspace):
    """未标注类型, evidence 含 V-02 应自动推断为 B 类."""
    rules_dir = str(fake_workspace / "review-rules")
    wiki_dir = str(fake_workspace / "wiki")
    item = {"raw_text": "", "evidence_content": "依据 V-02 内容自洽"}
    ok, reason = _verify_unknown_type("依据 V-02 内容自洽", wiki_dir, rules_dir, item)
    assert "[自动推断为 B 类]" in reason


def test_verify_unknown_type_infers_b_for_ev_prefix(fake_workspace):
    """EV- 前缀也应触发 B 类自动推断 (老 hardcoded regex 漏 EV/FN)."""
    rules_dir = str(fake_workspace / "review-rules")
    wiki_dir = str(fake_workspace / "wiki")
    item = {"raw_text": "", "evidence_content": "见 EV-01"}
    ok, reason = _verify_unknown_type("见 EV-01", wiki_dir, rules_dir, item)
    assert "[自动推断为 B 类]" in reason


# ============================================================
# 5. calculate_rule_coverage_matrix 用 registry 抽 rules
# ============================================================


def test_calculate_rule_coverage_matrix_recognizes_all_4_prefixes(fake_workspace):
    """coverage matrix 抽 review-rules 应识别 4 前缀, 而非只有 RC/V."""
    review_items = [
        {"rule_id": "V-02", "evidence_content": "", "dimension": "structure"},
        {"rule_id": "EV-01", "evidence_content": "", "dimension": "structure"},
    ]
    matrix = calculate_rule_coverage_matrix(review_items, str(fake_workspace))
    # all_rules 应含 4 个 (V-02 / RC-009 / EV-01 / FN-01)
    assert matrix["total_rules"] == 4
    # V-02 / EV-01 都应在 covered
    assert "V-02" in matrix["covered_rule_ids"]
    assert "EV-01" in matrix["covered_rule_ids"]
    # FN-01 / RC-009 在 uncovered
    assert "FN-01" in matrix["uncovered_rule_ids"]
    assert "RC-009" in matrix["uncovered_rule_ids"]


# ============================================================
# 6. registry 加新前缀 → cuckoo_scorer 自动识别 (单点 SoT 价值)
# ============================================================


def test_new_rule_prefix_in_registry_auto_recognized():
    """模拟 yaml 加 DQ- 新前缀, _extract_rule_ids_via_registry 自动识别."""
    fake_rules = {
        "V-02": RuleDef(rule_id="V-02", dimension="structure", name="内容自洽",
                        description="", status="active"),
        "DQ-01": RuleDef(rule_id="DQ-01", dimension="data_quality",
                         name="假新前缀", description="", status="experimental"),
    }
    fake_registry = SchemaRegistry(rules=fake_rules, dimensions=("structure", "data_quality"))

    with patch.object(SchemaRegistry, "get", return_value=fake_registry):
        ids = _extract_rule_ids_via_registry("DQ-01 + V-02 + EV-99", workspace="any")
        # DQ-01 应被识别 (registry 已注册前缀)
        assert "DQ-01" in ids
        assert "V-02" in ids
        # EV-99 (前缀不在 fake registry) → 不识别
        assert "EV-99" not in ids


# ============================================================
# 7. anti-corruption: 源码不再含硬编码 rule_id regex
# ============================================================


def test_cuckoo_scorer_no_hardcoded_rule_id_regex():
    """grep cuckoo_scorer.py 源码, 确保 ``r"(RC-\\d+|V-\\d+)"`` 硬编码已替换.

    防 P0-B 漂移再现 — 加新 prefix (EV/FN/V-13) 时漏改 cuckoo_scorer.
    白名单允许:
    - docstring (注释里出现描述性 RC-/V-)
    - 错误提示文案 (用户可读的"如 V-XX/RC-XXX")
    禁止: re.findall / re.search / re.compile 上的字面量 rule_id 列举.
    """
    import re as re_mod

    src_path = os.path.join(
        os.path.dirname(__file__), "..", "cuckoo_scorer.py"
    )
    with open(src_path, "r", encoding="utf-8") as f:
        src = f.read()

    # 不允许 re.findall/match/search/compile 上含 RC-\d+|V-\d+ 字面量
    forbidden = re_mod.findall(
        r"re\.(?:findall|match|search|compile|sub|split)\([^)]*RC-\\d\+\|V-\\d\+[^)]*\)",
        src,
    )
    assert not forbidden, (
        f"cuckoo_scorer.py 仍含硬编码 rule_id regex 调用: {forbidden}. "
        "应改用 _extract_rule_ids_via_registry → SchemaRegistry."
    )
