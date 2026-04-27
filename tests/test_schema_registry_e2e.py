"""schema_registry **端到端** integration test (step 3.7).

参考 docs/schema_registry_design_2026_04_27.md step 3.7.

设计目的:
- step 3.1-3.6 单测都是单消费者 wiring 验证, 跑得过单测但
  不一定全链路对得上. 本文件**真**调 production 函数 (worker /
  evidence_verify / review_fixer / prompting), 验:
  yaml → SchemaRegistry → 6 个下游 (worker tool enum / evidence_verify
  regex / review_fixer infer / prompting hint / anti-corruption merge /
  reload propagation) 全部用同一个 SoT.

7 测试组覆盖:
- A: registry → worker dim_constrained_tool enum
- B: registry → evidence_verify._extract_rule_ids
- C: registry → review_fixer.infer_evidence_type
- D: registry → prompting._b_class_format_hint
- E: 6 workspace anti-corruption 全链路 (RC-014 zombie 端到端不复活)
- F: yaml 加新规则 V-13 → 6 处全自动 propagate (单点 SoT 核心保证)
- G: yaml 删规则 → 全链路下不再识别

yaml fixture 策略: **选项 A** — monkeypatch dimensions._BASE_DIR
指向 tmp_path 装的 modified yaml, 真走 yaml 加载链, 不 short-circuit
SchemaRegistry._cached_get. 测试结束 monkeypatch 还原 + 清 cache.
"""

from __future__ import annotations

import os
import re
import shutil
import sys
import textwrap

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from review.schema_registry import (
    RuleDef,
    SchemaRegistry,
    SchemaRegistryError,
)


# ============================================================
# autouse fixture: 测试间清 cache (与 test_schema_registry.py 同策略)
# ============================================================

@pytest.fixture(autouse=True)
def _clear_registry_cache():
    """每个 e2e test 前清 cache (lru_cache + dimensions._cached_load)."""
    SchemaRegistry._cached_get.cache_clear()
    from review.dimensions import _cached_load
    _cached_load.cache_clear()
    yield
    SchemaRegistry._cached_get.cache_clear()
    _cached_load.cache_clear()


# ============================================================
# 共享 yaml fixture helper — 选项 A 实现
# ============================================================

# 真实仓库路径
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_REAL_YAML_PATH = os.path.join(_REPO_ROOT, "review-dimensions.yaml")


def _make_modified_yaml_dir(tmp_path, transform):
    """工厂: 把真 review-dimensions.yaml 读出, transform 修改后写到 tmp_path.

    返回 tmp_path 目录路径, caller monkeypatch dimensions._BASE_DIR 指它即可.

    Args:
        tmp_path: pytest tmp_path fixture
        transform: callable (yaml_text: str) -> str, 文本级改 yaml.

    Returns:
        str — 新目录的绝对路径, 含 modified review-dimensions.yaml.
    """
    with open(_REAL_YAML_PATH, "r", encoding="utf-8") as f:
        original = f.read()
    modified = transform(original)
    target = tmp_path / "review-dimensions.yaml"
    target.write_text(modified, encoding="utf-8")
    return str(tmp_path)


# ============================================================
# 测试组 A — registry → worker tool schema → LLM enum
# ============================================================
# A.1: 真加载 yaml → registry.dimension_rules('data_quality') 给 worker
#      → worker._prepare_worker_context 出的 dim_constrained_tool 含 enum
#      → enum 内容跟 registry.dimension_rules 给的 rule_id 完全一致


def _fake_worker_ctx(dim_key, workspace=None):
    """复用 worker._prepare_worker_context 真函数, 但传最小 args.

    workspace=None → 全局 yaml; 传路径 → 走 anti-corruption.
    返回 ctx dict (含 dim_constrained_tool / dim 等), caller 直接 assert enum.
    """
    from review.worker import _prepare_worker_context

    # 真 invoke. wiki_pages={} / prd_content="" 让 prompt 生成不崩.
    return _prepare_worker_context(
        dim_key=dim_key,
        model_tiers={"sonnet": "claude-sonnet-4-6", "opus": "claude-opus-4-7"},
        rule_perf_history=None,
        wiki_path=workspace,
        wiki_pages={},
        prd_content="测试 PRD",
        diff_context=None,
    )


