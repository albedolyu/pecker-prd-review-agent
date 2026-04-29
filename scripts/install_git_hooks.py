#!/usr/bin/env python
"""啄木鸟 git hooks 一键安装器.

把 scripts/pre-push.sample 复制到 .git/hooks/pre-push (或 .githooks/pre-push 二选一).

用法:
  python scripts/install_git_hooks.py                     # 默认装到 .git/hooks/
  python scripts/install_git_hooks.py --shared            # 装到 .githooks/ (进版本控制, 团队共享)
  python scripts/install_git_hooks.py --uninstall         # 卸载
  python scripts/install_git_hooks.py --check             # 仅检查现有 hook 是否漂移 (CI 用)
  python scripts/install_git_hooks.py --force             # 已存在直接覆盖, 不问

行为:
  1. 检测 .git/hooks 存在 (即 cwd 在 git repo 内)
  2. 如目标 hook 已存在 → 与 sample 做 diff, 差异时显式问要不要覆盖
  3. 复制 sample → 目标 + chmod +x (Unix) / 不需要 (Win, git for windows 会自动识别 shebang)
  4. 自检: 跑 `bash <hook> --help` 验证可执行 (软失败, 不阻塞安装)

绕过 hook (用户被卡时):
  git push --no-verify
"""
from __future__ import annotations

import argparse
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).parent.resolve()
_ROOT = _HERE.parent
_SAMPLE = _HERE / "pre-push.sample"


def _safe_print(text: str) -> None:
    """Win GBK 控制台兜底."""
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.encode("gbk", errors="replace").decode("gbk", errors="replace"))


def _find_git_root() -> Path | None:
    """从 cwd 往上找 .git 目录."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            return Path(result.stdout.strip())
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _diff_files(a: str, b: str) -> str:
    """简单 unified diff, 不依赖外部工具."""
    import difflib
    a_lines = a.splitlines(keepends=True)
    b_lines = b.splitlines(keepends=True)
    return "".join(difflib.unified_diff(
        a_lines, b_lines,
        fromfile="installed", tofile="sample",
        n=2,
    ))


def _confirm(prompt: str) -> bool:
    """y/n 提示."""
    try:
        ans = input(f"{prompt} [y/N]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    return ans in ("y", "yes")


def _set_executable(path: Path) -> None:
    """Unix: chmod +x. Windows: skip (git 自识别 shebang)."""
    if sys.platform == "win32":
        return
    try:
        st = path.stat()
        path.chmod(st.st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    except OSError as e:
        _safe_print(f"[install-hooks] WARN: chmod 失败: {e}")


def _self_test(hook_path: Path) -> bool:
    """跑 bash <hook> --help, 看是否能执行. 软失败."""
    if sys.platform == "win32":
        # Win 下 bash 可能没装 (git for windows 自带 mingw bash, 但路径不固定)
        bash = shutil.which("bash")
        if not bash:
            _safe_print("[install-hooks] (Windows 跳过自检, bash 不在 PATH; git for windows 内置 bash 仍能跑 hook)")
            return True
        cmd = [bash, str(hook_path), "--help"]
    else:
        cmd = ["bash", str(hook_path), "--help"]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        return result.returncode in (0, 1)  # hook 不一定有 --help, 不报错就行
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def install(target: Path, force: bool) -> int:
    """复制 sample → target. 返回 exit code."""
    if not _SAMPLE.exists():
        _safe_print(f"[install-hooks] ERROR: sample 不存在: {_SAMPLE}")
        return 1

    sample_text = _read_text(_SAMPLE) or ""

    if target.exists():
        installed_text = _read_text(target) or ""
        if installed_text == sample_text:
            _safe_print(f"[install-hooks] OK: {target} 已是最新, 跳过")
            return 0
        _safe_print(f"[install-hooks] {target} 已存在但内容不同:")
        diff = _diff_files(installed_text, sample_text)
        _safe_print(diff[:2000] if len(diff) > 2000 else diff)
        if not force and not _confirm(f"覆盖 {target}?"):
            _safe_print("[install-hooks] 已取消, 不修改现有 hook")
            return 1

    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(_SAMPLE, target)
    _set_executable(target)
    _safe_print(f"[install-hooks] 装好: {target}")

    if _self_test(target):
        _safe_print("[install-hooks] self-test 通过")
    else:
        _safe_print("[install-hooks] WARN: self-test 失败, hook 可能不可执行 — 检查 bash 是否在 PATH")

    return 0


def uninstall(target: Path) -> int:
    if not target.exists():
        _safe_print(f"[install-hooks] {target} 不存在, 无需卸载")
        return 0
    try:
        target.unlink()
        _safe_print(f"[install-hooks] 已删: {target}")
        return 0
    except OSError as e:
        _safe_print(f"[install-hooks] ERROR: 删除失败: {e}")
        return 1


def check_drift(target: Path) -> int:
    """CI 用: 看 hook 是否还和 sample 一致. 漂移返回 1.

    用例: CI 检查 .git/hooks/pre-push 存在但内容跟 sample 不一致 → 警告.
    """
    if not target.exists():
        _safe_print(f"[install-hooks] {target} 不存在 (用户没装 hook, 但不强制)")
        return 0
    sample_text = _read_text(_SAMPLE) or ""
    installed_text = _read_text(target) or ""
    if installed_text == sample_text:
        _safe_print(f"[install-hooks] OK: {target} 与 sample 一致")
        return 0
    _safe_print(f"[install-hooks] WARN: hook 漂移!")
    _safe_print(_diff_files(installed_text, sample_text)[:1500])
    _safe_print("[install-hooks] 修复: python scripts/install_git_hooks.py --force")
    return 1


def main():
    parser = argparse.ArgumentParser(description="啄木鸟 git hooks 一键安装")
    parser.add_argument("--shared", action="store_true",
                        help="装到 .githooks/ (进版本控制, 团队共享, 还需 git config core.hooksPath .githooks)")
    parser.add_argument("--uninstall", action="store_true", help="卸载")
    parser.add_argument("--check", action="store_true", help="仅检查漂移 (CI 用)")
    parser.add_argument("--force", action="store_true", help="已存在直接覆盖")
    args = parser.parse_args()

    git_root = _find_git_root()
    if not git_root:
        _safe_print("[install-hooks] ERROR: 当前不在 git repo 内")
        return 1

    if args.shared:
        target = git_root / ".githooks" / "pre-push"
    else:
        target = git_root / ".git" / "hooks" / "pre-push"

    if args.check:
        return check_drift(target)
    if args.uninstall:
        return uninstall(target)

    rc = install(target, force=args.force)
    if rc == 0 and args.shared:
        _safe_print("[install-hooks] 提示: --shared 模式下还要跑:")
        _safe_print("  git config core.hooksPath .githooks")
    return rc


if __name__ == "__main__":
    sys.exit(main())
