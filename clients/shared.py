"""Client 公共常量 + 轻量数据结构.

从 api_adapter.py 拆出 (2026-04-16):
- 重试策略 / 模型降级链 / 定价表 / 最小 max_tokens
- _gen_req_id: 短 hex 请求 ID 生成
- UnifiedResponse / _DotDict: 两端 client 共用的响应对象
"""

import uuid as _uuid_mod


# 重试策略（参考 Claude Code withRetry.ts:57-89 的 query source 分级）
RETRY_POLICIES = {
    "foreground": {"max_retries": 5, "retry_overload": True},   # Phase 1/3 交互，用户在等
    "worker":     {"max_retries": 2, "retry_overload": False},  # Phase 2 worker，失败走容错
    "advisor":    {"max_retries": 3, "retry_overload": True},   # 苍鹰，重要但可延迟
    "router":     {"max_retries": 1, "retry_overload": False},  # 意图路由，快速失败
}

# 模型降级链（参考 CC withRetry.ts:326-350 的 FallbackTriggeredError）
FALLBACK_MODELS = {
    "claude-opus-4-6": "claude-sonnet-4-6",
    "claude-sonnet-4-6": "claude-haiku-4-5-20251001",
}
MAX_CONSECUTIVE_OVERLOADS = 3  # 连续 N 次 529 后自动降级

# 成本定价（USD per million tokens）
MODEL_PRICING = {
    "claude-opus-4-6":            {"input": 15.0, "output": 75.0, "cache_read": 1.5, "cache_write": 18.75},
    "claude-sonnet-4-6":          {"input": 3.0,  "output": 15.0, "cache_read": 0.3, "cache_write": 3.75},
    "claude-haiku-4-5-20251001":  {"input": 0.8,  "output": 4.0,  "cache_read": 0.08, "cache_write": 1.0},
}
FLOOR_MAX_TOKENS = 3000  # 动态调整 max_tokens 的下限


def _gen_req_id():
    """生成短 hex 请求 ID (CC requestLogId 模式)"""
    return _uuid_mod.uuid4().hex[:8]


# ============================================================
# 统一响应对象 (两端 client 共用)
# ============================================================


class UnifiedResponse:
    """统一的 API 响应"""
    def __init__(self, text_blocks, tool_calls, stop_reason, usage, model, truncated=False):
        self.text_blocks = text_blocks
        self.tool_calls = tool_calls
        self.stop_reason = stop_reason
        self.usage = usage
        self.model = model
        # 1c: max_output_recovery 钩子 — 标记输出是否被截断 (CC max_tokens 检测)
        self.truncated = truncated

    @property
    def content(self):
        blocks = []
        for tb in self.text_blocks:
            blocks.append(_DotDict(tb))
        for tc in self.tool_calls:
            blocks.append(_DotDict({"type": "tool_use", **tc}))
        return blocks


class _DotDict(dict):
    """让 dict 支持 .属性 访问"""
    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError:
            raise AttributeError(key)