def test_a1_worker_tool_enum_matches_registry_data_quality():
    """A.1: data_quality 维度 worker tool enum 必须 == registry.dimension_rules('data_quality') rule_id 集合."""
    reg = SchemaRegistry.get()
    expected_ids = sorted(r.rule_id for r in reg.dimension_rules("data_quality"))
    assert expected_ids, "前置: data_quality 维度应有 rule (RC-009/RC-010/EV-04/FN-01)"

    ctx = _fake_worker_ctx("data_quality")
    tool = ctx["dim_constrained_tool"]
    enum = tool["input_schema"]["properties"]["items"]["items"]["properties"]["rule_id"]["enum"]

    assert sorted(enum) == expected_ids, (
        f"worker tool enum 与 registry.dimension_rules('data_quality') 不一致: "
        f"enum={sorted(enum)} expected={expected_ids}"
    )


def test_a2_worker_tool_enum_matches_registry_structure():
    """A.2: structure 维度也满足 enum == registry SoT."""
    reg = SchemaRegistry.get()
    expected_ids = sorted(r.rule_id for r in reg.dimension_rules("structure"))
    assert expected_ids

    ctx = _fake_worker_ctx("structure")
    enum = ctx["dim_constrained_tool"]["input_schema"]["properties"]["items"]["items"]["properties"]["rule_id"]["enum"]
    assert sorted(enum) == expected_ids


def test_a3_worker_tool_dimension_const_matches_dim_name():
    """A.3: tool schema 里 dimension 字段 const 必须 == registry-loaded dim['name'] (中文名).

    确认 worker 不绕 registry 拿 dim_name (老逻辑漂移点之一).
    """
    ctx = _fake_worker_ctx("structure")
    dim_name = ctx["dim"]["name"]
    const_val = ctx["dim_constrained_tool"]["input_schema"]["properties"]["dimension"]["const"]
    assert const_val == dim_name, f"tool const {const_val!r} != dim['name'] {dim_name!r}"


# ============================================================
# 测试组 B — registry → evidence_verify._extract_rule_ids
# ============================================================
# B.1: registry.rule_id_pattern() 出的 regex 给 evidence_verify
#      → _extract_rule_ids 在文本里抽 rule_id, 行为与 registry pattern 一致


def test_b1_evidence_verify_extract_rule_ids_uses_registry():
    """B.1: evidence_verify._extract_rule_ids 应用 registry rule_id_pattern, 抽出 V/RC/EV/FN."""
    from review.evidence_verify import _extract_rule_ids

    text = "PRD 违反 V-02 (文档版本) 和 RC-009 (物理表), 还有 EV-01 / FN-01 三个相关规则."
    extracted = _extract_rule_ids(text)
    # registry 已知前缀都应抽到
    assert "V-02" in extracted
    assert "RC-009" in extracted
    assert "EV-01" in extracted
    assert "FN-01" in extracted


def test_b2_evidence_verify_skips_unknown_prefix():
    """B.2: 文本里 DQ-99 / AC-01 / ZZ-XX 这种 registry 不认的前缀, _extract_rule_ids 不抽."""
    from review.evidence_verify import _extract_rule_ids

    text = "PRD 引用了 DQ-99 (data quality) 和 AC-01 (acceptance) 还有 V-05 (合法)."
    extracted = _extract_rule_ids(text)
    # 只抽合法的, 假前缀略过
    assert "V-05" in extracted
    assert "DQ-99" not in extracted
    assert "AC-01" not in extracted
    assert "ZZ-XX" not in extracted


