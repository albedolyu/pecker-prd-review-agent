"""
生产环境配置 — PECKER_ENV=prod 时生效

和 dev 相比:
- 超时更紧(生产应尽快失败)
- 依据可靠率阈值更严(生产对质量要求更高)
"""

from config.base import *  # noqa: F401,F403

# 更紧的超时(防止长尾请求占用资源)
WORKER_TIMEOUT = 300          # 5 分钟(dev=7 分钟)
TOTAL_REVIEW_TIMEOUT = 720    # 12 分钟(dev=15 分钟)

# 更严的可靠率要求
EVIDENCE_RELIABILITY_THRESHOLD = 0.90

# F4: 生产环境对 eval 质量要求更高
EVAL_MIN_OVERALL_SCORE = 0.60
EVAL_MIN_RECALL = 0.50
EVAL_MIN_PRECISION = 0.50
