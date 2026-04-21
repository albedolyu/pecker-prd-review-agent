#!/usr/bin/env bash
# 跨 workspace shadow run — 把 3 个就绪 workspace 各跑 2 次
# 目的: 让 STATUS 数据从单 PRD 域扩到多域,真正提高门禁置信度
#
# 预估: 6 个 session × 5-8 分钟 = 30-50 分钟
# 配额消耗: 6 × (4 worker + 苍鹰) ≈ 30 次 CC CLI 调用
#
# 用法:
#   bash scripts/run_cross_workspace_shadow.sh
#
# 跑完后:
#   python scripts/generate_status.py
#   cat STATUS.md   # 看 effective_consistency / worker_silent_rate 是否仍 PASS
#
# 如需中断: Ctrl+C 即可,已完成的 session 已落盘,下次重跑只会追加

set -e
cd "$(dirname "$0")/.."

WORKSPACES=(
  "workspace-产品召回"
  "workspace-侵权软件"
  "workspace-纳税人资质"
)

RUNS_PER_WS=2
TIMEOUT=900   # 单次 review 上限 15 分钟

echo "[shadow-cross] 即将在 ${#WORKSPACES[@]} 个 workspace 各跑 $RUNS_PER_WS 次"
echo "[shadow-cross] 总计 $((${#WORKSPACES[@]} * RUNS_PER_WS)) 个 session, 预估 30-50 分钟"
echo "[shadow-cross] 按 Enter 继续,Ctrl+C 取消"
read -r

for ws in "${WORKSPACES[@]}"; do
  echo ""
  echo "============================================================"
  echo "[shadow-cross] >>> $ws (runs=$RUNS_PER_WS)"
  echo "============================================================"
  python scripts/shadow_run.py \
    --workspace "$ws" \
    --runs "$RUNS_PER_WS" \
    --concurrent 1 \
    --timeout "$TIMEOUT"
done

echo ""
echo "============================================================"
echo "[shadow-cross] 全部完成,重生成 STATUS.md"
echo "============================================================"
python scripts/generate_status.py

echo ""
echo "[shadow-cross] STATUS 摘要:"
grep -A1 "稳定性门禁" STATUS.md || true