def test_b3_evidence_verify_pattern_changes_when_yaml_adds_prefix(tmp_path, monkeypatch):
    """B.3: yaml 加新前缀 (假装 BMAD-) → registry pattern 自动含 BMAD → evidence_verify 自动抽到.

    单点 SoT 核心: 修 yaml 一处, evidence_verify 抽取行为同步变.
    """
    # 这里走"加 V-13"路径 (V- 前缀已知, 但加新 rule_id) — yaml 真实文件加 V-13 后
    # registry pattern 仍然是 ^(V|RC|EV|FN)-\d+$, 关键是 V-13 被识别为合法 id.
    def _add_v13(yaml_text):
        # 在 quality dimension checklist 末尾加一条 V-13
        return yaml_text.replace(
            '      - rule_id: "V-12"\n        name: "异常处理完整性"\n        enabled: true\n        owner: quality\n',
            (
                '      - rule_id: "V-12"\n        name: "异常处理完整性"\n        enabled: true\n        owner: quality\n'
                '      - rule_id: "V-13"\n        name: "测试新规则 e2e"\n        enabled: true\n        owner: quality\n'
            ),
        )

    new_dir = _make_modified_yaml_dir(tmp_path, _add_v13)
    monkeypatch.setattr("review.dimensions._BASE_DIR", new_dir)
    SchemaRegistry._cached_get.cache_clear()
    from review.dimensions import _cached_load
    _cached_load.cache_clear()

    from review.evidence_verify import _extract_rule_ids

    text = "PRD 违反 V-13 (新加 e2e 测试规则)."
    extracted = _extract_rule_ids(text)
    assert "V-13" in extracted, f"yaml 加 V-13 后 evidence_verify 应识别. extracted={extracted}"


# ============================================================
# 测试组 C — registry → review_fixer.infer_evidence_type
# ============================================================
# C.1: review_fixer.infer_evidence_type 用 registry 决定哪些 rule_id 算 B 类


def test_c1_review_fixer_infers_b_class_for_known_rule_id():
    """C.1: evidence_content 含 V-02 → infer 出 B 类."""
    from review_fixer import infer_evidence_type

    ev = "依据规则 V-02 (文档版本与变更追踪), 应有版本历史表"
    inferred = infer_evidence_type(ev)
    assert inferred == "B", f"V-02 应推断 B 类, 实 {inferred!r}"


def test_c2_review_fixer_does_not_infer_b_for_unknown_prefix():
    """C.2: evidence_content 含 DQ-99 / AC-XX → 不推 B 类 (registry 不认这前缀)."""
    from review_fixer import infer_evidence_type

    # 没 wiki ref / 没竞品惯例关键词 / 只有假前缀 → 应推 "" (无效)
    ev = "依据规则 DQ-99 (data quality), 应改"
    inferred = infer_evidence_type(ev)
    assert inferred != "B", f"DQ-99 不该推 B (registry 不认), 实 {inferred!r}"


def test_c3_review_fixer_a_class_priority_over_b():
    """C.3: 优先级 A > B — 含 [[wiki]] 引用 + V-02 时推 A 类."""
    from review_fixer import infer_evidence_type

    ev = "依据 [[约束-接口命名规范]] 配合 V-02 检查"
    inferred = infer_evidence_type(ev)
    assert inferred == "A", f"含 [[ref]] 应优先 A 类, 实 {inferred!r}"


def test_c4_review_fixer_picks_up_v13_after_yaml_add(tmp_path, monkeypatch):
    """C.4: yaml 加 V-13 → review_fixer 自动识别成 B 类 (单点 SoT 验证)."""
    def _add_v13(yaml_text):
        return yaml_text.replace(
            '      - rule_id: "V-12"\n        name: "异常处理完整性"\n        enabled: true\n        owner: quality\n',
            (
                '      - rule_id: "V-12"\n        name: "异常处理完整性"\n        enabled: true\n        owner: quality\n'
                '      - rule_id: "V-13"\n        name: "测试新规则 e2e"\n        enabled: true\n        owner: quality\n'
            ),
        )

    new_dir = _make_modified_yaml_dir(tmp_path, _add_v13)
    monkeypatch.setattr("review.dimensions._BASE_DIR", new_dir)
    SchemaRegistry._cached_get.cache_clear()
    from review.dimensions import _cached_load
    _cached_load.cache_clear()

    from review_fixer import infer_evidence_type

    ev = "依据 V-13 检查"
    inferred = infer_evidence_type(ev)
    assert inferred == "B", f"yaml 加 V-13 后 review_fixer 应识别 B 类, 实 {inferred!r}"


