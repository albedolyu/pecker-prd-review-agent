"""claim-level provenance 模块单测.

覆盖 review/claim_provenance.py 的两个核心函数:
- parse_claim_markers: 把文本切成 Claim list, 提 ^[xxx] 标
- lint_wiki_claims: 对 generated/contextual wiki 扫 untagged 强断言

设计参考: obsidian-wiki (Ar9av/obsidian-wiki) 的 inline marker 语法.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from review.claim_provenance import (
    Claim,
    ClaimLintWarning,
    lint_wiki_claims,
    parse_claim_markers,
)


# ---------------------------------------------------------------------------
# parse_claim_markers - 基础切分
# ---------------------------------------------------------------------------


def test_parse_no_marker_single_sentence():
    """无 marker 的单句, 应得 1 个 untagged claim."""
    claims = parse_claim_markers("风鸟前端用 Vue3 + uni-app。")
    assert len(claims) == 1
    assert claims[0].tag == "untagged"
    assert "Vue3" in claims[0].text


def test_parse_single_marker():
    """单个 ^[verified] marker, tag 应被识别."""
    text = "风鸟前端用 Vue3 + uni-app^[verified]。"
    claims = parse_claim_markers(text)
    assert len(claims) == 1
    assert claims[0].tag == "verified"
    # text 字段不带 marker
    assert "^[" not in claims[0].text


def test_parse_multiple_markers_mixed():
    """三种 tag 在同一段, 各句独立 tag."""
    text = (
        "风鸟前端用 Vue3 + uni-app^[verified]。"
        "状态管理用 Pinia^[inferred]。"
        "路由配置在 pages.json^[verified]。"
        "监控方案待确认^[ambiguous]。"
    )
    claims = parse_claim_markers(text)
    tags = [c.tag for c in claims]
    assert tags == ["verified", "inferred", "verified", "ambiguous"]


def test_parse_marker_with_inner_space():
    """marker 中间允许空白 (^[ verified ]), 仍能识别."""
    text = "数据库用 MySQL^[ verified ]。"
    claims = parse_claim_markers(text)
    assert len(claims) == 1
    assert claims[0].tag == "verified"


def test_parse_marker_before_and_after_punctuation():
    """marker 在断句符前/后均合法; 句中无 marker 视为 untagged."""
    text = "A 是 1^[verified]。B 是 2。C 是 3^[inferred]！"
    claims = parse_claim_markers(text)
    tags = [c.tag for c in claims]
    assert tags == ["verified", "untagged", "inferred"]


def test_parse_chinese_english_mixed():
    """中英文混排, 中文「。」+英文「.」都按断句符切分."""
    text = (
        "风鸟前端用 Vue3^[verified]。"
        "Backend uses Spring Boot^[inferred]. "
        "API gateway is nginx^[verified]."
    )
    claims = parse_claim_markers(text)
    assert len(claims) == 3
    assert [c.tag for c in claims] == ["verified", "inferred", "verified"]
    # 验证 text 字段不含 marker
    assert all("^[" not in c.text for c in claims)


# ---------------------------------------------------------------------------
# lint_wiki_claims - frontmatter / authority gating
# ---------------------------------------------------------------------------


def test_lint_generated_with_untagged_assertion_warns(tmp_path: Path):
    """generated 级 wiki 含强断言但没 marker → warn."""
    f = tmp_path / "概念-x.md"
    f.write_text(
        "---\n"
        "title: x\n"
        "authority: generated\n"
        "sources: 0\n"
        "---\n\n"
        "# 概念-x\n\n"
        "侵权软件每日上限是 5 张。\n",
        encoding="utf-8",
    )
    warnings = lint_wiki_claims(f, authority="generated")
    assert len(warnings) >= 1
    assert all(isinstance(w, ClaimLintWarning) for w in warnings)
    # 应该报 untagged_factual_claim
    reasons = {w.reason for w in warnings}
    assert "untagged_factual_claim" in reasons


def test_lint_canonical_skips_check(tmp_path: Path):
    """canonical 级 wiki 即使有 untagged 强断言也不扫."""
    f = tmp_path / "概念-x.md"
    f.write_text(
        "---\n"
        "title: x\n"
        "authority: canonical\n"
        "sources: 3\n"
        "---\n\n"
        "侵权软件每日上限是 5 张。\n",
        encoding="utf-8",
    )
    warnings = lint_wiki_claims(f, authority="canonical")
    assert warnings == []


def test_lint_skips_frontmatter_content(tmp_path: Path):
    """frontmatter 内的 key: value 不算 claim, 不应被扫."""
    f = tmp_path / "概念-x.md"
    # frontmatter 里 title 是 "数据库用 MySQL", 含强断言关键词
    # 但应被跳过 — 只有正文那句无标的强断言被报
    f.write_text(
        "---\n"
        "title: 数据库用 MySQL\n"
        "authority: contextual\n"
        "sources: 1\n"
        "---\n\n"
        "# x\n\n"
        "本节无强断言句子。\n",
        encoding="utf-8",
    )
    warnings = lint_wiki_claims(f, authority="contextual")
    # frontmatter 那行不该被算成 untagged claim
    assert all("数据库用 MySQL" not in w.claim_text for w in warnings)


def test_lint_tagged_assertions_dont_warn(tmp_path: Path):
    """正文中所有强断言都标了 marker → 0 warn."""
    f = tmp_path / "概念-x.md"
    f.write_text(
        "---\n"
        "title: x\n"
        "authority: generated\n"
        "---\n\n"
        "侵权软件每日上限是 5 张^[verified]。\n"
        "采用 MySQL^[inferred]。\n",
        encoding="utf-8",
    )
    warnings = lint_wiki_claims(f, authority="generated")
    assert warnings == []


def test_lint_returns_warnings_sorted_by_line(tmp_path: Path):
    """多条 warning 按 line 升序返回."""
    f = tmp_path / "概念-x.md"
    f.write_text(
        "---\n"
        "title: x\n"
        "authority: generated\n"
        "---\n\n"
        "采用 Vue3。\n"
        "\n"
        "数据库是 MySQL。\n"
        "\n"
        "上限为 10 张/天。\n",
        encoding="utf-8",
    )
    warnings = lint_wiki_claims(f, authority="generated")
    assert len(warnings) >= 2
    lines = [w.line for w in warnings]
    assert lines == sorted(lines)


def test_lint_real_workspace_wiki_smoke(tmp_path: Path):
    """fixture 测: 真业务样态的 wiki (中英混合 + 表格 + frontmatter) 不崩."""
    f = tmp_path / "约束-x.md"
    f.write_text(
        "---\n"
        "title: ds_risk_x\n"
        "authority: generated\n"
        "sources: 0\n"
        "category: constraint\n"
        "---\n\n"
        "# 约束-ds_risk_x\n\n"
        "数据库类型是 MySQL。\n"
        "默认排序采用 publish_date DESC^[verified]。\n",
        encoding="utf-8",
    )
    warnings = lint_wiki_claims(f, authority="generated")
    # 第一句无 marker → warn; 第二句有 marker → 不 warn
    untagged = [w for w in warnings if w.reason == "untagged_factual_claim"]
    assert len(untagged) >= 1
    assert all("publish_date" not in w.claim_text for w in untagged)


# ---------------------------------------------------------------------------
# 假阳白名单 — UI 通用能力短句 + 工具自述行 (2026-04-26 patch)
# ---------------------------------------------------------------------------


def test_lint_skips_ui_capability_short_phrases(tmp_path: Path):
    """UI 通用能力短句不应被识别为强断言 (5 条假阳的代表 4 条).

    场景: workspace-侵权软件/wiki/场景-企业主页侵权软件.md 行 59/92/96/102
    这种 "- 支持 X 切换/导出/筛选/反馈" 只有动词+对象的列表项不是事实断言.
    """
    f = tmp_path / "场景-x.md"
    f.write_text(
        "---\n"
        "title: x\n"
        "authority: generated\n"
        "sources: 0\n"
        "---\n\n"
        "# 场景-x\n\n"
        "### 列表能力\n\n"
        "- 支持升降序排序切换\n"
        "- 支持用户反馈侵权软件数据问题\n"
        "- 支持维度数据导出\n"
        "- 支持单维度数据导出\n",
        encoding="utf-8",
    )
    warnings = lint_wiki_claims(f, authority="generated")
    # 这 4 条 list bullet 全是 UI 通用能力, 不应被 warn
    assert warnings == [], (
        f"UI capability short phrases should not warn, got {warnings}"
    )


def test_lint_skips_tool_self_description(tmp_path: Path):
    """工具自述行 (鸮鹦/啄木鸟自动创建 placeholder) 不应被识别.

    场景: workspace-侵权软件/wiki/实体-风鸟平台.md 行 15.
    """
    f = tmp_path / "实体-x.md"
    f.write_text(
        "---\n"
        "title: x\n"
        "authority: generated\n"
        "sources: 0\n"
        "---\n\n"
        "# 实体-风鸟平台\n\n"
        "> 此页面由鸮鹦自动创建，因为有其他页面引用了 [[实体-风鸟平台]] 但该页面不存在。\n"
        "> 请补充具体内容。\n",
        encoding="utf-8",
    )
    warnings = lint_wiki_claims(f, authority="generated")
    # 自述行被跳过, 此页面应 0 warn
    assert warnings == [], (
        f"Tool self-description line should not warn, got {warnings}"
    )


def test_lint_keeps_real_factual_claims(tmp_path: Path):
    """回归: 真因果断言/数字断言/字段定义仍被识别 (≥ 4 warn).

    覆盖之前 23 条 patch 中的代表样态 (去 marker 模拟漏标场景):
    - 数据来源断言 (数据来源为 X)
    - 数字上限断言 (上限为 5 张/天)
    - 字段类型断言 (类型为 tinyint(1))
    - 业务行为断言 (默认排序采用 X)
    - 字段含义断言 (riskbird_status 是 X)
    """
    f = tmp_path / "概念-x.md"
    f.write_text(
        "---\n"
        "title: x\n"
        "authority: generated\n"
        "sources: 0\n"
        "---\n\n"
        "# 概念-x\n\n"
        "数据来源为工信部官网发布的通报。\n"
        "侵权软件每日上限为 5 张。\n"
        "riskbird_status 类型为 tinyint(1)。\n"
        "默认排序采用 publish_date DESC。\n"
        "riskbird_status 是侵权软件主表的状态控制字段。\n",
        encoding="utf-8",
    )
    warnings = lint_wiki_claims(f, authority="generated")
    # 这 5 条都是真断言, 至少 4 条要被识别 (留一格弹性, 防启发式微调误伤)
    assert len(warnings) >= 4, (
        f"Real factual claims should still be warned (>=4), got {len(warnings)}: "
        f"{[w.claim_text for w in warnings]}"
    )


def test_lint_ui_capability_with_concrete_value_still_warns(tmp_path: Path):
    """边界: UI 短句若带具体值断言 ('支持 X 切换为 ASC') 仍应 warn.

    防止 Rule A 过宽误伤真正的事实断言.
    """
    f = tmp_path / "场景-x.md"
    f.write_text(
        "---\n"
        "title: x\n"
        "authority: generated\n"
        "sources: 0\n"
        "---\n\n"
        "# x\n\n"
        "支持前端切换为升序（ASC）。\n",
        encoding="utf-8",
    )
    warnings = lint_wiki_claims(f, authority="generated")
    # 这句有具体值 (升序/ASC), 仍应 warn
    assert len(warnings) >= 1, (
        f"Concrete value assertion should still warn, got {warnings}"
    )
