"""
模型路由 + system prompt blocks 构造 — 从 run_session.py 抽出

route_intent: Haiku 轻量分类,决定用哪个模型
build_system_blocks: 支持 prompt caching 的 system blocks 拼装
"""

from typing import Any, Dict, List, Optional

from agent_config import MODEL_TIERS, ROUTER_PROMPT


def route_intent(client: Any, prd_name: str, user_instruction: str = "PRD 评审") -> str:
    """用 Haiku 做轻量分类,决定用哪个模型。

    返回 MODEL_TIERS 中的键(opus/sonnet/haiku),失败默认 sonnet。

    Wave 2: 默认走 model_router.route_call("router.intent", ...). client 入参变 deprecated
    但保留 — 显式传 client (e.g. test_router 系列 mock client) 时仍走 client.create
    兼容老 mock 通道.
    """
    msgs = [{
        "role": "user",
        "content": f"PRD 名称：{prd_name}\n用户指令：{user_instruction}",
    }]
    try:
        if client is None:
            from model_router import route_call
            response = route_call(
                "router.intent",
                system=ROUTER_PROMPT,
                messages=msgs,
                max_tokens=10,
            )
        else:
            response = client.create(
                model=MODEL_TIERS["haiku"],
                max_tokens=10,
                system=ROUTER_PROMPT,
                messages=msgs,
            )
        tier = response.content[0].text.strip().lower()
        if tier in MODEL_TIERS:
            return tier
    except Exception:
        pass
    return "sonnet"


def build_system_blocks(
    system_prompt: str,
    prd_content: Optional[str] = None,
    workspace: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """构建 system prompt blocks,支持 prompt caching。

    block 顺序:
    1. 主 system prompt (cache_control)
    2. 当前待评审 PRD (cache_control, 可选)
    3. scratchpad 评审状态 (无 cache, 可选)
    """
    blocks: List[Dict[str, Any]] = [
        {
            "type": "text",
            "text": system_prompt,
            "cache_control": {"type": "ephemeral"},
        }
    ]

    if prd_content:
        blocks.append({
            "type": "text",
            "text": f"## 当前待评审 PRD 内容\n\n{prd_content}",
            "cache_control": {"type": "ephemeral"},
        })

    if workspace:
        # 避免在 import 层硬依赖 context_manager(保持模块可独立测试)
        from context_manager import read_scratchpad
        scratchpad = read_scratchpad(workspace)
        if scratchpad:
            blocks.append({
                "type": "text",
                "text": f"## 当前评审状态\n\n{scratchpad}",
            })

    return blocks