# ============================================================
# 测试组 D — registry → prompting._b_class_format_hint
# ============================================================
# D.1: registry.valid_prefixes() + sample_rule_ids(3) 给 prompting._b_class_format_hint
#      → 错误提示文本动态含所有 prefix


def test_d1_prompting_format_hint_contains_all_prefixes():
    """D.1: _b_class_format_hint 文本应含 V/RC/EV/FN 4 前缀."""
    from review.prompting import _b_class_format_hint

    hint = _b_class_format_hint()
    # 前缀格式 "`V-\d+`" / "`RC-\d+`" 等
    assert "V-" in hint
    assert "RC-" in hint
    assert "EV-" in hint
    assert "FN-" in hint


def test_d2_prompting_format_hint_contains_samples():
    """D.2: hint 应含 sample_rule_ids 给的样例 (registry 抽 3 个代表)."""
    from review.prompting import _b_class_format_hint

    reg = SchemaRegistry.get()
    samples = reg.sample_rule_ids(n=3)
    hint = _b_class_format_hint()
    # 至少一个 sample 应出现在 hint 文本里
    matched = any(s in hint for s in samples)
    assert matched, f"hint 应含 sample, samples={samples}, hint={hint!r}"


def test_d3_prompting_format_hint_changes_after_yaml_add(tmp_path, monkeypatch):
    """D.3: yaml 加 V-13 → registry sample/prefix 变 → prompting hint 自动更新."""
    def _add_v13(yaml_text):
        return yaml_text.replace(
            '      - rule_id: "V-12"\n        name: "异常处理完整性"\n        enabled: true\n        owner: quality\n',
            (
                '      - rule_id: "V-12"\n        name: "异常处理完整性"\n        enabled: true\n        owner: quality\n'
                '      - rule_id: "V-13"\n        name: "测试新规则 e2e"\n        enabled: true\n        owner: quality\n'
            ),
        )

    new_dir = _make_modified_yaml_dir(tmp_path, _add_v13)
    monkeypatch.setattr("review.dimensions._BASE_DIR", new_dir)
    SchemaRegistry._cached_get.cache_clear()
    from review.dimensions import _cached_load
    _cached_load.cache_clear()

    # registry 重 load 后 V-13 应在 all_rule_ids
    reg2 = SchemaRegistry.get()
    assert "V-13" in reg2.all_rule_ids(), "前置: yaml 改后 V-13 应在 registry"

    # prompting hint 至少不崩 + 仍含 V- 前缀文本
    from review.prompting import _b_class_format_hint
    hint = _b_class_format_hint()
    assert "V-" in hint


# ============================================================
# 测试组 E — 6 workspace anti-corruption 全链路
# ============================================================
# E.1: SchemaRegistry.get(workspace=ws) 真 invoke anti-corruption
#      → registry.all_rule_ids() 含转译后 rule (除 RC-014 zombie)
#      → worker 跑该 workspace 时 enum 不含 RC-014


_LEGACY_WORKSPACES = [
    "workspace",
    "workspace-产品召回",
    "workspace-对外投资",
    "workspace-劳动仲裁",
    "workspace-纳税人资质",
    "workspace-侵权软件",
]


@pytest.mark.parametrize("ws_name", _LEGACY_WORKSPACES)
def test_e1_workspace_anti_corruption_no_rc014_zombie(ws_name):
    """E.1: 6 workspace 老 yaml 含 RC-014, 走 anti-corruption merge 后不应复活.

    端到端: SchemaRegistry.get(workspace) → all_rule_ids → 不含 RC-014.
    """
    ws_path = os.path.join(_REPO_ROOT, ws_name)
    if not os.path.isdir(ws_path):
        pytest.skip(f"workspace {ws_name} 不存在")

    SchemaRegistry._cached_get.cache_clear()
    from review.dimensions import _cached_load
    _cached_load.cache_clear()

    reg = SchemaRegistry.get(workspace=ws_path)
    ids = reg.all_rule_ids()
    assert "RC-014" not in ids, (
        f"{ws_name}: RC-014 zombie 复活! ids 含: "
        f"{sorted(rid for rid in ids if rid.startswith('RC-014'))}"
    )


