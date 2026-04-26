"""
content_loader 模块单测 — 覆盖 PRD/Wiki 加载 + 分支名规整 + wiki_pull 降级
"""

import os
import sys
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from content_loader import (
    load_prd_content,
    load_wiki_pages,
    sanitize_branch_name,
    wiki_pull,
)


class TestLoadPRDContent:
    def test_missing_prd_dir_returns_none(self, tmp_path):
        assert load_prd_content(str(tmp_path)) == (None, [])

    def test_empty_prd_dir_returns_none(self, tmp_path):
        (tmp_path / "prd").mkdir()
        assert load_prd_content(str(tmp_path)) == (None, [])

    def test_single_md_file(self, tmp_path):
        prd_dir = tmp_path / "prd"
        prd_dir.mkdir()
        (prd_dir / "spec.md").write_text("# Title\n\nContent", encoding="utf-8")
        content, files = load_prd_content(str(tmp_path))
        assert "## spec.md" in content
        assert "Title" in content
        assert files == ["spec.md"]

    def test_multiple_files_sorted_and_joined(self, tmp_path):
        prd_dir = tmp_path / "prd"
        prd_dir.mkdir()
        (prd_dir / "b.md").write_text("B", encoding="utf-8")
        (prd_dir / "a.md").write_text("A", encoding="utf-8")
        content, files = load_prd_content(str(tmp_path))
        # 排序确保稳定性
        assert files == ["b.md", "a.md"] or files == ["a.md", "b.md"]
        # 内容里先 a 后 b (sorted)
        a_pos = content.index("## a.md")
        b_pos = content.index("## b.md")
        assert a_pos < b_pos
        assert "---" in content  # 分隔符

    def test_non_md_files_ignored(self, tmp_path):
        prd_dir = tmp_path / "prd"
        prd_dir.mkdir()
        (prd_dir / "readme.txt").write_text("txt", encoding="utf-8")
        (prd_dir / "spec.md").write_text("md", encoding="utf-8")
        _, files = load_prd_content(str(tmp_path))
        assert files == ["spec.md"]


class TestLoadWikiPages:
    @pytest.fixture(autouse=True)
    def _disable_external_canonical(self, monkeypatch):
        # 修法 C 后 load_wiki_pages 会自动合外挂 canonical wiki (PM 机器默认存在),
        # 单测要的是纯 workspace 行为, 所以强制 env="" disable 外挂.
        monkeypatch.setenv("PECKER_EXTERNAL_CANONICAL_WIKI", "")

    def test_missing_dir_returns_empty(self, tmp_path):
        assert load_wiki_pages(str(tmp_path / "nonexistent")) == {}

    def test_excludes_index_log_scratchpad(self, tmp_path):
        (tmp_path / "index.md").write_text("idx", encoding="utf-8")
        (tmp_path / "log.md").write_text("log", encoding="utf-8")
        (tmp_path / "_scratchpad.md").write_text("sc", encoding="utf-8")
        (tmp_path / "实体-公司.md").write_text("company page", encoding="utf-8")
        pages = load_wiki_pages(str(tmp_path))
        assert pages == {"实体-公司": "company page"}

    def test_returns_dict_without_md_suffix(self, tmp_path):
        (tmp_path / "page_a.md").write_text("A", encoding="utf-8")
        (tmp_path / "page_b.md").write_text("B", encoding="utf-8")
        pages = load_wiki_pages(str(tmp_path))
        assert set(pages.keys()) == {"page_a", "page_b"}
        assert pages["page_a"] == "A"

    def test_non_md_ignored(self, tmp_path):
        (tmp_path / "image.png").write_text("binary", encoding="utf-8")
        (tmp_path / "note.md").write_text("note", encoding="utf-8")
        pages = load_wiki_pages(str(tmp_path))
        assert list(pages.keys()) == ["note"]


