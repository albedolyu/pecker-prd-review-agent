#!/usr/bin/env bash
# 啄木鸟 git pre-push hook 一键安装 (bash 友好版)
#
# 实际逻辑都在 install_git_hooks.py, 本脚本只是包装一层让 bash 用户能直接跑.
# 安装的 pre-push 会包含公网 remote 防泄漏检查 + rule_regression。
# 仍依赖 Python 3.10+, 因为 hook 自检 / diff 逻辑在 python 里更可靠.
#
# 用法:
#   bash scripts/install_git_hooks.sh                # 装到 .git/hooks/pre-push (个人级)
#   bash scripts/install_git_hooks.sh --shared       # 装到 .githooks/ (团队共享, 进版本控制)
#   bash scripts/install_git_hooks.sh --uninstall    # 卸载
#   bash scripts/install_git_hooks.sh --check        # 仅检查漂移 (CI 用)
#   bash scripts/install_git_hooks.sh --force        # 已存在直接覆盖, 不问

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ---------- 检查 Python ----------
PYTHON="${PYTHON:-}"
if [ -z "$PYTHON" ]; then
  if command -v python3 > /dev/null 2>&1; then
    PYTHON="python3"
  elif command -v python > /dev/null 2>&1; then
    PYTHON="python"
  else
    echo "[install-hooks] ERROR: 未找到 python / python3 命令"
    echo "[install-hooks] Linux:   sudo apt-get install python3.11"
    echo "[install-hooks] macOS:   brew install python@3.11"
    echo "[install-hooks] Windows: 用 scripts/install_git_hooks.ps1 而不是 .sh"
    exit 1
  fi
fi

# ---------- 检查 git ----------
if ! command -v git > /dev/null 2>&1; then
  echo "[install-hooks] ERROR: 未找到 git"
  exit 1
fi

# ---------- 检查在 git 仓库内 ----------
if ! git rev-parse --show-toplevel > /dev/null 2>&1; then
  echo "[install-hooks] ERROR: 当前不在 git repo 内"
  exit 1
fi

# ---------- 转发给 Python 实现 ----------
echo "[install-hooks] 走 $PYTHON $SCRIPT_DIR/install_git_hooks.py $*"
exec "$PYTHON" "$SCRIPT_DIR/install_git_hooks.py" "$@"