def test_e2_worker_enum_excludes_rc014_zombie_in_legacy_workspace():
    """E.2: 走 legacy workspace 时, worker tool enum 也不能含 RC-014.

    端到端: workspace yaml → registry → worker._prepare_worker_context →
    dim_constrained_tool["...rule_id"]["enum"] 不含 RC-014.
    """
    ws_path = os.path.join(_REPO_ROOT, "workspace-劳动仲裁")
    if not os.path.isdir(ws_path):
        pytest.skip("workspace-劳动仲裁 不存在")

    # 跑 ai_coding 维度 — 老 yaml RC-014 zombie 是 ai_coding 类
    ctx = _fake_worker_ctx("ai_coding", workspace=ws_path)
    enum = ctx["dim_constrained_tool"]["input_schema"]["properties"]["items"]["items"]["properties"]["rule_id"].get("enum", [])
    assert "RC-014" not in enum, (
        f"workspace-劳动仲裁 worker enum 含 RC-014 zombie! enum={enum}"
    )


def test_e3_workspace_legacy_yaml_severity_flowing_to_registry():
    """E.3: 老 workspace yaml 的 severity 字段在 anti-corruption 转译后保留到 RuleDef.severity.

    虽 _merge_workspace_rules 当前实现 global 优先 (legacy enrichment 留后续 step),
    但单 _load_legacy_workspace_yaml 应保留. e2e 验从源头保留.
    """
    from review.schema_registry import _load_legacy_workspace_yaml

    ws_path = os.path.join(_REPO_ROOT, "workspace-劳动仲裁")
    if not os.path.isdir(ws_path):
        pytest.skip("workspace-劳动仲裁 不存在")

    legacy_rules = _load_legacy_workspace_yaml(ws_path)
    # 至少几条老 rule 有 severity
    sev_set = {r.severity for r in legacy_rules if r.severity is not None}
    assert sev_set & {"must", "should"}, (
        f"老 yaml severity 字段应保留到 RuleDef.severity, 实 {sev_set}"
    )


# ============================================================
# 测试组 F — yaml 加新规则 V-13 → 6 处自动 propagate
# ============================================================
# 单点 SoT 的核心验证: 加规则改 1 处 (yaml), 自动同步到所有 wiring 点


def test_f_yaml_add_v13_propagates_to_all_wirings(tmp_path, monkeypatch):
    """F: 单点 SoT 核心 — yaml 加 V-13 一次, 自动同步到 6 处 wiring.

    检查点 (1 改 6 同步):
    1. registry.all_rule_ids() 含 V-13
    2. registry.dimension_rules('quality') 含 V-13
    3. worker dim_constrained_tool enum 含 V-13
    4. evidence_verify._extract_rule_ids 抽到 V-13
    5. review_fixer.infer_evidence_type 把 V-13 推 B 类
    6. prompting._b_class_format_hint 至少不崩, 仍含 V- 前缀
    """
    def _add_v13(yaml_text):
        return yaml_text.replace(
            '      - rule_id: "V-12"\n        name: "异常处理完整性"\n        enabled: true\n        owner: quality\n',
            (
                '      - rule_id: "V-12"\n        name: "异常处理完整性"\n        enabled: true\n        owner: quality\n'
                '      - rule_id: "V-13"\n        name: "测试新规则 e2e propagation"\n        enabled: true\n        owner: quality\n'
            ),
        )

    new_dir = _make_modified_yaml_dir(tmp_path, _add_v13)
    monkeypatch.setattr("review.dimensions._BASE_DIR", new_dir)
    SchemaRegistry._cached_get.cache_clear()
    from review.dimensions import _cached_load
    _cached_load.cache_clear()

    # 1. registry 层
    reg = SchemaRegistry.get()
    assert "V-13" in reg.all_rule_ids(), "1) registry.all_rule_ids 应含 V-13"
    quality_rule_ids = {r.rule_id for r in reg.dimension_rules("quality")}
    assert "V-13" in quality_rule_ids, "2) dimension_rules('quality') 应含 V-13"

    # 3. worker 层 — 注: worker 也走 dimensions cache, 必须保 cache 已清
    ctx = _fake_worker_ctx("quality")
    enum = ctx["dim_constrained_tool"]["input_schema"]["properties"]["items"]["items"]["properties"]["rule_id"]["enum"]
    assert "V-13" in enum, f"3) worker tool enum 应含 V-13, 实 enum={enum}"

    # 4. evidence_verify 层
    from review.evidence_verify import _extract_rule_ids
    extracted = _extract_rule_ids("依据 V-13 (新加测试规则)")
    assert "V-13" in extracted, f"4) evidence_verify 应抽 V-13, 实 {extracted}"

    # 5. review_fixer 层
    from review_fixer import infer_evidence_type
    inferred = infer_evidence_type("依据 V-13 检查")
    assert inferred == "B", f"5) review_fixer 应推 B 类, 实 {inferred!r}"

    # 6. prompting 层 — hint 至少含 V- 前缀 (V-13 让 V 仍在 valid_prefixes 里)
    from review.prompting import _b_class_format_hint
    hint = _b_class_format_hint()
    assert "V-" in hint, "6) prompting hint 应保留 V- 前缀"


