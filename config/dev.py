"""
开发环境配置 — 默认环境

从 base 继承,开发环境下超时和 token 较宽松,便于调试。
"""

from config.base import *  # noqa: F401,F403

# Phase G #2: dev 收紧 worker 超时
# 之前 base WORKER_TIMEOUT=420 太宽,实际 stuck 时用户感知不到,直接卡住
# 4 分钟单 worker 已经足够 dev 调试,超时就走 degraded 路径
WORKER_TIMEOUT = 240         # 4 分钟 / 单 worker
TOTAL_REVIEW_TIMEOUT = 600   # 10 分钟总上限,触发后整体降级
