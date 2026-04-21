#!/usr/bin/env bash
# 把当前项目打包成 tar.gz 放到桌面
#
# 排除可重建产物:
#   - web/node_modules     (647M, pnpm install 重建)
#   - .claude/worktrees    (27M, 临时 git worktree)
#   - __pycache__          (Python 字节码缓存)
#   - .pytest_cache        (pytest 缓存)
#   - .next                (Next.js build 产物)
#   - *.pyc                (Python 字节码)
#   - pecker.egg-info      (pip install 产物)
#   - tsconfig.tsbuildinfo (tsc 增量缓存)
#
# 保留:
#   - .git/                (11M 历史宝贵)
#   - workspace*/output    (评审产物 + session jsonl)
#   - logs/                (shadow run 日志)
#
# 预估: 1.4G → 80-200M
#
# 用法:
#   bash scripts/pack_to_desktop.sh

set -e

PROJ="/c/Users/20834/Desktop/agent/prd review"
DEST="/c/Users/20834/Desktop/prd-review-$(date +%Y-%m-%d).tar.gz"

echo "[pack] src:  $PROJ"
echo "[pack] dest: $DEST"
echo "[pack] excluding: node_modules / __pycache__ / .pytest_cache / .next / .claude/worktrees / *.pyc / pecker.egg-info / tsbuildinfo"

cd "/c/Users/20834/Desktop/agent"

tar -czf "$DEST" \
  --exclude='*/node_modules' \
  --exclude='*/__pycache__' \
  --exclude='__pycache__' \
  --exclude='*/.pytest_cache' \
  --exclude='*/.next' \
  --exclude='prd review/.claude/worktrees' \
  --exclude='*.pyc' \
  --exclude='*/pecker.egg-info' \
  --exclude='*/tsconfig.tsbuildinfo' \
  --exclude='prd review/status_*.tmp' \
  "prd review"

SIZE=$(du -sh "$DEST" | cut -f1)
echo ""
echo "[pack] done: $DEST  ($SIZE)"
echo "[pack] 解压: tar -xzf '$DEST' -C 目标目录"
