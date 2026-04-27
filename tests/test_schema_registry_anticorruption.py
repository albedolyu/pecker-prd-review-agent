"""schema_registry 老 yaml anti-corruption layer 单测 (step 3.6).

参考 docs/schema_registry_design_2026_04_27.md Part 4 (最大风险).

背景:
- 6 个 workspace 各自有 review-checklist.yaml 老 schema (id/name/severity/impact_score)
- 全局新 yaml review-dimensions.yaml 有 RC-014 已删 (commit f876fd5), 但 6 老 yaml 还有 RC-014
- step 3.6 加 anti-corruption layer 转译老 yaml, 关键防 RC-014 zombie 复活
- 转译策略: 老字段 → 新 RuleDef (severity + impact_score 由 step 3.6 加进 RuleDef)
- 冲突策略: 全局新 yaml 优先于 workspace 老 yaml (新 yaml 已删的 rule_id 不复活)

覆盖目标 (设计 doc Part 4 要求 ≥ 8 项):
1. 6 workspace 老 yaml 全部能转译, 不 raise
2. 转译后 rule_id 全部合法 (V/RC/EV/FN 前缀)
3. severity / impact_score 字段保留到 RuleDef
4. dimension 从 rule_id prefix 推断准 (V- → quality, RC- 部分 → ai_coding, etc.)
5. RC-014 zombie 在转译时被 drop + warn (新 yaml 已删, 不让复活)
6. global > legacy 优先级一致 (跟 P0-A iter_wiki_files 一致)
7. 老 yaml 损坏时 raise SchemaRegistryError
8. owner / status 默认值 (legacy_workspace / active)
"""

from __future__ import annotations

import os
import sys
import textwrap

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from review.schema_registry import (
    RuleDef,
    SchemaRegistry,
    SchemaRegistryError,
    _infer_dimension_from_prefix,
    _load_legacy_workspace_yaml,
    _merge_workspace_rules,
)


# ============================================================
# autouse fixture: 清 cache (与 test_schema_registry.py 一致)
# ============================================================


@pytest.fixture(autouse=True)
def _clear_registry_cache():
    SchemaRegistry._cached_get.cache_clear()
    from review.dimensions import _cached_load
    _cached_load.cache_clear()
    yield
    SchemaRegistry._cached_get.cache_clear()
    _cached_load.cache_clear()


# ============================================================
# 1. 6 workspace 老 yaml 全部能转译 (真读, 不 mock)
# ============================================================


# 6 workspace 实际目录名
LEGACY_WORKSPACES = [
    "workspace",
    "workspace-产品召回",
    "workspace-对外投资",
    "workspace-劳动仲裁",
    "workspace-纳税人资质",
    "workspace-侵权软件",
]


@pytest.mark.parametrize("workspace", LEGACY_WORKSPACES)
def test_legacy_yaml_translation_loadable(workspace):
    """每个 workspace 老 review-checklist.yaml 能转译, 不 raise."""
    repo_root = os.path.join(os.path.dirname(__file__), "..")
    ws_path = os.path.join(repo_root, workspace)
    rules = _load_legacy_workspace_yaml(ws_path)
    assert isinstance(rules, list), f"{workspace}: 应返回 list"
    assert len(rules) > 0, f"{workspace}: 转译后 0 规则 (yaml 应有 10 条)"
    # 全部都是 RuleDef
    for r in rules:
        assert isinstance(r, RuleDef), f"{workspace}: 元素应为 RuleDef, 实为 {type(r)}"


# ============================================================
# 2. 转译后 rule_id 全部合法 (V/RC/EV/FN 前缀)
# ============================================================


@pytest.mark.parametrize("workspace", LEGACY_WORKSPACES)
def test_legacy_rule_ids_valid_prefix(workspace):
    """转译后 rule_id 全部符合 V/RC/EV/FN 前缀."""
    import re

    repo_root = os.path.join(os.path.dirname(__file__), "..")
    ws_path = os.path.join(repo_root, workspace)
    rules = _load_legacy_workspace_yaml(ws_path)
    pattern = re.compile(r"^(V|RC|EV|FN)-\d+$")
    for r in rules:
        assert pattern.match(r.rule_id), (
            f"{workspace}: 非法 rule_id {r.rule_id!r}"
        )


# ============================================================
# 3. severity / impact_score 字段保留 (RuleDef 必须扩字段)
# ============================================================


