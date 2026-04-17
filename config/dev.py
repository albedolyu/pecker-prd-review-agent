"""
开发环境配置 — 默认环境

从 base 继承,开发环境下超时和 token 较宽松,便于调试。
"""

from config.base import *  # noqa: F401,F403

# 2026-04-16 基于 shadow run 实测数据调优 (N=17 session, 80 worker calls):
#   - ai_coding (Opus): 平均 88s,从未触发超时
#   - quality / structure / data_quality (Sonnet): 平均 200-250s
#   - 原 240s 导致 44-53% Sonnet worker 超时 → 数据层的"假静默"
#   - 调到 360s (6 min) 可覆盖 p90, 同时保留"真 stuck"检测语义
#   - 参考 logs/shadow_20260416_174900/report.json 分析
WORKER_TIMEOUT = 360         # 6 分钟 / 单 worker
TOTAL_REVIEW_TIMEOUT = 900   # 15 分钟总上限 (worker 360 + goshawk 300 + phase3 + buffer)
GOSHAWK_TIMEOUT = 300        # Phase G #9: 苍鹰 5 分钟,Opus CLI 慢但不能无限等
