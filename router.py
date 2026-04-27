"""
模型路由 + system prompt blocks 构造 — 从 run_session.py 抽出

route_intent: Haiku 轻量分类,决定用哪个模型 (含 reject 拒识类)
build_system_blocks: 支持 prompt caching 的 system blocks 拼装
"""

import re
from typing import Any, Dict, List, Optional

from agent_config import MODEL_TIERS, ROUTER_PROMPT


_VALID_INTENTS = ("opus", "sonnet", "haiku", "reject")


def route_intent(client: Any, prd_name: str, user_instruction: str = "PRD 评审") -> str:
    """用 Haiku 做轻量分类,决定用哪个模型 (或拒识)。

    返回值: opus / sonnet / haiku / reject 之一 (失败默认 sonnet)。
    "reject" 表示输入不是有效 PRD (简历/合同/营销文案/咨询等), caller 应拒评。

    Wave 2: 默认走 model_router.route_call("router.intent", ...). client 入参变 deprecated
    但保留 — 显式传 client (e.g. test_router 系列 mock client) 时仍走 client.create
    兼容老 mock 通道.

    2026-04-27 P1 修: 加 reject 类 + few-shot prompt (baseline 实测原 prompt
    accuracy=0.25, opus/haiku/reject 全错 — ROUTER_PROMPT 没列 reject 类,
    LLM 无 anchor)。
    """
    # 容错: max_tokens 调到 16 留一点尾巴 (haiku 偶尔输出 "Sonnet." 多一字符就被截)
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
                max_tokens=16,
            )
        else:
            response = client.create(
                model=MODEL_TIERS["haiku"],
                max_tokens=16,
                system=ROUTER_PROMPT,
                messages=msgs,
            )
        # 容错解析: 取首词, 去标点 / 引号
        raw = response.content[0].text.strip().lower()
        tier = re.split(r"[\s\.,;:!?'\"]", raw, maxsplit=1)[0]
        if tier in _VALID_INTENTS:
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
