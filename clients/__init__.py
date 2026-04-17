"""LLM Client 拆分 (2026-04-16).

api_adapter.py 893 行太大,按职责拆到这里:
- shared.py: 公共常量 (定价/重试策略) + UnifiedResponse + _DotDict + _gen_req_id
- token_tracker.py: TokenTracker + cost/token 预估函数
- anthropic_native.py: AnthropicNativeClient (直连 Anthropic SDK)
- claude_cli.py: ClaudeCodeCLIClient (subprocess claude -p) + git-bash PATH 兜底

api_adapter.py 仍是对外入口 (create_client 工厂 + re-export 全部符号)。
"""
