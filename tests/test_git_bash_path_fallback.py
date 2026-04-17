"""Windows git-bash PATH 兜底测试.

场景: Python 多进程并发调 Claude CLI 时,子进程继承的 PATH 偶发不含 git-bash,
CLI 启动失败报 "requires git-bash"。`_ensure_git_bash_in_path` 在 Windows 下
显式把 Git 安装路径拼到 PATH 最前面,其他平台透传。
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from api_adapter import _ensure_git_bash_in_path


class TestEnsureGitBashInPath:
    def test_non_windows_passthrough(self, monkeypatch):
        """非 Windows 平台应该不改动 env."""
        monkeypatch.setattr("os.name", "posix")
        env = {"PATH": "/usr/bin:/bin"}
        out = _ensure_git_bash_in_path(env)
        assert out["PATH"] == "/usr/bin:/bin"

    def test_windows_path_already_has_bash(self, monkeypatch, tmp_path):
        """PATH 里已有 bash.exe → 不改动."""
        monkeypatch.setattr("os.name", "nt")
        fake_bin = tmp_path / "fake_bin"
        fake_bin.mkdir()
        (fake_bin / "bash.exe").write_text("")

        original_path = str(fake_bin) + ";C:\\other"
        env = {"PATH": original_path}
        out = _ensure_git_bash_in_path(env)
        assert out["PATH"] == original_path

    def test_windows_path_missing_bash_prepends_git(self, monkeypatch):
        """PATH 缺 bash.exe → 检测到的 Git 目录拼到最前."""
        monkeypatch.setattr("os.name", "nt")
        # isfile 始终 False → PATH 里没 bash.exe
        monkeypatch.setattr("os.path.isfile", lambda p: False)
        # isdir 只对标准 Git 路径返回 True
        monkeypatch.setattr(
            "os.path.isdir",
            lambda p: p == r"C:\Program Files\Git\bin",
        )

        env = {"PATH": "C:\\Windows\\System32"}
        out = _ensure_git_bash_in_path(env)
        assert out["PATH"].startswith(r"C:\Program Files\Git\bin")
        assert "C:\\Windows\\System32" in out["PATH"]

    def test_windows_no_git_installed_noop(self, monkeypatch):
        """Git 一个候选目录都不存在 → PATH 不变."""
        monkeypatch.setattr("os.name", "nt")
        monkeypatch.setattr("os.path.isdir", lambda p: False)
        monkeypatch.setattr("os.path.isfile", lambda p: False)

        env = {"PATH": "C:\\Windows\\System32"}
        out = _ensure_git_bash_in_path(env)
        assert out["PATH"] == "C:\\Windows\\System32"

    def test_empty_path(self, monkeypatch):
        """PATH 为空字符串也不能崩."""
        monkeypatch.setattr("os.name", "nt")
        monkeypatch.setattr("os.path.isdir", lambda p: False)
        monkeypatch.setattr("os.path.isfile", lambda p: False)

        env = {"PATH": ""}
        out = _ensure_git_bash_in_path(env)
        assert "PATH" in out

    def test_path_key_missing(self, monkeypatch):
        """env 完全没有 PATH 字段 → 不崩,透传 None."""
        monkeypatch.setattr("os.name", "nt")
        monkeypatch.setattr("os.path.isdir", lambda p: False)
        monkeypatch.setattr("os.path.isfile", lambda p: False)

        env = {}
        out = _ensure_git_bash_in_path(env)
        # 没 Git 就什么也不做
        assert out == {}
