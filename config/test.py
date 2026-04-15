"""
测试环境配置 — PECKER_ENV=test 时生效

用小超时和小 token,让测试跑得快。
pytest 和 CI 场景下应设置 PECKER_ENV=test + PECKER_NONINTERACTIVE=1。
"""

from config.base import *  # noqa: F401,F403

# 测试用极短超时,快速暴露挂起问题
WORKER_TIMEOUT = 60           # 1 分钟
TOTAL_REVIEW_TIMEOUT = 180    # 3 分钟
TOOL_LOOP_TIMEOUT = 300       # 5 分钟(A4)

# 测试用小 token,减少 API 消耗
MAX_TOKENS = 2048

# 测试降低可靠率阈值(避免 mock 数据偶尔不达标导致 CI 红)
EVIDENCE_RELIABILITY_THRESHOLD = 0.50

# F4: 测试环境门槛最低(用于 CI 冒烟)
EVAL_MIN_OVERALL_SCORE = 0.40
EVAL_MIN_RECALL = 0.30
EVAL_MIN_PRECISION = 0.30
