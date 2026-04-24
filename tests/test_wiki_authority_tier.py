"""T1: Wiki frontmatter v2 — `_wiki_authority_tier` 四级分层 + 冷启动映射 (2026-04-24).

spec: docs/wiki-frontmatter-v2.md

测试矩阵:
- IOError / 无 frontmatter → contextual (保留老 _is_pecker_generated 返回 False 语义)
- sources:0 → generated (硬性约束, 即使有显式 authority: canonical)
- 显式 authority 合法 → 原样返回
- 冷启动映射: sources>=1 + verified_by 空 → contextual
- 冷启动映射: sources>=1 + verified_by 有 → trusted
- _is_pecker_generated 向后兼容 thin wrapper: generated → True, 其他 → False
"""
from __future__ import annotations

import pytest

from review.evidence_verify import (
    _VALID_AUTHORITY,
    _is_pecker_generated,
    _parse_wiki_frontmatter,
    _wiki_authority_tier,
)


# ============================================================
# 工具: 生成测试 wiki 文件
# ============================================================

def _write_wiki(tmp_path, name, frontmatter_lines):
    """在 tmp_path 下写一个带 frontmatter 的 md 文件."""
    wiki = tmp_path / name
    content = "---\n" + "\n".join(frontmatter_lines) + "\n---\n\n# Test wiki\n"
    wiki.write_text(content, encoding="utf-8")
    return wiki


# ============================================================
# _parse_wiki_frontmatter
# ============================================================

class TestParseWikiFrontmatter:
    def test_empty_file(self, tmp_path):
        """空文件 → {} (没有 frontmatter 包围块)."""
        p = tmp_path / "empty.md"
        p.write_text("", encoding="utf-8")
        assert _parse_wiki_frontmatter(str(p)) == {}

    def test_no_frontmatter(self, tmp_path):
        """普通 md 无 --- → {}."""
        p = tmp_path / "plain.md"
        p.write_text("# Title\n\nSome content\n", encoding="utf-8")
        assert _parse_wiki_frontmatter(str(p)) == {}

    def test_nonexistent_file(self, tmp_path):
        """不存在的文件 → {} (OSError 兜底)."""
        assert _parse_wiki_frontmatter(str(tmp_path / "nope.md")) == {}

    def test_basic_kv(self, tmp_path):
        """基础 key: value 解析."""
        p = _write_wiki(tmp_path, "x.md", [
            "title: Foo",
            "sources: 2",
            "authority: canonical",
        ])
        fm = _parse_wiki_frontmatter(str(p))
        assert fm["title"] == "Foo"
        assert fm["sources"] == "2"
        assert fm["authority"] == "canonical"


# ============================================================
# _wiki_authority_tier 主逻辑
# ============================================================

