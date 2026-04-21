"""
生产环境配置 — PECKER_ENV=prod 时生效

和 dev 相比:
- 超时更紧(生产应尽快失败)
- 依据可靠率阈值更严(生产对质量要求更高)
"""

from config.base import *  # noqa: F401,F403

# 2026-04-18: 与 dev 对齐 buffer 策略,prod 实测 worker p99 也接近 360s
# (Sonnet worker 复杂 PRD 200-371s,prod 一致性要求更高,不能 borderline 切)
# 原 300s 在 04-17 session 实测被多次擦边切;改 420 留 50s buffer over 实测 p99 369s
WORKER_TIMEOUT = 420          # 7 分钟(dev=8 分钟,prod 比 dev 紧 60s)
TOTAL_REVIEW_TIMEOUT = 900    # 15 分钟(原 720 等于 worker+goshawk 没 buffer)

# 更严的可靠率要求
EVIDENCE_RELIABILITY_THRESHOLD = 0.90

# F4: 生产环境对 eval 质量要求更高
EVAL_MIN_OVERALL_SCORE = 0.60
EVAL_MIN_RECALL = 0.50
EVAL_MIN_PRECISION = 0.50
