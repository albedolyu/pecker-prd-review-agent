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
