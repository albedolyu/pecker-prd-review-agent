"""T4 wiki_lint + wiki_migrate_v2 单测 (2026-04-24).

不跑 CLI 入口, 直接测里面的纯函数 + lint 规则 + migrate 提议.
"""
from __future__ import annotations

import os
import sys

import pytest


_SCRIPTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "scripts"))
sys.path.insert(0, _SCRIPTS_DIR)


def _write_wiki(tmp_path, name, fm_lines):
    wiki_dir = tmp_path / "wiki"
    wiki_dir.mkdir(exist_ok=True)
    p = wiki_dir / name
    content = "---\n" + "\n".join(fm_lines) + "\n---\n\n# content\n"
    p.write_text(content, encoding="utf-8")
    return p


# ============================================================
# wiki_lint
# ============================================================

class TestWikiLintFile:
    def test_missing_fields_warn(self, tmp_path):
        from wiki_lint import lint_wiki_file
        p = _write_wiki(tmp_path, "x.md", ["title: Foo"])
        warnings = lint_wiki_file(str(p))
        # 缺 authority / owner / sources
        assert any("authority" in w for w in warnings)
        assert any("owner" in w for w in warnings)
        assert any("sources" in w for w in warnings)

    def test_sources_zero_canonical_conflict(self, tmp_path):
        from wiki_lint import lint_wiki_file
        p = _write_wiki(tmp_path, "x.md", [
            "title: Foo", "authority: canonical", "owner: albedolyu",
            "sources: 0", "last_verified: 2026-04-24", "verified_by: PM",
        ])
        warnings = lint_wiki_file(str(p))
        assert any("sources:0 但 authority=canonical" in w for w in warnings)

    def test_canonical_sources_lt_2(self, tmp_path):
        from wiki_lint import lint_wiki_file
        p = _write_wiki(tmp_path, "x.md", [
            "title: Foo", "authority: canonical", "owner: albedolyu",
            "sources: 1", "last_verified: 2026-04-24", "verified_by: PM",
        ])
        warnings = lint_wiki_file(str(p))
        assert any("sources>=2" in w for w in warnings)

    def test_trusted_missing_last_verified(self, tmp_path):
        from wiki_lint import lint_wiki_file
        p = _write_wiki(tmp_path, "x.md", [
            "title: Foo", "authority: trusted", "owner: albedolyu",
            "sources: 1", "verified_by: PM",
        ])
        warnings = lint_wiki_file(str(p))
        assert any("last_verified, 未填" in w for w in warnings)

    def test_trusted_expired_verification(self, tmp_path):
        from wiki_lint import lint_wiki_file
        # 2 年前验证, trusted 过期
        p = _write_wiki(tmp_path, "x.md", [
            "title: Foo", "authority: trusted", "owner: albedolyu",
            "sources: 1", "last_verified: 2024-01-01", "verified_by: PM",
        ])
        warnings = lint_wiki_file(str(p))
        assert any("last_verified=2024-01-01" in w and "已" in w for w in warnings)

    def test_invalid_date_format_warn(self, tmp_path):
        from wiki_lint import lint_wiki_file
        p = _write_wiki(tmp_path, "x.md", [
            "title: Foo", "authority: trusted", "owner: albedolyu",
            "sources: 1", "last_verified: 26-04-24",   # 格式错
        ])
        warnings = lint_wiki_file(str(p))
        assert any("格式非 YYYY-MM-DD" in w for w in warnings)

    def test_all_fields_present_clean(self, tmp_path):
        """完整 frontmatter → 没 warning."""
        from wiki_lint import lint_wiki_file
        today = "2026-04-24"
        p = _write_wiki(tmp_path, "x.md", [
            "title: Foo", "authority: trusted", "owner: albedolyu",
            "sources: 2", f"last_verified: {today}", "verified_by: PM",
        ])
        assert lint_wiki_file(str(p)) == []

    def test_no_frontmatter(self, tmp_path):
        """完全没 frontmatter → 一条 warning."""
        from wiki_lint import lint_wiki_file
        wiki_dir = tmp_path / "wiki"
        wiki_dir.mkdir()
        p = wiki_dir / "plain.md"
        p.write_text("# just content\n", encoding="utf-8")
        warnings = lint_wiki_file(str(p))
        assert len(warnings) == 1
        assert "frontmatter 解析失败" in warnings[0]


