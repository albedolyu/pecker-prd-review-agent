"""
共享配置 -- 模型、提示词、常量

v1.2(E2): 所有配置迁移到 config/ 子包,本模块只做**向后兼容的重新导出**。
下游模块的 `from agent_config import ...` 保持工作。

新代码推荐直接 `from config import ...`,按 PECKER_ENV 切换环境:
  - PECKER_ENV=dev (默认)
  - PECKER_ENV=prod
  - PECKER_ENV=test
"""

# 从 config 包重新导出所有公共配置(dev/prod/test 由 PECKER_ENV 决定)
from config import (  # noqa: F401
    # 路径
    BASE_DIR,
    PROMPT_PATH,
    PR_REVIEW_PROMPT_PATH,
    DEFAULT_WORKSPACE,
    # 模型
    MODEL_TIERS,
    ROUTER_PROMPT,
    # API 参数
    MAX_TOKENS,
    MAX_TOOL_TURNS,
    # 超时
    WORKER_TIMEOUT,
    TOTAL_REVIEW_TIMEOUT,
    TOOL_LOOP_TIMEOUT,
    # 质量阈值
    EVIDENCE_RELIABILITY_THRESHOLD,
    # 断路器 + 截断 + token 追踪
    MAX_CONSECUTIVE_WORKER_FAILURES,
    MAX_ITEMS_PER_WORKER,
    COMPACT_THRESHOLD,
    MAX_WIKI_CHARS,
    # CC deep patterns (Round 3)
    JITTER_MAX_FRAC,
    EFFORT_TOKENS,
    # helper
    load_system_prompt,
    load_pr_review_prompt,
    get_api_key,
    get_base_url,
    get_feishu_webhook,
)
