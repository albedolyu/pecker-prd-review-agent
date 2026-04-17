"""
interactive_io 模块单测 — 覆盖非交互模式检测和降级输入
"""

import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from interactive_io import is_noninteractive, read_input


class TestIsNoninteractive:
    def test_unset_returns_false(self, monkeypatch):
        monkeypatch.delenv("PECKER_NONINTERACTIVE", raising=False)
        assert is_noninteractive() is False

    def test_truthy_values(self, monkeypatch):
        for v in ("1", "true", "yes", "TRUE", "Yes"):
            monkeypatch.setenv("PECKER_NONINTERACTIVE", v)
            assert is_noninteractive() is True, f"expected True for {v!r}"

    def test_falsy_values(self, monkeypatch):
        for v in ("0", "false", "no", "", "foo"):
            monkeypatch.setenv("PECKER_NONINTERACTIVE", v)
            assert is_noninteractive() is False, f"expected False for {v!r}"


class TestReadInput:
    def test_noninteractive_returns_fallback(self, monkeypatch):
        monkeypatch.setenv("PECKER_NONINTERACTIVE", "1")
        # 不应调用 input()
        monkeypatch.setattr("builtins.input", lambda *a, **kw: pytest.fail("input should not be called"))
        assert read_input("prompt: ", fallback="default") == "default"

    def test_interactive_calls_input(self, monkeypatch):
        monkeypatch.delenv("PECKER_NONINTERACTIVE", raising=False)
        monkeypatch.setattr("builtins.input", lambda *a, **kw: "  user answer  ")
        # input().strip() 被调用
        assert read_input("prompt: ", fallback="default") == "user answer"

    def test_eof_returns_fallback(self, monkeypatch):
        monkeypatch.delenv("PECKER_NONINTERACTIVE", raising=False)
        def _raise_eof(*a, **kw):
            raise EOFError()
        monkeypatch.setattr("builtins.input", _raise_eof)
        assert read_input("prompt: ", fallback="fb") == "fb"

    def test_keyboard_interrupt_returns_fallback(self, monkeypatch):
        monkeypatch.delenv("PECKER_NONINTERACTIVE", raising=False)
        def _raise_kbi(*a, **kw):
            raise KeyboardInterrupt()
        monkeypatch.setattr("builtins.input", _raise_kbi)
        assert read_input("prompt: ", fallback="fb") == "fb"

    def test_empty_fallback_default(self, monkeypatch):
        monkeypatch.setenv("PECKER_NONINTERACTIVE", "1")
        assert read_input("prompt: ") == ""