class TestWikiAuthorityTier:
    def test_nonexistent_file_returns_contextual(self, tmp_path):
        """IOError 兜底 → contextual (保留老 _is_pecker_generated 返 False 语义)."""
        result = _wiki_authority_tier(str(tmp_path / "nope.md"))
        assert result == "contextual"

    def test_no_frontmatter_returns_contextual(self, tmp_path):
        """有文件但没 frontmatter → contextual."""
        p = tmp_path / "plain.md"
        p.write_text("# Just markdown\n", encoding="utf-8")
        assert _wiki_authority_tier(str(p)) == "contextual"

    def test_sources_zero_forces_generated(self, tmp_path):
        """sources:0 硬性约束 → generated, 忽略其他字段."""
        p = _write_wiki(tmp_path, "x.md", [
            "sources: 0",
            "authority: canonical",   # 矛盾声明, 被硬性约束覆盖
            "verified_by: PM",
        ])
        assert _wiki_authority_tier(str(p)) == "generated"

    def test_explicit_canonical(self, tmp_path):
        """显式 canonical + sources>=1 → canonical."""
        p = _write_wiki(tmp_path, "x.md", [
            "sources: 2",
            "authority: canonical",
            "verified_by: 数据",
        ])
        assert _wiki_authority_tier(str(p)) == "canonical"

    def test_explicit_trusted(self, tmp_path):
        p = _write_wiki(tmp_path, "x.md", [
            "sources: 1",
            "authority: trusted",
            "verified_by: PM",
        ])
        assert _wiki_authority_tier(str(p)) == "trusted"

    def test_explicit_contextual(self, tmp_path):
        p = _write_wiki(tmp_path, "x.md", [
            "sources: 1",
            "authority: contextual",
        ])
        assert _wiki_authority_tier(str(p)) == "contextual"

    def test_explicit_generated(self, tmp_path):
        """显式 generated + sources>=1 (罕见但合法) → generated."""
        p = _write_wiki(tmp_path, "x.md", [
            "sources: 1",
            "authority: generated",
        ])
        assert _wiki_authority_tier(str(p)) == "generated"

    def test_invalid_authority_falls_back_to_default_mapping(self, tmp_path):
        """authority: 某非法值 + sources>=1 + 无 verified_by → contextual (默认映射)."""
        p = _write_wiki(tmp_path, "x.md", [
            "sources: 1",
            "authority: bogus_tier",
        ])
        assert _wiki_authority_tier(str(p)) == "contextual"

    def test_cold_start_without_verified_by(self, tmp_path):
        """sources>=1 + 无 authority + 无 verified_by → contextual (默认映射)."""
        p = _write_wiki(tmp_path, "x.md", [
            "sources: 1",
        ])
        assert _wiki_authority_tier(str(p)) == "contextual"

    def test_cold_start_with_verified_by(self, tmp_path):
        """sources>=1 + 无 authority + 有 verified_by → trusted (默认映射)."""
        p = _write_wiki(tmp_path, "x.md", [
            "sources: 1",
            "verified_by: 研发",
        ])
        assert _wiki_authority_tier(str(p)) == "trusted"

    def test_non_int_sources_falls_through_to_default(self, tmp_path):
        """sources 字段非整数 (list / 奇怪格式) → 不视为 0, 走默认映射 → contextual."""
        p = _write_wiki(tmp_path, "x.md", [
            "sources: [url1, url2]",    # list 格式, int() 抛 ValueError
        ])
        # 有 list 格式的 sources, 表达"有来源", 不该强制 generated
        assert _wiki_authority_tier(str(p)) == "contextual"

    def test_sources_missing_falls_through_to_default(self, tmp_path):
        """没有 sources 字段 → 走默认映射, 不强制 generated (与老 _is_pecker_generated 行为等价)."""
        p = _write_wiki(tmp_path, "x.md", [
            "title: 只有 title 没 sources",
        ])
        # 老 `_is_pecker_generated` 的 `^sources:\s*0\s*$` 正则只匹配显式 "sources: 0",
        # 缺失 sources 时返回 False → 文件不是 pecker-generated → 进 wiki_index
        assert _wiki_authority_tier(str(p)) == "contextual"

    def test_pm_curated_without_sources_matches_legacy(self, tmp_path):
        """PM 手工维护但没显式声 sources 的文件 → 不该判成 generated (回归 test_evidence_verify_wiki_sparse 场景)."""
        p = _write_wiki(tmp_path, "pm.md", [
            "author: pm",
        ])
        assert _wiki_authority_tier(str(p)) == "contextual"
        from review.evidence_verify import _is_pecker_generated
        assert _is_pecker_generated(str(p)) is False   # 与老正则 `^sources:\s*0\s*$` 语义一致


# ============================================================
# _is_pecker_generated 向后兼容 thin wrapper
# ============================================================

class TestIsPeckerGeneratedBackwardCompat:
    def test_generated_returns_true(self, tmp_path):
        p = _write_wiki(tmp_path, "x.md", ["sources: 0"])
        assert _is_pecker_generated(str(p)) is True

    def test_canonical_returns_false(self, tmp_path):
        p = _write_wiki(tmp_path, "x.md", [
            "sources: 2",
            "authority: canonical",
        ])
        assert _is_pecker_generated(str(p)) is False

    def test_trusted_returns_false(self, tmp_path):
        p = _write_wiki(tmp_path, "x.md", [
            "sources: 1",
            "verified_by: PM",
        ])
        assert _is_pecker_generated(str(p)) is False

    def test_contextual_returns_false(self, tmp_path):
        p = _write_wiki(tmp_path, "x.md", ["sources: 1"])
        assert _is_pecker_generated(str(p)) is False

    def test_nonexistent_file_returns_false(self, tmp_path):
        """IOError → contextual tier → wrapper returns False. 与老行为 (IOError return False) 等价."""
        assert _is_pecker_generated(str(tmp_path / "nope.md")) is False


# ============================================================
# _VALID_AUTHORITY sanity check
# ============================================================

def test_valid_authority_set():
    """Guardrail: 任何未来 enum 扩展需要同步更新 _VALID_AUTHORITY."""
    assert _VALID_AUTHORITY == {"canonical", "trusted", "contextual", "generated"}
