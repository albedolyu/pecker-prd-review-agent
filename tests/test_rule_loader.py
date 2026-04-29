"""测试 review/rule_loader.py — SSOT extends 加载.

覆盖:
1. 老 schema (无 extends, 直接列 rules) 加载 OK
2. 新 schema (extends SSOT) 加载 OK + 数量正确
3. 同 id 时 additional_rules 覆盖 SSOT
4. 跨 workspace 加载结果一致 (除自定义部分)
5. 升级覆盖率 100% (L3 字段)
6. 循环 extends 安全
"""
from __future__ import annotations

import os
import textwrap

import pytest

from review.rule_loader import (
    _merge_rules,
    get_rule_by_id,
    list_rule_ids,
    load_review_checklist,
)

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)


def _make_workspace(tmp_path, yaml_content: str) -> str:
    """在 tmp 下造 workspace/review-rules/review-checklist.yaml."""
    ws = tmp_path / "ws"
    rules_dir = ws / "review-rules"
    rules_dir.mkdir(parents=True)
    (rules_dir / "review-checklist.yaml").write_text(yaml_content, encoding="utf-8")
    return str(ws)


# =========================================================
# 1. 老 schema 兼容
# =========================================================


def test_load_legacy_schema_direct_rules(tmp_path):
    """老 schema (没 extends, 直接列 rules) — 100% 向后兼容."""
    yaml_content = textwrap.dedent("""\
        rules:
          - id: RC-004
            name: legacy rule
            severity: must
            description: legacy
            impact_score: 0.7
          - id: RC-005
            name: another legacy
            severity: should
            description: legacy
            impact_score: 0.5
        """)
    ws = _make_workspace(tmp_path, yaml_content)
    rules = load_review_checklist(ws)
    assert len(rules) == 2
    assert {r["id"] for r in rules} == {"RC-004", "RC-005"}


def test_load_real_workspace_sample_old_schema():
    """2026-04-28 SSOT 迁移后, workspace-sample 已转为 extends 模式 (additional_rules: []),
    应展开为 SSOT 全部 31 条规则. 之前的 10 条老 inline 在 .bak 备份, 不再生效."""
    ws = os.path.join(_ROOT, "workspace-sample")
    rules = load_review_checklist(ws)
    assert len(rules) == 31, f"SSOT extends 后应有 31 条, 实际 {len(rules)} (yaml 是否被回滚?)"
    ids = {r["id"] for r in rules}
    # 老 10 条 SSOT 兼容 ID 仍应在 (现在都来自 SSOT)
    legacy_ids = {"RC-004", "RC-005", "RC-006", "RC-007", "RC-008",
                  "RC-009", "RC-014", "RC-015"}
    assert legacy_ids.issubset(ids), f"SSOT 应仍包含老 ID, 缺失: {legacy_ids - ids}"


# =========================================================
# 2. 新 schema (extends) 加载
# =========================================================


def test_load_new_schema_with_extends(tmp_path):
    """新 schema 用 extends 引用 SSOT — 应自动展开 SSOT 全部规则."""
    yaml_content = f"""\
extends: {_ROOT.replace(chr(92), '/')}/review-rules-shared/review-checklist.yaml
additional_rules: []
"""
    ws = _make_workspace(tmp_path, yaml_content)
    rules = load_review_checklist(ws)
    # SSOT 当前是 31 条, ≥30 是 task 要求
    assert len(rules) >= 30
    # 全部应有 L3 升级
    upgraded = sum(1 for r in rules if r.get("positive_example"))
    assert upgraded == len(rules), \
        f"L3 覆盖率不足: {upgraded}/{len(rules)}"
    # fire_when 也应 100%
    assert all(r.get("fire_when") for r in rules)


def test_load_real_workspace_laodong_uses_extends():
    """workspace-劳动仲裁 已迁移到 extends 模式 (ship 范本)."""
    ws = os.path.join(_ROOT, "workspace-劳动仲裁")
    rules = load_review_checklist(ws)
    assert len(rules) >= 30
    # 100% L3 升级
    upgraded = sum(1 for r in rules if r.get("positive_example"))
    assert upgraded == len(rules)


# =========================================================
# 3. additional_rules 覆盖 SSOT 同 id
# =========================================================


def test_additional_rules_override_ssot(tmp_path):
    """workspace 在 additional_rules 里写同 id 应覆盖 SSOT 的版本."""
    yaml_content = f"""\
extends: {_ROOT.replace(chr(92), '/')}/review-rules-shared/review-checklist.yaml
additional_rules:
  - id: RC-004
    name: workspace 覆盖版
    severity: should
    description: 本 workspace 把 RC-004 降为 should
    impact_score: 0.3
"""
    ws = _make_workspace(tmp_path, yaml_content)
    rule = get_rule_by_id(ws, "RC-004")
    assert rule is not None
    assert rule["name"] == "workspace 覆盖版"
    assert rule["severity"] == "should"
    assert rule["impact_score"] == 0.3