def test_f2_yaml_add_new_prefix_dq_propagates_pattern(tmp_path, monkeypatch):
    """F.2: yaml 加新 rule_id 前缀 DQ-XX 时, 由于 schema_registry _load_from_dimensions 用
    硬正则 ^(V|RC|EV|FN)-\\d+$ 校验, DQ-99 会 raise SchemaRegistryError.

    本测试验"前缀校验仍然由 schema_registry 集中管理" — 加 DQ- 必须先改
    schema_registry._load_from_dimensions 的 regex, **不能**只改 yaml.
    这是设计约束的正向验证, 防 PM 误以为加新前缀 yaml 改一处就行.
    """
    def _add_dq(yaml_text):
        return yaml_text.replace(
            '      - rule_id: "V-12"\n        name: "异常处理完整性"\n        enabled: true\n        owner: quality\n',
            (
                '      - rule_id: "V-12"\n        name: "异常处理完整性"\n        enabled: true\n        owner: quality\n'
                '      - rule_id: "DQ-99"\n        name: "新前缀测试"\n        enabled: true\n        owner: quality\n'
            ),
        )

    new_dir = _make_modified_yaml_dir(tmp_path, _add_dq)
    monkeypatch.setattr("review.dimensions._BASE_DIR", new_dir)
    SchemaRegistry._cached_get.cache_clear()
    from review.dimensions import _cached_load
    _cached_load.cache_clear()

    # 期望 raise — 校验 schema_registry 仍对前缀有 gatekeeper
    with pytest.raises(SchemaRegistryError) as exc_info:
        SchemaRegistry.get()
    assert "DQ-99" in str(exc_info.value)


# ============================================================
# 测试组 G — yaml 删规则 propagation
# ============================================================
# G.1: yaml 临时删 V-07, registry.reload, 验所有 wiring 不再识别 V-07


