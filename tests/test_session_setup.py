"""
session_setup 单测 — 覆盖 main() 抽出的编排辅助

重点: apply_noninteractive_defaults 的环境副作用 + resolve_messages 三种策略分支。
"""

import argparse
import os
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _mk_args(**overrides):
    """构造默认 args Namespace,便于测 apply_noninteractive_defaults."""
    defaults = {
        "prd_name": None,
        "model": "auto",
        "reviewer": "default",
        "workspace": ".",
        "no_parallel": False,
        "merge": None,
        "non_interactive": False,
        "resume": "prompt",
        "auto_decide": "off",
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


# ============================================================
# build_parser
# ============================================================

class TestBuildParser:
    def test_defaults(self):
        from session_setup import build_parser
        args = build_parser().parse_args([])
        assert args.prd_name is None
        # 2026-04-29: --model 默认 auto → opus (router.intent Haiku 路由废弃, 默认走 opus)
        assert args.model == "opus"
        assert args.resume == "prompt"
        assert args.auto_decide == "off"
        assert args.no_parallel is False
        assert args.merge is None

    def test_positional_prd_name(self):
        from session_setup import build_parser
        args = build_parser().parse_args(["搜索优化"])
        assert args.prd_name == "搜索优化"

    def test_merge_takes_two(self):
        from session_setup import build_parser
        args = build_parser().parse_args(["--merge", "alice", "bob"])
        assert args.merge == ["alice", "bob"]

    def test_invalid_model_rejected(self):
        from session_setup import build_parser
        with pytest.raises(SystemExit):
            build_parser().parse_args(["--model", "gpt"])


# ============================================================
# apply_noninteractive_defaults
# ============================================================

class TestApplyNoninteractiveDefaults:
    def test_tty_keeps_interactive(self, monkeypatch):
        monkeypatch.delenv("PECKER_NONINTERACTIVE", raising=False)
        from session_setup import apply_noninteractive_defaults
        args = _mk_args()
        apply_noninteractive_defaults(args, stdin_is_tty=True)
        assert args.non_interactive is False
        # PECKER_NONINTERACTIVE 不应该被设置
        assert os.environ.get("PECKER_NONINTERACTIVE", "") == ""

    def test_non_tty_auto_enables(self, monkeypatch, capsys):
        monkeypatch.delenv("PECKER_NONINTERACTIVE", raising=False)
        from session_setup import apply_noninteractive_defaults
        args = _mk_args()
        apply_noninteractive_defaults(args, stdin_is_tty=False)
        assert args.non_interactive is True
        assert os.environ["PECKER_NONINTERACTIVE"] == "1"
        assert "自动启用 --non-interactive" in capsys.readouterr().out

    def test_noninteractive_resume_becomes_skip(self, monkeypatch):
        monkeypatch.delenv("PECKER_NONINTERACTIVE", raising=False)
        from session_setup import apply_noninteractive_defaults
        args = _mk_args(non_interactive=True, resume="prompt")
        apply_noninteractive_defaults(args, stdin_is_tty=False)
        assert args.resume == "skip"

    def test_noninteractive_auto_decide_becomes_by_confidence(self, monkeypatch):
        monkeypatch.delenv("PECKER_NONINTERACTIVE", raising=False)
        from session_setup import apply_noninteractive_defaults
        args = _mk_args(non_interactive=True, auto_decide="off")
        apply_noninteractive_defaults(args, stdin_is_tty=False)
        assert args.auto_decide == "by-confidence"

    def test_explicit_auto_decide_preserved(self, monkeypatch):
        monkeypatch.delenv("PECKER_NONINTERACTIVE", raising=False)
        from session_setup import apply_noninteractive_defaults
        args = _mk_args(non_interactive=True, auto_decide="accept-all")
        apply_noninteractive_defaults(args, stdin_is_tty=False)
        assert args.auto_decide == "accept-all"

    def test_pecker_auto_decide_always_exported(self, monkeypatch):
        monkeypatch.delenv("PECKER_AUTO_DECIDE", raising=False)
        monkeypatch.delenv("PECKER_NONINTERACTIVE", raising=False)
        from session_setup import apply_noninteractive_defaults
        args = _mk_args(auto_decide="reject-all")
        apply_noninteractive_defaults(args, stdin_is_tty=True)
        assert os.environ["PECKER_AUTO_DECIDE"] == "reject-all"


# ============================================================
# resolve_messages
# ============================================================

class TestResolveMessages:
    def test_none_resumed(self):
        from session_setup import resolve_messages
        assert resolve_messages("prompt", None) is None

    def test_empty_prev_messages(self):
        from session_setup import resolve_messages
        assert resolve_messages("auto", ([], {})) is None

    def test_auto_returns_prev(self, capsys):
        from session_setup import resolve_messages
        prev = [{"role": "user", "content": "x"}]
        result = resolve_messages("auto", (prev, {}))
        assert result is prev
        assert "自动恢复" in capsys.readouterr().out

    def test_skip_ignores_prev(self, capsys):
        from session_setup import resolve_messages
        prev = [{"role": "user", "content": "x"}]
        result = resolve_messages("skip", (prev, {}))
        assert result is None
        assert "忽略" in capsys.readouterr().out

    def test_prompt_y_restores(self, monkeypatch):
        monkeypatch.setenv("PECKER_NONINTERACTIVE", "0")
        monkeypatch.delenv("PECKER_NONINTERACTIVE", raising=False)
        from session_setup import resolve_messages
        prev = [{"role": "user", "content": "x"}]
        with patch("session_setup.read_input", return_value="y"):
            result = resolve_messages("prompt", (prev, {}))
        assert result is prev

    def test_prompt_n_discards(self, monkeypatch):
        monkeypatch.delenv("PECKER_NONINTERACTIVE", raising=False)
        from session_setup import resolve_messages
        prev = [{"role": "user", "content": "x"}]
        with patch("session_setup.read_input", return_value="n"):
            result = resolve_messages("prompt", (prev, {}))
        assert result is None

    def test_prompt_uppercase_y_works(self, monkeypatch):
        monkeypatch.delenv("PECKER_NONINTERACTIVE", raising=False)
        from session_setup import resolve_messages
        prev = [{"role": "user", "content": "x"}]
        with patch("session_setup.read_input", return_value="Y"):
            result = resolve_messages("prompt", (prev, {}))
        assert result is prev


# ============================================================
# build_initial_message
# ============================================================

class TestBuildInitialMessage:
    def test_contains_all_fields(self):
        from session_setup import build_initial_message
        msg = build_initial_message(
            date_str="2026-04-16",
            reviewer="夏新",
            prd_name="搜索优化",
            workspace="/tmp/ws",
            branch_name="review/xia/search/2026-04-16",
        )
        assert "2026-04-16" in msg
        assert "夏新" in msg
        assert "搜索优化" in msg
        assert "/tmp/ws" in msg
        assert "review/xia/search/2026-04-16" in msg
        assert "Phase 0" in msg


# ============================================================
# run_merge_mode
# ============================================================

class TestRunMergeMode:
    def test_writes_report_and_logs(self, tmp_path, capsys):
        from session_setup import run_merge_mode
        args = _mk_args(
            prd_name="搜索",
            workspace=str(tmp_path),
            merge=["alice", "bob"],
        )

        fake_items = [{"id": "R-001"}]
        fake_result = {
            "merged": [{"id": "R-001"}],
            "agreement": {"agreed": 1, "total": 2},
        }

        with patch("merge_reviews.load_reviewer_items", return_value=fake_items), \
             patch("merge_reviews.merge_reviews", return_value=fake_result), \
             patch("merge_reviews.format_merged_report", return_value="# 合并报告\n内容"):
            run_merge_mode(args)

        out_dir = tmp_path / "output"
        reports = list(out_dir.glob("PRD_合并报告_*.md"))
        assert len(reports) == 1
        assert "# 合并报告" in reports[0].read_text(encoding="utf-8")
        captured = capsys.readouterr().out
        assert "共识 1 条" in captured
