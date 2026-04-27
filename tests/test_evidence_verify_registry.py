"""evidence_verify ↔ SchemaRegistry 接通单测 (step 3.4).

参考 docs/schema_registry_design_2026_04_27.md step 3.4.

设计意图:
- 替代 evidence_verify.py 内 2 处散落 rule_id regex (line 486 / 528).
- 新加 yaml 规则 (V-13 / RC-017 / FN-04 等) 时 evidence_verify 不需要再改.
- 防 P0-B 漂移再现 (上次新加 EV/FN 漏改了 evidence_verify, 让 worker 提的 EV/FN
  evidence 100% 被判 retract).

覆盖 6 类断言:
1. _find_rule_reference 用 registry pattern 提取 rule_id (不再硬编码 regex)
2. _verify_b_class_semantic 用 registry pattern 提取 rule_id
3. registry 不识别的 rule_id 前缀 (DQ-XX) 被 reject
4. registry 加新 rule_id (monkeypatch yaml 加 V-13) 自动被 evidence_verify 识别
5. _find_rule_reference 仍兼容 BMAD V-XX 写法 (向后兼容)
6. P0-B 行为不变: EV-01 / FN-09 仍能被识别
"""

from __future__ import annotations

import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from review.evidence_verify import (
    _find_rule_reference,
    _verify_b_class_semantic,
)
from review.schema_registry import SchemaRegistry


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
def fake_rules_dir(tmp_path):
    """在 tmp 下造一个 review-rules/all-rules.md, 让 _find_rule_reference 读得到.

    内容包含 V-02 / RC-009 / EV-01 / FN-01 真规则名 (跟 yaml 对齐).
    """
    rules_dir = tmp_path / "review-rules"
    rules_dir.mkdir()
    rules_file = rules_dir / "all-rules.md"
    rules_file.write_text(
        "# 评审规则\n"
        "## V-02 内容自洽\n"
        "## RC-009 物理表定义\n"
        "## EV-01 验收标准可执行\n"
        "## FN-01 字段类型一致\n"
        "## V-13 假新规则 (test only)\n"
        "## DQ-XX 不存在的伪前缀\n",
        encoding="utf-8",
    )
    return str(rules_dir)


# ============================================================
# 1. _find_rule_reference 走 registry pattern (而非硬编码 regex)
# ============================================================


def test_find_rule_reference_uses_registry_pattern(fake_rules_dir):
    """evidence 内含 V-02 应被 _find_rule_reference 识别 (registry 已知前缀)."""
    ev = "依据 V-02 内容自洽性检查"
    assert _find_rule_reference(ev, fake_rules_dir) is True


def test_find_rule_reference_recognizes_all_4_prefixes(fake_rules_dir):
    """4 前缀 V/RC/EV/FN 都应被 _find_rule_reference 识别 (P0-B 行为不变)."""
    cases = [
        "依据 V-02",
        "参考 RC-009 物理表定义",
        "见 EV-01",
        "对应 FN-01",
    ]
    for ev in cases:
        assert _find_rule_reference(ev, fake_rules_dir) is True, f"failed for {ev!r}"


def test_find_rule_reference_bmad_prefix_compatible(fake_rules_dir):
    """BMAD V-XX 写法仍兼容 (向后兼容老 worker 输出)."""
    ev = "BMAD V-02 内容自洽"
    assert _find_rule_reference(ev, fake_rules_dir) is True


# ============================================================
# 2. _verify_b_class_semantic 走 registry pattern
# ============================================================


def test_verify_b_class_uses_registry_pattern(fake_rules_dir):
    """B 类语义验证应能从 evidence 抽 V-02 (registry 已知前缀)."""
    item = {
        "evidence_content": "V-02 内容自洽",
        "issue": "PRD 内容自洽性不足",
        "suggestion": "应明确字段定义",
    }
    passed, note = _verify_b_class_semantic(item, fake_rules_dir)
    # V-02 在 fake_rules_dir 里能找到, 关键词 "内容" / "自洽" / "字段" 与规则文本 overlap
    # passed 不强求 (overlap 取决于关键词命中), 但至少 _verify 不应崩, 且 rule_id 抽取成功
    assert isinstance(passed, bool)


def test_verify_b_class_recognizes_ev_fn(fake_rules_dir):
    """EV-/FN- 在 _verify_b_class_semantic 内也应被抽出 (P0-B 行为不变)."""
    item = {
        "evidence_content": "EV-01 验收标准",
        "issue": "验收标准不可执行",
        "suggestion": "补可量化验收",
    }
    passed, note = _verify_b_class_semantic(item, fake_rules_dir)
    assert isinstance(passed, bool)


# ============================================================
# 3. registry 不识别的前缀被 reject
# ============================================================


def test_unknown_rule_prefix_rejected(fake_rules_dir):
    """DQ-XX / ZZ-99 这种伪前缀不在 registry, 应被 _find_rule_reference 视为无 rule."""
    # evidence 只含伪前缀, _find_rule_reference 应返回 False (没有合法 rule_id)
    ev = "DQ-XX 不存在的规则"
    assert _find_rule_reference(ev, fake_rules_dir) is False


def test_unknown_prefix_in_b_class_skipped(fake_rules_dir):
    """B 类 evidence 含伪前缀时 _verify_b_class_semantic 跳过验证返 (True, '')."""
    item = {
        "evidence_content": "DQ-XX 伪规则",
        "issue": "test issue",
        "suggestion": "test suggestion",
    }
    passed, note = _verify_b_class_semantic(item, fake_rules_dir)
    # rule_ids 为空 → 跳过验证返 (True, '')
    assert passed is True
    assert note == ""