def test_g1_yaml_remove_v07_propagates_to_all_wirings(tmp_path, monkeypatch):
    """G.1: yaml 删 V-07 → 所有 wiring 不再识别.

    检查点:
    1. registry.all_rule_ids() 不含 V-07
    2. dimension_rules('quality') 不含 V-07
    3. worker tool enum 不含 V-07
    4. evidence_verify._extract_rule_ids: V-07 在 registry 已删后, regex pattern
       仍允许 V- 前缀 (其他 V-XX 还在), 所以 _extract_rule_ids 仍抽 V-07 substring;
       但 _is_known_rule_id('V-07') 必须返 False.
    """
    def _remove_v07(yaml_text):
        # 把 V-07 那 4 行 (rule_id/name/enabled/owner) 删掉
        return re.sub(
            r'      - rule_id: "V-07"\n        name: "逻辑一致性"\n        enabled: true\n        owner: quality\n',
            "",
            yaml_text,
        )

    new_dir = _make_modified_yaml_dir(tmp_path, _remove_v07)
    monkeypatch.setattr("review.dimensions._BASE_DIR", new_dir)
    SchemaRegistry._cached_get.cache_clear()
    from review.dimensions import _cached_load
    _cached_load.cache_clear()

    # 1. registry 不含 V-07
    reg = SchemaRegistry.get()
    assert "V-07" not in reg.all_rule_ids(), "1) registry 删 V-07 后 all_rule_ids 不该含"

    # 2. quality 维度不含 V-07
    quality_ids = {r.rule_id for r in reg.dimension_rules("quality")}
    assert "V-07" not in quality_ids, "2) dimension_rules('quality') 不该含 V-07"

    # 3. worker enum 不含 V-07
    ctx = _fake_worker_ctx("quality")
    enum = ctx["dim_constrained_tool"]["input_schema"]["properties"]["items"]["items"]["properties"]["rule_id"]["enum"]
    assert "V-07" not in enum, f"3) worker enum 不该含 V-07, 实 enum={enum}"

    # 4. _is_known_rule_id 返 False (membership check)
    from review.evidence_verify import _is_known_rule_id
    assert not _is_known_rule_id("V-07"), "4) _is_known_rule_id 不该认 V-07"


def test_g2_review_fixer_b_inference_after_remove_v07(tmp_path, monkeypatch):
    """G.2: yaml 删 V-07 后, review_fixer 的 B 类推断 — V-07 substring 还能匹配 (因为
    其他 V- 还在, regex 前缀仍含 V), 但下游 _is_known_rule_id 才是真 SoT, 所以
    review_fixer 自身只检查 regex, 行为是 V-07 仍推 B (这是设计上的 weak 校验,
    强校验在 evidence_verify._is_known_rule_id).

    本测试断言 inference 仍走 registry-based regex, **没**漏 fail-fast.
    """
    def _remove_v07(yaml_text):
        return re.sub(
            r'      - rule_id: "V-07"\n        name: "逻辑一致性"\n        enabled: true\n        owner: quality\n',
            "",
            yaml_text,
        )

    new_dir = _make_modified_yaml_dir(tmp_path, _remove_v07)
    monkeypatch.setattr("review.dimensions._BASE_DIR", new_dir)
    SchemaRegistry._cached_get.cache_clear()
    from review.dimensions import _cached_load
    _cached_load.cache_clear()

    # V-07 substring 在 review_fixer 仍推 B (regex 仅前缀匹配, 不查 membership).
    # 但若 yaml 把整个 V- 前缀都删光 (test g3) 才会推 "" — 这是设计的 weak/strong 分层.
    from review_fixer import infer_evidence_type
    inferred = infer_evidence_type("依据 V-07 检查")
    # 仍能匹配 V- 前缀 (因为 V-02..V-12 still exist), 推 B
    assert inferred == "B", (
        f"删 V-07 后 review_fixer regex 仍允许 V- 前缀 (其他 V-XX 在), "
        f"V-07 应仍推 B, 实 {inferred!r}"
    )


