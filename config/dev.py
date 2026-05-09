"""
开发环境配置 — 默认环境

从 base 继承,开发环境下超时和 token 较宽松,便于调试。
"""

from config.base import *  # noqa: F401,F403
import os


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default

# 2026-04-16 基于 shadow run 实测数据调优 (N=17 session, 80 worker calls):
#   - ai_coding (Opus): 平均 88s,从未触发超时
#   - quality / structure / data_quality (Sonnet): 平均 200-250s
#   - 原 240s 导致 44-53% Sonnet worker 超时 → 数据层的"假静默"
#   - 调到 360s (6 min) 可覆盖 p90, 同时保留"真 stuck"检测语义
#   - 参考 logs/shadow_20260416_174900/report.json 分析
# 2026-04-18 二次调优:对外投资 04-17 实测两次 session 出现 worker duration
#   = 369s/371s,刚好挤在 360 阈值上,wait_for 切线程的 race 极易让"本来能完成"
#   的 worker 被判超时。把 dev 上限抬到 480s 留 100s 真 buffer,prod 改 420s。
#   实测数据点见 workspace-对外投资/output/sessions/rev_1776410765,rev_1776412194。
WORKER_TIMEOUT = _env_float("PECKER_WORKER_TIMEOUT", 480)         # 8 分钟 / 单 worker (覆盖实测 p99 + 100s buffer)
TOTAL_REVIEW_TIMEOUT = _env_float("PECKER_TOTAL_REVIEW_TIMEOUT", 1080)  # 18 分钟总上限
GOSHAWK_TIMEOUT = _env_float("PECKER_GOSHAWK_TIMEOUT", 300)        # Phase G #9: 苍鹰 5 分钟,Opus CLI 慢但不能无限等
