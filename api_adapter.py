"""
API 适配层 — 拆分后对外入口

2026-04-16 重构: 893 行文件按职责拆到 clients/ 包:
- clients/shared.py: 常量 + UnifiedResponse + _DotDict + _gen_req_id
- clients/token_tracker.py: TokenTracker + cost/token 预估
- clients/anthropic_native.py: AnthropicNativeClient (直连 SDK)
- clients/claude_cli.py: ClaudeCodeCLIClient (subprocess) + git-bash 兜底

本文件保留:
- create_client() 工厂
- 全部公开符号 re-export (兼容 `from api_adapter import X` 的旧代码)
"""

# ============================================================
# Re-export from clients/ (保持向后兼容)
# ============================================================

from clients.shared import (  # noqa: F401
    FALLBACK_MODELS,
    FLOOR_MAX_TOKENS,
    MAX_CONSECUTIVE_OVERLOADS,
    MODEL_PRICING,
    RETRY_POLICIES,
    UnifiedResponse,
    _DotDict,
    _gen_req_id,
)
from clients.token_tracker import (  # noqa: F401
    TokenTracker,
    compute_call_cost_usd,
    estimate_message_tokens,
    estimate_tokens,
)
from clients.anthropic_native import AnthropicNativeClient  # noqa: F401
from clients.claude_cli import (  # noqa: F401
    ClaudeCodeCLIClient,
    _ensure_git_bash_in_path,
)


# ============================================================
# 工厂函数
# ============================================================

def create_client(api_key=None, base_url=None, **kwargs):
    """创建 API 客户端。

    只走本地 Claude Code CLI（零 API key，复用当前 CC 登录态）。
    api_key / base_url 参数保留仅为兼容旧调用签名，实际被忽略。
    """
    return ClaudeCodeCLIClient()