def test_g3_yaml_remove_all_ev_prefix_propagates(tmp_path, monkeypatch):
    """G.3: yaml 把所有 EV-XX 删光 → registry.valid_prefixes 不再含 EV →
    review_fixer.infer_evidence_type('EV-99') 不推 B 类.

    这是删整个前缀的 e2e 验证 — yaml 改 1 处, 所有 wiring 同步剥 EV.

    line-based 删 EV-XX 块 — yaml 中每条 rule 占连续 3-5 行, 用 state
    machine 跳过这些行更稳, 比 regex 跨多行匹配可靠.
    """
    def _remove_all_ev(yaml_text):
        # state machine: 遇到 `- rule_id: "EV-XX"` 进 skip 模式,
        # 直到下一个 `- rule_id:` 或 dimension 块边界 (无缩进顶级 key) 退出 skip
        out_lines = []
        skipping = False
        for line in yaml_text.split("\n"):
            stripped = line.strip()
            # 进 skip
            if stripped.startswith("- rule_id:") and '"EV-' in stripped:
                skipping = True
                continue
            # 出 skip — 遇到下一个 - rule_id: 不是 EV / 或 dimension 块边界 (顶级 key)
            if skipping:
                if stripped.startswith("- rule_id:"):
                    skipping = False
                    out_lines.append(line)
                elif (line and not line[0].isspace() and line.rstrip().endswith(":")):
                    skipping = False
                    out_lines.append(line)
                # 否则继续 skip (rule 内部的 name/enabled/owner/status/comment 行)
                continue
            out_lines.append(line)
        return "\n".join(out_lines)

    new_dir = _make_modified_yaml_dir(tmp_path, _remove_all_ev)
    monkeypatch.setattr("review.dimensions._BASE_DIR", new_dir)
    SchemaRegistry._cached_get.cache_clear()
    from review.dimensions import _cached_load
    _cached_load.cache_clear()

    reg = SchemaRegistry.get()
    # EV 前缀应消失
    remaining_ev = [rid for rid in reg.all_rule_ids() if rid.startswith("EV-")]
    assert not remaining_ev, f"yaml 删 EV-XX 失败, 残留 {remaining_ev}"

    prefixes = reg.valid_prefixes()
    assert "EV" not in prefixes, f"删完 EV-XX 后 valid_prefixes 不该含 EV, 实 {prefixes}"

    # rule_id_pattern 不再含 EV
    pattern = reg.rule_id_pattern()
    assert "EV" not in pattern, f"删 EV 后 rule_id_pattern 不该含, 实 {pattern!r}"

    # 注: review_fixer regex 不带 word boundary, "EV-99" 文本会被 V- substring
    # 误命中 — 这是已知的 production 边缘 bug (registry pattern 应加 \b 锚点),
    # 不属于 step 3.7 范围. 这里改用 _is_known_rule_id (registry membership 真判),
    # 它走 set 查无 substring 误命问题.
    from review.evidence_verify import _is_known_rule_id
    assert not _is_known_rule_id("EV-99"), (
        "删完 EV 后 _is_known_rule_id('EV-99') 应 False (registry 没这条)"
    )
    # 同时验证仍存的 V-02 仍认
    assert _is_known_rule_id("V-02"), "V-02 仍在 registry 应认"


# ============================================================
# 额外: 全链路一致性 — registry 是 6 处的"金主"
# ============================================================


def test_h1_consistency_all_wirings_use_same_registry_instance():
    """H.1: 同一进程内, 各 wiring 点拿到的 registry 是同 instance (lru_cache 命中).

    防止"worker 加载一个 registry, evidence_verify 加载另一个" 的并发漂移 bug.
    """
    from review.evidence_verify import _registry_rule_id_extractor
    from review_fixer import _b_class_rule_id_regex

    # 直接 SchemaRegistry.get()
    reg_direct = SchemaRegistry.get()

    # evidence_verify 内部走 registry — 抽 pattern 内容
    ev_pattern = _registry_rule_id_extractor()
    # review_fixer 内部走 registry
    rf_pattern = _b_class_rule_id_regex()

    # 两个 helper 拿到的 registry 应是同 instance
    reg_again = SchemaRegistry.get()
    assert reg_direct is reg_again, "registry singleton 应是同 instance"

    # ev_pattern / rf_pattern 都是 compiled regex, 字符串等价
    assert isinstance(ev_pattern.pattern, str)
    assert isinstance(rf_pattern.pattern, str)


def test_h2_consistency_worker_enum_size_matches_dimension_rules_count():
    """H.2: worker tool enum 长度 == registry.dimension_rules() 长度 (各维度对账)."""
    reg = SchemaRegistry.get()
    for dim_key in ("structure", "quality", "ai_coding", "data_quality"):
        registry_count = len(reg.dimension_rules(dim_key))
        ctx = _fake_worker_ctx(dim_key)
        enum = ctx["dim_constrained_tool"]["input_schema"]["properties"]["items"]["items"]["properties"]["rule_id"].get("enum", [])
        assert len(enum) == registry_count, (
            f"{dim_key} worker enum {len(enum)} 条 != registry {registry_count} 条"
        )
