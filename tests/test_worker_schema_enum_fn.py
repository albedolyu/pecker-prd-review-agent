"""P0-B 防回归 (2026-04-27): worker / prompting 真识别 EV-/FN- rule_id 不被降级.

背景:
2026-04-27 calibration verdict: FN active 接通 PARTIAL — schema 已扩
`^(V|RC|EV|FN)-\\d+$` (commit a45e3dd) + yaml 已加 FN-01/03/09 + EV-01/04
(commit f288c9c), 但 worker 实际 submit 全用幻觉 ID (DQ-XX/AC-XX), 0 条 FN/EV.

根因 (3 处 regex 漏 EV/FN):
1. `prompting._build_feedback_section`: regex `(?:RC-\\d+|V-\\d+)` 漏 EV/FN,
   rule_perf 反馈循环里 EV-01/FN-XX 永远进不来, EV/FN 历史无法注入 worker prompt.
2. `prompting._build_real_refs_section`: 同 regex 漏 EV/FN, 真实清单里没
   出现 → 模型看不到合法 EV/FN id → 用幻觉 ID (DQ-XX/AC-XX) 试图绕开.
3. `prompting._build_real_refs_section` 错误提示文本 "B 类必须 RC-/V- 格式"
   直接告诉模型 "EV/FN 不合法" → 模型不敢用真 EV/FN.

加: `evidence_verify._find_rule_reference` / `_verify_b_class_semantic`
也漏 regex → worker 写 EV-01 依据时被判 retract.

加: `_DEFAULT_REVIEW_DIMENSIONS` yaml 加载失败 fallback 没含 FN/EV → 兜底丢规则.

修法 (2026-04-27 P0-B):
- 4 处 regex 全统一 `(?:RC|V|EV|FN)-\\d+`
- 错误提示文本扩 EV-/FN- 列出
- _DEFAULT_REVIEW_DIMENSIONS 三维度补 FN/EV checklist + rules

本测试覆盖 4 类断言:
- yaml 加载真把 FN/EV id 进 dim.checklist (校准 yaml 修法 a45e3dd)
- _DEFAULT_REVIEW_DIMENSIONS 含 FN-01/03/09 + EV-01/04 (yaml fallback 兜底)
- prompting._build_real_refs_section regex 真识别 EV/FN
- prompting._build_real_refs_section 错误提示真含 EV/FN
- evidence_verify._find_rule_reference / _verify_b_class_semantic 真接 EV/FN
"""
from __future__ import annotations

import os
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ============================================================
# 1. yaml 加载真把 EV/FN 进 dim.checklist
# ============================================================


class TestYamlLoadIncludesFnEv:
    """yaml 真把 FN-01/03/09 + EV-01/04 加载进 dim.checklist (校验 a45e3dd commit)."""

    def test_structure_contains_ev01_fn09(self):
        from review.dimensions import load_review_dimensions
        # 不过 lru_cache, 直接调底层
        dims, _ = load_review_dimensions(workspace=None)
        rids = [r["rule_id"] for r in dims["structure"]["checklist"]]
        assert "EV-01" in rids, f"structure dim 应含 EV-01, 实际 {rids}"
        assert "FN-09" in rids, f"structure dim 应含 FN-09, 实际 {rids}"

    def test_ai_coding_contains_fn03(self):
        from review.dimensions import load_review_dimensions
        dims, _ = load_review_dimensions(workspace=None)
        rids = [r["rule_id"] for r in dims["ai_coding"]["checklist"]]
        assert "FN-03" in rids, f"ai_coding dim 应含 FN-03, 实际 {rids}"

    def test_data_quality_contains_ev04_fn01(self):
        from review.dimensions import load_review_dimensions
        dims, _ = load_review_dimensions(workspace=None)
        rids = [r["rule_id"] for r in dims["data_quality"]["checklist"]]
        assert "EV-04" in rids, f"data_quality dim 应含 EV-04, 实际 {rids}"
        assert "FN-01" in rids, f"data_quality dim 应含 FN-01, 实际 {rids}"


# ============================================================
# 2. _DEFAULT_REVIEW_DIMENSIONS fallback 测试已删除 (step 3.2, 2026-04-27)
# ============================================================
#
# 历史: P0-B 时这里有 4 个测试锁死 _DEFAULT_REVIEW_DIMENSIONS 含 EV/FN.
# step 3.2 删了 _DEFAULT_REVIEW_DIMENSIONS 硬编码 fallback (反模式根因 — 与 yaml 漂移).
# yaml 加载失败的新行为: 返回空 dict + warn (或 PECKER_SCHEMA_FALLBACK=1 兜底空).
#
# yaml 真路径含 EV/FN 的 P0-B 防回归:
# - 上方 TestYamlLoadIncludesFnEv 已锁死 yaml 真路径含 EV/FN.
# - tests/test_dimensions_registry_wiring.py::test_yaml_loaded_rules_include_v_rc_ev_fn
#   也锁死 4 前缀都被 yaml 加载.