class TestExternalCanonicalWiki:
    """修法 C 新增: 验证 PECKER_EXTERNAL_CANONICAL_WIKI default + merge 语义."""

    def test_env_empty_string_disables_external(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PECKER_EXTERNAL_CANONICAL_WIKI", "")
        (tmp_path / "local.md").write_text("local", encoding="utf-8")
        pages = load_wiki_pages(str(tmp_path))
        assert pages == {"local": "local"}

    def test_env_nonexistent_path_skipped(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PECKER_EXTERNAL_CANONICAL_WIKI", str(tmp_path / "nope"))
        (tmp_path / "local.md").write_text("local", encoding="utf-8")
        pages = load_wiki_pages(str(tmp_path))
        assert pages == {"local": "local"}

    def test_external_merged_workspace_overrides(self, tmp_path, monkeypatch):
        ext = tmp_path / "ext_wiki"
        ext.mkdir()
        (ext / "external_only.md").write_text("EXT_ONLY", encoding="utf-8")
        (ext / "shared.md").write_text("EXT_SHARED", encoding="utf-8")

        ws = tmp_path / "ws_wiki"
        ws.mkdir()
        (ws / "shared.md").write_text("WS_SHARED", encoding="utf-8")
        (ws / "ws_only.md").write_text("WS_ONLY", encoding="utf-8")

        monkeypatch.setenv("PECKER_EXTERNAL_CANONICAL_WIKI", str(ext))
        pages = load_wiki_pages(str(ws))
        # 外挂 + workspace 都加载, key 冲突 workspace 赢 (本地 override)
        assert set(pages.keys()) == {"external_only", "shared", "ws_only"}
        assert pages["shared"] == "WS_SHARED"
        assert pages["external_only"] == "EXT_ONLY"
        assert pages["ws_only"] == "WS_ONLY"

    def test_external_skips_index_log_scratchpad(self, tmp_path, monkeypatch):
        ext = tmp_path / "ext_wiki"
        ext.mkdir()
        (ext / "index.md").write_text("idx", encoding="utf-8")
        (ext / "log.md").write_text("log", encoding="utf-8")
        (ext / "_scratchpad.md").write_text("sc", encoding="utf-8")
        (ext / "real.md").write_text("real", encoding="utf-8")

        ws = tmp_path / "ws_wiki"
        ws.mkdir()

        monkeypatch.setenv("PECKER_EXTERNAL_CANONICAL_WIKI", str(ext))
        pages = load_wiki_pages(str(ws))
        assert pages == {"real": "real"}


class TestSanitizeBranchName:
    def test_plain_ascii(self):
        assert sanitize_branch_name("feature-auth") == "feature-auth"

    def test_chinese_kept(self):
        assert sanitize_branch_name("搜索优化") == "搜索优化"

    def test_spaces_to_hyphen(self):
        assert sanitize_branch_name("foo bar baz") == "foo-bar-baz"

    def test_multiple_special_chars_collapsed(self):
        assert sanitize_branch_name("foo///bar") == "foo-bar"

    def test_leading_trailing_hyphens_stripped(self):
        assert sanitize_branch_name("---foo---") == "foo"

    def test_empty_returns_unnamed(self):
        assert sanitize_branch_name("") == "unnamed"
        assert sanitize_branch_name("///") == "unnamed"

    def test_mixed_chinese_ascii(self):
        assert sanitize_branch_name("PRD 评审/v2") == "PRD-评审-v2"


class TestWikiPull:
    def test_not_git_repo_silent_skip(self, tmp_path, capsys):
        # 不是 git 仓库,静默跳过
        wiki_pull(str(tmp_path))
        captured = capsys.readouterr()
        assert captured.out == ""

    def test_git_pull_success(self, tmp_path, capsys):
        (tmp_path / ".git").mkdir()
        with patch("content_loader.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stderr="")
            wiki_pull(str(tmp_path))
        captured = capsys.readouterr()
        assert "已同步" in captured.out

    def test_git_pull_failure_not_raises(self, tmp_path, capsys):
        (tmp_path / ".git").mkdir()
        with patch("content_loader.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stderr="remote err")
            wiki_pull(str(tmp_path))
        captured = capsys.readouterr()
        assert "pull 失败" in captured.out