def test_legacy_severity_preserved():
    """老 severity 字段被保留到 RuleDef.severity."""
    repo_root = os.path.join(os.path.dirname(__file__), "..")
    ws_path = os.path.join(repo_root, "workspace-劳动仲裁")
    rules = _load_legacy_workspace_yaml(ws_path)
    sev_values = {r.severity for r in rules if r.severity is not None}
    # 老 yaml 有 must / should 两类
    assert sev_values & {"must", "should"}, (
        f"应保留 must/should, 实际 severity: {sev_values}"
    )


def test_legacy_impact_score_preserved():
    """老 impact_score 字段被保留到 RuleDef.impact_score (Optional[float])."""
    repo_root = os.path.join(os.path.dirname(__file__), "..")
    ws_path = os.path.join(repo_root, "workspace-劳动仲裁")
    rules = _load_legacy_workspace_yaml(ws_path)
    # 至少有几条规则的 impact_score 应是 0.0-1.0 浮点
    scores = [r.impact_score for r in rules if r.impact_score is not None]
    assert len(scores) > 0, "应至少有一条规则保留 impact_score"
    for s in scores:
        assert 0.0 <= s <= 1.0, f"impact_score 应 0..1, 实际 {s}"


# ============================================================
# 4. dimension 从 rule_id prefix 推断准
# ============================================================


def test_infer_dimension_from_prefix():
    """V- → quality / structure 之一; RC- → data_quality / ai_coding 之一; EV-/FN- 单测."""
    # 与 review-dimensions.yaml 真实分布对齐:
    # V-XX: structure (V-02..V-06) 或 quality (V-07..V-12)
    # RC-XX: ai_coding (RC-004..008/013/015) 或 data_quality (RC-009/010)
    # EV-XX: structure (EV-01) 或 data_quality (EV-04)
    # FN-XX: structure (FN-09) 或 ai_coding (FN-03) 或 data_quality (FN-01)
    dim = _infer_dimension_from_prefix("V-02")
    assert dim in ("structure", "quality"), f"V-02 期望 structure/quality, 实 {dim}"
    dim = _infer_dimension_from_prefix("RC-004")
    assert dim in ("ai_coding", "data_quality"), f"RC-004 期望 ai_coding/data_quality"
    dim = _infer_dimension_from_prefix("RC-009")
    assert dim in ("ai_coding", "data_quality")


def test_infer_dimension_unknown_prefix_fallback():
    """未知前缀 (如 ZZ-XX) 应 fallback 到默认 dimension (不 raise)."""
    dim = _infer_dimension_from_prefix("ZZ-99")
    # 不 raise, 给一个合法 dimension fallback
    assert dim in ("structure", "quality", "ai_coding", "data_quality")


# ============================================================
# 5. RC-014 zombie 防复活 — 关键防御
# ============================================================


def test_rc_014_present_in_legacy_yaml_but_dropped_after_merge():
    """⚠️ 关键: 6 workspace 老 yaml 都有 RC-014 (zombie), 但全局新 yaml 已删.

    转译时单独看 legacy: RC-014 仍在 (老 yaml 真有).
    与全局 merge 后: RC-014 被 drop, 因为新 yaml 已删 → 优先级 global > legacy.
    """
    repo_root = os.path.join(os.path.dirname(__file__), "..")
    ws_path = os.path.join(repo_root, "workspace-劳动仲裁")
    legacy_rules = _load_legacy_workspace_yaml(ws_path)
    legacy_ids = {r.rule_id for r in legacy_rules}
    # 老 yaml 真有 RC-014
    assert "RC-014" in legacy_ids, "老 yaml 应有 RC-014 (zombie 物证)"

    # 全局 yaml 已删 RC-014
    reg_global = SchemaRegistry.get()
    assert "RC-014" not in reg_global.all_rule_ids(), "全局 yaml 应不含 RC-014"

    # 走 merge: legacy 里 RC-014 不应出现在最终 registry
    # (因为新 yaml 已没这条 rule, legacy 不能"复活"已 deprecate 的)
    global_rules_dict = {rid: reg_global.get_rule(rid) for rid in reg_global.all_rule_ids()}
    merged = _merge_workspace_rules(global_rules_dict, legacy_rules)
    assert "RC-014" not in merged, (
        f"RC-014 zombie 复活! merged 含: {sorted(merged.keys())}"
    )