# ============================================================
# 3. prompting._build_real_refs_section regex 真识别 EV/FN id
# ============================================================


class TestPromptingRealRefsExtractsFnEv:
    """workspace/review-rules/ 含 EV/FN id 时, _build_real_refs_section 应扫到."""

    def test_real_refs_extracts_ev_fn_from_yaml(self, tmp_path):
        ws = tmp_path / "ws"
        rules_dir = ws / "review-rules"
        rules_dir.mkdir(parents=True)
        # 模拟一个 yaml 含 EV/FN id
        (rules_dir / "test-rules.yaml").write_text(
            "rule_id: V-02\nrule_id: RC-005\nrule_id: EV-01\nrule_id: FN-01\nrule_id: FN-09\n",
            encoding="utf-8",
        )
        from review.prompting import _build_real_refs_section
        text = _build_real_refs_section(str(ws))
        # P0-B 修法: regex 应扫到 EV-/FN- 也算合法
        assert "EV-01" in text, (
            "_build_real_refs_section 应识别 EV-01 — "
            "P0-B 修法漏改 prompting.py:292 的 regex"
        )
        assert "FN-01" in text, "应识别 FN-01"
        assert "FN-09" in text, "应识别 FN-09"
        assert "V-02" in text  # 老的 V- 也仍要在
        assert "RC-005" in text  # 老的 RC- 也仍要在

    def test_real_refs_error_text_mentions_fn_ev(self, tmp_path):
        """错误提示文本应明确告诉模型 EV-/FN- 也合法, 不能只说 RC-/V-."""
        ws = tmp_path / "ws"
        rules_dir = ws / "review-rules"
        rules_dir.mkdir(parents=True)
        (rules_dir / "test.yaml").write_text("rule_id: V-02\n", encoding="utf-8")
        from review.prompting import _build_real_refs_section
        text = _build_real_refs_section(str(ws))
        # P0-B 修法: 错误提示文本也要扩
        assert "EV-" in text, (
            "错误提示文本应明确写 EV- 是合法格式 — "
            "P0-B 修法漏改 prompting.py:323 的 文本"
        )
        assert "FN-" in text, "错误提示文本应明确写 FN- 是合法格式"


# ============================================================
# 4. prompting._build_feedback_section regex 真识别 EV/FN
# ============================================================


class TestPromptingFeedbackSectionExtractsFnEv:
    """rule_perf 反馈循环里 EV-/FN- 应能进入维度规则集合."""

    def test_dim_rule_ids_includes_ev_fn(self, tmp_path):
        """_build_feedback_section 调 re.findall(r'(?:RC|V|EV|FN)-\\d+', dim_rules_text)
        应能从规则文本中扫到 EV/FN id, 让 EV/FN 历史能进 prompt."""
        from review.prompting import _build_feedback_section

        # 模拟 dimensions dict (含 EV/FN id 的 rules 文本)
        fake_dims = {
            "structure": {
                "rules": "V-02 fmt. EV-01 验收标准. FN-09 移动端对齐.",
                "checklist": [],
            },
        }
        # rule_perf_history 真带 EV/FN entry, 让 trigger 路径走通
        rule_perf = {
            "EV-01": {
                "stats": {"total": 10, "missed": 3},  # missed > 2 trigger
                "rejection_rate": 0.1,
                "name": "验收标准",
            },
            "FN-09": {
                "stats": {"total": 10, "missed": 1},
                "rejection_rate": 0.5,  # > 0.3 trigger
                "name": "移动端对齐",
            },
            "V-02": {  # 控制项: V-02 也能扫到
                "stats": {"total": 10, "missed": 0},
                "rejection_rate": 0.4,
                "name": "格式",
            },
        }
        text = _build_feedback_section("structure", rule_perf_history=rule_perf, dimensions=fake_dims)
        # 应该真出现在反馈段里, 非空
        assert text, "_build_feedback_section 应返回非空 (EV-01 / FN-09 trigger 后被加入 flagged)"
        assert "EV-01" in text, (
            "rule_perf 里 EV-01 应进入反馈段 — "
            "P0-B 修法漏改 prompting.py:151 的 regex"
        )
        assert "FN-09" in text, "rule_perf 里 FN-09 应进入反馈段"


# ============================================================
# 5. evidence_verify regex 也接 EV/FN id
# ============================================================