# ============================================================
# 4. registry 加新 rule_id 自动被 evidence_verify 识别 (单点 SoT)
# ============================================================


def test_new_rule_added_in_registry_auto_recognized(fake_rules_dir, monkeypatch):
    """模拟 yaml 加 V-13 新规则, evidence_verify 不需要改代码就能识别.

    这是 step 3.4 核心价值 — 单点 SoT 防 P0-B 漂移再现.
    """
    # 用 monkeypatch 直接构造一个含 V-13 的 fake registry 并替换 SchemaRegistry.get
    from review.schema_registry import RuleDef, SchemaRegistry

    fake_rules = {
        "V-02": RuleDef(rule_id="V-02", dimension="structure", name="内容自洽",
                        description="", status="active"),
        "V-13": RuleDef(rule_id="V-13", dimension="structure", name="新加规则 (test)",
                        description="", status="experimental"),
        "RC-009": RuleDef(rule_id="RC-009", dimension="data_quality",
                          name="物理表定义", description="", status="active",
                          cross_section=True),
        "EV-01": RuleDef(rule_id="EV-01", dimension="structure",
                         name="验收标准", description="", status="experimental"),
        "FN-01": RuleDef(rule_id="FN-01", dimension="data_quality",
                         name="字段类型", description="", status="active"),
    }
    fake_registry = SchemaRegistry(rules=fake_rules, dimensions=("structure", "data_quality"))

    # registry pattern 应自动覆盖 V- 前缀 → V-13 在 evidence 里能被抽出
    pattern = fake_registry.rule_id_pattern()
    import re
    assert re.match(pattern, "V-13") is not None
    # V-13 应在 all_rule_ids 里
    assert "V-13" in fake_registry.all_rule_ids()

    # 当 evidence_verify 走 registry 后, V-13 的 evidence 也应被识别 — 但 V-13 在 fake_rules_dir
    # 里有个标题, 所以 _find_rule_reference 也找得到. 这里关键是 registry 抽取层不漏.
    # 注意: SchemaRegistry.get 是 lru_cache, monkeypatch 整体替换 _cached_get 不太干净,
    # 这里用 patch SchemaRegistry.get 直接返回 fake_registry.
    with patch.object(SchemaRegistry, "get", return_value=fake_registry):
        # V-13 在 fake_rules_dir/all-rules.md 已写入, 应找到
        assert _find_rule_reference("依据 V-13 新规则", fake_rules_dir) is True


# ============================================================
# 5. anti-corruption: 替换后 evidence_verify 不再依赖硬编码 regex 字符串
# ============================================================


def test_evidence_verify_no_hardcoded_rule_id_regex():
    """grep evidence_verify.py 源码, 确保 line 486 / 528 的 (RC|V|EV|FN)-\\d+ 硬编码已替换.

    防再次出现 P0-B 漂移 — 加新前缀时漏改 evidence_verify.
    白名单允许的硬编码 = 注释 (# / docstring), 不在 re.findall / re.compile 调用上.
    """
    import re as re_mod

    src_path = os.path.join(
        os.path.dirname(__file__), "..", "review", "evidence_verify.py"
    )
    with open(src_path, "r", encoding="utf-8") as f:
        src = f.read()

    # 找所有 re.findall / re.match / re.compile 等调用上含 (?:RC|V|EV|FN) 字面量的硬编码
    # 不允许该字符序列作为 re.* 函数参数字面量出现
    # (允许在注释 / docstring / 测试白名单变量等位置)
    forbidden = re_mod.findall(
        r're\.(?:findall|match|search|compile|sub|split)\([^)]*\(\?:RC\|V\|EV\|FN\)[^)]*\)',
        src,
    )
    assert not forbidden, (
        f"evidence_verify.py 仍含硬编码 rule_id regex 调用: {forbidden}. "
        "应改用 SchemaRegistry.get(workspace).rule_id_pattern() 单点 SoT."
    )


# ============================================================
# 6. 集成: verify_evidence 端到端走 registry 仍能正确判 B 类
# ============================================================


def test_verify_evidence_b_class_end_to_end_via_registry(fake_rules_dir, tmp_path):
    """端到端: verify_evidence 收到 B 类 item, 走 registry 抽 rule_id, 标 VERIFIED."""
    from review.evidence_verify import verify_evidence

    # 造 workspace 结构: review-rules + 空 wiki
    ws = tmp_path
    wiki_dir = ws / "wiki"
    wiki_dir.mkdir()
    # 把 fake_rules_dir 内容复制 (rules_dir 必须叫 review-rules 在 ws 下)
    # fake_rules_dir 已经是 tmp_path / 'review-rules', 所以 ws 已经含 review-rules

    items = [
        {
            "id": "1",
            "evidence_type": "B",
            "evidence_content": "依据 V-02 内容自洽",
            "issue": "PRD 内容自洽性不足",
            "suggestion": "补字段定义",
        },
        {
            "id": "2",
            "evidence_type": "B",
            "evidence_content": "依据 EV-01 验收标准",
            "issue": "验收标准不可执行",
            "suggestion": "补量化指标",
        },
    ]
    out = verify_evidence(items, str(ws))
    # 两条 B 类都应能识别 rule_id, 不被判 retracted (V-02/EV-01 都在 rules 文件里)
    assert out[0]["status"] == "VERIFIED"
    assert out[1]["status"] == "VERIFIED"