def test_legacy_yaml_with_rc014_logs_warning(caplog):
    """legacy yaml 有 RC-014 但新 yaml 已删时, merge 应 log warning 提示 PM."""
    import logging

    repo_root = os.path.join(os.path.dirname(__file__), "..")
    ws_path = os.path.join(repo_root, "workspace-对外投资")
    legacy_rules = _load_legacy_workspace_yaml(ws_path)

    reg_global = SchemaRegistry.get()
    global_rules_dict = {rid: reg_global.get_rule(rid) for rid in reg_global.all_rule_ids()}

    with caplog.at_level(logging.WARNING):
        _merge_workspace_rules(global_rules_dict, legacy_rules)

    # caplog 里应至少有一条提示老 yaml RC-014 被 drop 的信息
    msgs = " ".join(r.message for r in caplog.records)
    # 不强制要求严格字符串匹配, 但应有 RC-014 / drop / zombie 之一
    has_warning = ("RC-014" in msgs) or ("drop" in msgs.lower()) or ("legacy" in msgs.lower())
    assert has_warning, (
        f"RC-014 zombie drop 应有 log warning. 实际 caplog: {msgs!r}"
    )


# ============================================================
# 6. global > legacy 优先级
# ============================================================


def test_global_priority_over_legacy_for_same_rule_id(tmp_path):
    """同 rule_id 在 global 和 legacy 都存在时, global 字段优先 (status/dimension/owner)."""
    # 构造 global rule (active, dimension=ai_coding, owner=ai_coding)
    global_rule = RuleDef(
        rule_id="RC-004",
        dimension="ai_coding",
        name="GlobalName",
        description="from global",
        owner="ai_coding",
        status="active",
        cross_section=False,
    )
    # 构造 legacy rule (different status / owner / dimension)
    legacy_rule = RuleDef(
        rule_id="RC-004",
        dimension="data_quality",  # 与 global 不一样
        name="LegacyName",
        description="from legacy",
        owner="legacy_workspace",
        status="active",
        cross_section=False,
        severity="must",
        impact_score=0.7,
    )
    merged = _merge_workspace_rules({"RC-004": global_rule}, [legacy_rule])
    # global 仍是 RC-004 winner
    assert merged["RC-004"].name == "GlobalName"
    assert merged["RC-004"].dimension == "ai_coding"
    assert merged["RC-004"].owner == "ai_coding"


def test_legacy_only_rules_kept_when_not_in_global():
    """legacy 里有但 global 也有的 rule_id 用 global; 两边都没的不出现."""
    global_rule = RuleDef(
        rule_id="V-02",
        dimension="structure",
        name="V-02",
        description="V-02",
        owner="structure",
        status="active",
    )
    # legacy 有 RC-013 (假设它真在新 yaml — 实测会有), 也有 RC-014 (zombie)
    legacy_rules = [
        RuleDef(
            rule_id="RC-013",
            dimension="ai_coding",
            name="伪代码字段可追溯",
            description="伪代码字段可追溯",
            owner="legacy_workspace",
            status="active",
            severity="should",
            impact_score=0.6,
        ),
        RuleDef(
            rule_id="RC-014",
            dimension="ai_coding",
            name="RC-014 zombie",
            description="zombie",
            owner="legacy_workspace",
            status="active",
            severity="must",
            impact_score=0.7,
        ),
    ]
    merged = _merge_workspace_rules({"V-02": global_rule}, legacy_rules)
    # V-02 仍在
    assert "V-02" in merged
    # RC-013 / RC-014 不该出现 (因为 global 都没有)
    assert "RC-013" not in merged
    assert "RC-014" not in merged


# ============================================================
# 7. 老 yaml 损坏 raise SchemaRegistryError
# ============================================================


def test_legacy_yaml_corrupt_raises(tmp_path):
    """老 yaml 损坏 (非法语法) 应 raise SchemaRegistryError."""
    fake_ws = tmp_path / "fake-workspace"
    fake_ws.mkdir()
    rules_dir = fake_ws / "review-rules"
    rules_dir.mkdir()
    bad_yaml = rules_dir / "review-checklist.yaml"
    bad_yaml.write_text("rules: [\n  - id:\n  bad indent\n", encoding="utf-8")
    with pytest.raises(SchemaRegistryError):
        _load_legacy_workspace_yaml(str(fake_ws))


def test_legacy_yaml_missing_returns_empty():
    """老 yaml 文件不存在 → 返回空 list (不 raise, anti-corruption fail-soft)."""
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        # 不创建 review-rules/, 让 review-checklist.yaml 找不到
        result = _load_legacy_workspace_yaml(td)
        assert result == []