class TestEvidenceVerifyAcceptsFnEv:
    """evidence_verify._find_rule_reference / _verify_b_class_semantic
    应识别 EV-/FN- id, 不再判 retract."""

    def test_find_rule_reference_accepts_ev01(self, tmp_path):
        rules_dir = tmp_path / "review-rules"
        rules_dir.mkdir()
        # rule 文件真含 EV-01 (模拟 review-dimensions.yaml 里的 entry)
        (rules_dir / "rules.yaml").write_text("EV-01 验收标准\n", encoding="utf-8")

        from review.evidence_verify import _find_rule_reference
        # evidence_content 引用 EV-01, 应找到不 retract
        assert _find_rule_reference("依据 EV-01 验收标准缺失", str(rules_dir)) is True

    def test_find_rule_reference_accepts_fn01(self, tmp_path):
        rules_dir = tmp_path / "review-rules"
        rules_dir.mkdir()
        (rules_dir / "rules.yaml").write_text("FN-01 ds_risk 三段过滤\n", encoding="utf-8")

        from review.evidence_verify import _find_rule_reference
        assert _find_rule_reference("依据 FN-01 缺三段过滤", str(rules_dir)) is True

    def test_find_rule_reference_no_ev_in_content_returns_false(self, tmp_path):
        """没引用任何 rule_id → False (老语义不变)."""
        rules_dir = tmp_path / "review-rules"
        rules_dir.mkdir()
        (rules_dir / "rules.yaml").write_text("FN-01\n", encoding="utf-8")

        from review.evidence_verify import _find_rule_reference
        assert _find_rule_reference("依据缺失没引用任何规则", str(rules_dir)) is False

    def test_verify_b_class_semantic_accepts_fn09(self, tmp_path):
        """_verify_b_class_semantic 引用 FN-09 时不应直接 fail (能找到 rule_id)."""
        rules_dir = tmp_path / "review-rules"
        rules_dir.mkdir()
        # rule 原文跟 item issue 有 keyword overlap (移动端 / Web 端)
        (rules_dir / "fn-09.yaml").write_text(
            "FN-09 移动端 uni-app 与 Web 端必显式对齐 复用 隐式引用\n", encoding="utf-8",
        )

        from review.evidence_verify import _verify_b_class_semantic
        item = {
            "issue": "移动端章节复用 Web 端 隐式引用",
            "suggestion": "显式标注每个移动端页面",
            "evidence_content": "FN-09 移动端必须显式对齐",
        }
        passed, note = _verify_b_class_semantic(item, str(rules_dir))
        # P0-B 修法: regex 接 FN- 后, rule_ids 非空, 走 rule_text 加载逻辑.
        # 真 rule 找到 + keyword overlap >= 阈值 → passed=True
        assert passed is True, f"FN-09 引用不应判语义薄弱, note={note}"


# ============================================================
# 6. SUBMIT_REVIEW_ITEMS_TOOL schema 不卡 FN/EV (no enum on rule_id)
# ============================================================


class TestSubmitToolSchemaAcceptsFnEv:
    """worker tool schema 的 rule_id 字段没有 enum 限制, 不会拒掉 EV-/FN- 提交."""

    def test_rule_id_field_no_enum(self):
        from review.worker import SUBMIT_REVIEW_ITEMS_TOOL
        rule_id_schema = (
            SUBMIT_REVIEW_ITEMS_TOOL["input_schema"]["properties"]["items"]
                ["items"]["properties"]["rule_id"]
        )
        # 没 enum, 让 worker 自由提交合法 id (V/RC/EV/FN), 由 _postprocess_items 校验
        assert "enum" not in rule_id_schema, (
            "rule_id 不应有 enum 限制, 否则 EV/FN 会被 schema 拒"
        )
        assert rule_id_schema.get("type") == "string"


# ============================================================
# 7. dimensions.py schema regex 真接 EV/FN
# ============================================================


class TestSchemaRegexAcceptsFnEv:
    """_REVIEW_DIMENSIONS_SCHEMA 的 rule_id pattern 真允许 EV-/FN-."""

    def test_schema_regex_pattern(self):
        from review.dimensions import _REVIEW_DIMENSIONS_SCHEMA
        pattern = (
            _REVIEW_DIMENSIONS_SCHEMA["properties"]["dimensions"]
                ["additionalProperties"]["properties"]["checklist"]["items"]
                ["properties"]["rule_id"]["pattern"]
        )
        # P0-B 校准: pattern 必须接 V/RC/EV/FN 四种前缀
        for rid in ("V-02", "RC-005", "EV-01", "FN-09", "FN-01", "FN-03"):
            assert re.match(pattern, rid), (
                f"schema regex {pattern} 应允许 {rid}, 实际拒绝"
            )
        # 反例: 幻觉 ID 应该被拒
        for bad in ("DQ-01", "AC-01", "ABC-1"):
            assert not re.match(pattern, bad), (
                f"schema regex 应拒幻觉 ID {bad}, 实际接受"
            )