class TestWikiLintWorkspace:
    def test_empty_workspace(self, tmp_path):
        """没 wiki 目录 → 空 distribution + 空 warnings."""
        from wiki_lint import lint_workspace
        dist, warnings = lint_workspace(str(tmp_path))
        assert dist == {}
        assert warnings == []

    def test_skip_meta_files(self, tmp_path):
        """log.md / index.md 跳过."""
        from wiki_lint import lint_workspace
        wiki_dir = tmp_path / "wiki"
        wiki_dir.mkdir()
        (wiki_dir / "log.md").write_text("---\nsources: 0\n---\n", encoding="utf-8")
        (wiki_dir / "business.md").write_text("---\nsources: 1\n---\n", encoding="utf-8")
        dist, _warnings = lint_workspace(str(tmp_path))
        # 只 business.md 进 distribution, log.md 不算
        assert sum(dist.values()) == 1


# ============================================================
# wiki_migrate_v2 dry-run
# ============================================================

class TestWikiMigrateDryRun:
    def test_propose_for_missing_authority(self, tmp_path):
        """没 authority 字段 → 建议加 (tier 与冷启动一致)."""
        from wiki_migrate_v2 import propose_frontmatter_delta
        p = _write_wiki(tmp_path, "x.md", ["sources: 0"])
        current, proposed, new_fields = propose_frontmatter_delta(str(p))
        assert current == "generated"
        assert proposed == "generated"
        assert new_fields["authority"] == "generated"
        assert new_fields["owner"] == "pecker-auto"   # generated 归 pecker-auto

    def test_trusted_gets_last_verified(self, tmp_path):
        """trusted tier 且没 last_verified → 建议补 今天日期."""
        from wiki_migrate_v2 import propose_frontmatter_delta
        p = _write_wiki(tmp_path, "x.md", [
            "sources: 1", "verified_by: PM",   # 冷启动推导 → trusted
        ])
        current, _proposed, new_fields = propose_frontmatter_delta(str(p))
        assert current == "trusted"
        assert "last_verified" in new_fields

    def test_contextual_no_last_verified(self, tmp_path):
        """contextual tier → 不补 last_verified (不强制)."""
        from wiki_migrate_v2 import propose_frontmatter_delta
        p = _write_wiki(tmp_path, "x.md", ["sources: 1"])
        current, _proposed, new_fields = propose_frontmatter_delta(str(p))
        assert current == "contextual"
        assert "last_verified" not in new_fields

    def test_existing_authority_not_overridden(self, tmp_path):
        """显式 authority 的 wiki → new_fields 不含 authority key."""
        from wiki_migrate_v2 import propose_frontmatter_delta
        p = _write_wiki(tmp_path, "x.md", [
            "sources: 2", "authority: canonical", "verified_by: 数据",
            "last_verified: 2026-04-24", "owner: albedolyu",
        ])
        _current, _proposed, new_fields = propose_frontmatter_delta(str(p))
        # 所有字段都齐, new_fields 空
        assert new_fields == {}

    def test_scan_workspace_groups_changes(self, tmp_path):
        from wiki_migrate_v2 import scan_workspace
        wiki_dir = tmp_path / "wiki"
        wiki_dir.mkdir()
        (wiki_dir / "g.md").write_text("---\nsources: 0\n---\n", encoding="utf-8")
        (wiki_dir / "c.md").write_text("---\nsources: 1\n---\n", encoding="utf-8")
        count, dist_before, dist_after, changes = scan_workspace(str(tmp_path))
        assert count == 2   # 两个都没显式 authority, 都会被改
        assert dist_before["generated"] == 1
        assert dist_before["contextual"] == 1
        assert dist_after == dist_before   # dry-run 冷启动不改 tier

    def test_apply_disabled_returns_error_code(self, tmp_path, monkeypatch, capsys):
        """--apply 直接 error, 不跑."""
        from wiki_migrate_v2 import main
        monkeypatch.setattr(sys, "argv", ["wiki_migrate_v2", "--apply"])
        ret = main()
        assert ret == 1
        captured = capsys.readouterr()
        assert "Phase 1 只允许 --dry-run" in captured.out