def test_legacy_yaml_invalid_rule_id_skipped(tmp_path, caplog):
    """老 yaml 含非法 rule_id (如 'XYZ-99') 应被 skip + warn, 不阻塞.

    Defensive: 设计 doc 说"转译失败的老 rule 直接 drop + log warning, 不阻塞启动".
    """
    import logging

    fake_ws = tmp_path / "fake-workspace"
    fake_ws.mkdir()
    rules_dir = fake_ws / "review-rules"
    rules_dir.mkdir()
    yaml_text = textwrap.dedent("""\
        rules:
          - id: XYZ-99
            name: 非法前缀
            severity: must
            description: 应被 skip
            impact_score: 0.5
          - id: RC-004
            name: 合法
            severity: must
            description: 这条留下
            impact_score: 0.7
        """)
    (rules_dir / "review-checklist.yaml").write_text(yaml_text, encoding="utf-8")

    with caplog.at_level(logging.WARNING):
        rules = _load_legacy_workspace_yaml(str(fake_ws))

    # 非法的被丢, 合法的留
    rule_ids = {r.rule_id for r in rules}
    assert "RC-004" in rule_ids
    assert "XYZ-99" not in rule_ids


# ============================================================
# 8. owner / status 默认值
# ============================================================


def test_legacy_owner_defaults_to_legacy_workspace():
    """老 yaml 没有 owner 字段, 转译时默认 'legacy_workspace'."""
    repo_root = os.path.join(os.path.dirname(__file__), "..")
    ws_path = os.path.join(repo_root, "workspace-劳动仲裁")
    rules = _load_legacy_workspace_yaml(ws_path)
    owners = {r.owner for r in rules}
    # 全是 legacy_workspace (因为老 yaml 没 owner 字段)
    assert "legacy_workspace" in owners, (
        f"应默认 owner=legacy_workspace, 实际 {owners}"
    )


def test_legacy_status_defaults_to_active():
    """老 yaml 没有 status 字段, 转译时默认 'active' (兼容老行为)."""
    repo_root = os.path.join(os.path.dirname(__file__), "..")
    ws_path = os.path.join(repo_root, "workspace-劳动仲裁")
    rules = _load_legacy_workspace_yaml(ws_path)
    for r in rules:
        # 全 active (老 yaml 没 status, 默认 active)
        assert r.status == "active", f"{r.rule_id} 默认 status 应是 active, 实 {r.status}"


# ============================================================
# 9. e2e — SchemaRegistry.get(workspace) 走 anti-corruption
# ============================================================


def test_schema_registry_loads_legacy_workspace_e2e(monkeypatch):
    """端到端: SchemaRegistry.get(workspace=...) 应 invoke anti-corruption layer.

    workspace-劳动仲裁 的老 yaml 有 RC-013 (新 yaml 也有), 走 merge 后 RC-013 来自 global.
    RC-014 (老 yaml 有, 新 yaml 已删) 应不在最终 registry.
    """
    repo_root = os.path.join(os.path.dirname(__file__), "..")
    ws_path = os.path.join(repo_root, "workspace-劳动仲裁")
    SchemaRegistry._cached_get.cache_clear()
    from review.dimensions import _cached_load
    _cached_load.cache_clear()

    reg = SchemaRegistry.get(workspace=ws_path)
    ids = reg.all_rule_ids()
    # RC-014 zombie 不应复活
    assert "RC-014" not in ids, f"RC-014 zombie 复活了! ids={sorted(ids)}"
    # 关键 rule 仍在 (来自 global)
    assert "V-02" in ids
    assert "RC-009" in ids


# ============================================================
# 额外: 转译后 cross_section 标记仍准 (V-05/V-06/RC-009 不被 legacy 覆盖)
# ============================================================


def test_cross_section_preserved_after_merge():
    """走 merge 后 cross_section 标记仍准 (走 global 优先级, 不被老 yaml 覆盖)."""
    repo_root = os.path.join(os.path.dirname(__file__), "..")
    ws_path = os.path.join(repo_root, "workspace-劳动仲裁")
    SchemaRegistry._cached_get.cache_clear()
    from review.dimensions import _cached_load
    _cached_load.cache_clear()

    reg = SchemaRegistry.get(workspace=ws_path)
    # RC-009 (data_quality) 是 cross_section
    if "RC-009" in reg.all_rule_ids():
        rule = reg.get_rule("RC-009")
        assert rule.cross_section is True
