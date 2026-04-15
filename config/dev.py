"""
开发环境配置 — 默认环境

从 base 继承,开发环境下超时和 token 较宽松,便于调试。
"""

from config.base import *  # noqa: F401,F403

# dev 环境保留 base 的默认值,无需额外覆盖
# 如需 dev 专属配置,在此覆盖,例如:
# WORKER_TIMEOUT = 600   # 开发时给更长的超时便于调试
# MAX_TOKENS = 16384     # 开发时放宽 token