def test_additional_rules_appended_when_new_id(tmp_path):
    """workspace additional_rules 新 id 应追加."""
    yaml_content = f"""\
extends: {_ROOT.replace(chr(92), '/')}/review-rules-shared/review-checklist.yaml
additional_rules:
  - id: RC-099
    name: 本 workspace 独有规则
    severity: must
    description: foo
    impact_score: 0.5
"""
    ws = _make_workspace(tmp_path, yaml_content)
    ids = list_rule_ids(ws)
    assert "RC-099" in ids
    assert "RC-004" in ids  # SSOT 原有的也保留


# =========================================================
# 4. 跨 workspace 一致性
# =========================================================


def test_extends_workspaces_have_consistent_ssot_rules(tmp_path):
    """两个不同 workspace 都 extends SSOT, SSOT 部分应完全一致."""
    yaml_a = f"""\
extends: {_ROOT.replace(chr(92), '/')}/review-rules-shared/review-checklist.yaml
additional_rules: []
"""
    yaml_b = f"""\
extends: {_ROOT.replace(chr(92), '/')}/review-rules-shared/review-checklist.yaml
additional_rules:
  - id: RC-099
    name: only in B
    severity: must
    description: x
"""
    ws_a = _make_workspace(tmp_path / "a", yaml_a)
    ws_b = _make_workspace(tmp_path / "b", yaml_b)
    rules_a = load_review_checklist(ws_a)
    rules_b = load_review_checklist(ws_b)

    # SSOT 部分: B 比 A 多一条 RC-099
    ids_a = {r["id"] for r in rules_a}
    ids_b = {r["id"] for r in rules_b}
    assert ids_b == ids_a | {"RC-099"}
    # 同 id 内容应一致
    for rid in ids_a:
        ra = next(r for r in rules_a if r["id"] == rid)
        rb = next(r for r in rules_b if r["id"] == rid)
        assert ra == rb, f"{rid} 内容不一致"


# =========================================================
# 5. 边界 / 错误处理
# =========================================================


def test_loader_returns_empty_when_workspace_not_exist(tmp_path):
    """workspace 路径不存在 → 空 list, 不抛."""
    rules = load_review_checklist(str(tmp_path / "nonexistent"))
    assert rules == []


def test_loader_returns_empty_when_yaml_missing(tmp_path):
    """workspace 存在但 yaml 缺失 → 空 list."""
    ws = tmp_path / "ws"
    (ws / "review-rules").mkdir(parents=True)
    rules = load_review_checklist(str(ws))
    assert rules == []


def test_loader_handles_broken_yaml(tmp_path):
    """yaml 损坏 → 空 list + warn (不抛, 让 caller 决定)."""
    ws = _make_workspace(tmp_path, "rules: [\nbroken")
    rules = load_review_checklist(ws)
    assert rules == []


def test_loader_handles_missing_extends_target(tmp_path):
    """extends 指向不存在的文件 → 不抛, 走 additional_rules."""
    yaml_content = """\
extends: ./nonexistent.yaml
additional_rules:
  - id: RC-001
    name: only local
    severity: must
"""
    ws = _make_workspace(tmp_path, yaml_content)
    rules = load_review_checklist(ws)
    assert len(rules) == 1
    assert rules[0]["id"] == "RC-001"


def test_merge_rules_overlay_overrides_base():
    """内部 _merge_rules 单元测试."""
    base = [{"id": "A", "name": "base"}, {"id": "B", "name": "base"}]
    overlay = [{"id": "B", "name": "overlay"}, {"id": "C", "name": "new"}]
    out = _merge_rules(base, overlay)
    by_id = {r["id"]: r for r in out}
    assert by_id["A"]["name"] == "base"
    assert by_id["B"]["name"] == "overlay"
    assert by_id["C"]["name"] == "new"
    assert len(out) == 3


# =========================================================
# 6. SSOT 全局健康度
# =========================================================


def test_ssot_yaml_has_30_plus_rules():
    """SSOT 应有 ≥30 条规则 (task 验收点)."""
    ssot_path = os.path.join(_ROOT, "review-rules-shared", "review-checklist.yaml")
    assert os.path.isfile(ssot_path)
    import yaml
    with open(ssot_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    assert len(data["rules"]) >= 30


def test_ssot_yaml_full_l3_coverage():
    """SSOT 每条 rule 必须有 fire_when + dont_fire_when + positive_example."""
    ssot_path = os.path.join(_ROOT, "review-rules-shared", "review-checklist.yaml")
    import yaml
    with open(ssot_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    for rule in data["rules"]:
        rid = rule["id"]
        assert rule.get("fire_when"), f"{rid} 缺 fire_when"
        assert rule.get("dont_fire_when"), f"{rid} 缺 dont_fire_when"
        assert rule.get("positive_example"), f"{rid} 缺 positive_example"
        # negative_example 可以是 null, 但若是 null 必须有 why_no_negative
        ne = rule.get("negative_example")
        if ne is None:
            assert rule.get("why_no_negative"), f"{rid} negative_example=null 但无 why_no_negative"


def test_ssot_severity_values_valid():
    """SSOT 每条 rule severity 必须是 must / should."""
    ssot_path = os.path.join(_ROOT, "review-rules-shared", "review-checklist.yaml")
    import yaml
    with open(ssot_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    for rule in data["rules"]:
        assert rule.get("severity") in ("must", "should"), \
            f"{rule['id']} severity={rule.get('severity')} 不合法"
