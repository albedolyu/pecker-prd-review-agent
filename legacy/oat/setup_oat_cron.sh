#!/usr/bin/env bash
# Linux/macOS cron 配置: 每 30 分钟跑一次 OAT 健康检查.
#
# 用法:
#   bash scripts/setup_oat_cron.sh /abs/path/to/prd-review
#
# 安装后:
#   crontab -l   # 查看
#   crontab -r   # 全部移除
# 日志: /tmp/oat_health.log

set -euo pipefail

REPO_ROOT="${1:-$(pwd)}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
LOG_PATH="${OAT_LOG:-/tmp/oat_health.log}"
METRICS_DB="${METRICS_DB:-${REPO_ROOT}/workspace/metrics.db}"

if [[ ! -d "${REPO_ROOT}" ]]; then
  echo "[ERROR] REPO_ROOT 不存在: ${REPO_ROOT}" >&2
  exit 1
fi

CRON_LINE="*/30 * * * * cd ${REPO_ROOT} && ${PYTHON_BIN} scripts/oat_health_monitor.py --auto-heal --metrics-db ${METRICS_DB} >> ${LOG_PATH} 2>&1"

# 去重: 已存在跳过, 否则 append
if crontab -l 2>/dev/null | grep -F "scripts/oat_health_monitor.py" >/dev/null; then
  echo "[INFO] cron 项已存在, 跳过"
else
  ( crontab -l 2>/dev/null; echo "${CRON_LINE}" ) | crontab -
  echo "[OK] 已注册 cron: ${CRON_LINE}"
fi

echo "[INFO] 当前 crontab:"
crontab -l | grep oat_health || true
echo "[INFO] 日志位置: ${LOG_PATH}"
echo "[TIP] 测试一次: ${PYTHON_BIN} scripts/oat_health_monitor.py --auto-heal"
