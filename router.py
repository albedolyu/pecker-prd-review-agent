"""
模型路由 + system prompt blocks 构造 — 从 run_session.py 抽出

route_intent: Haiku 轻量分类,决定用哪个模型 (含 reject 拒识类)
build_system_blocks: 支持 prompt caching 的 system blocks 拼装
"""

import os
import re
import sys
from typing import Any, Dict, List, Optional

from agent_config import MODEL_TIERS, ROUTER_PROMPT


_VALID_INTENTS = ("opus", "sonnet", "haiku", "reject")


def _router_debug_log(line: str) -> None:
    """PECKER_ROUTER_DEBUG=1 时打印调试信息到 stderr (默认关).

    跑 baseline 时可:
        PECKER_ROUTER_DEBUG=1 python scripts/eval_route.py router.intent ... 2>&1 | grep router_debug
    """
    if os.environ.get("PECKER_ROUTER_DEBUG", "").strip() in ("1", "true", "True"):
        sys.stderr.write(f"[router_debug] {line}\n")
        sys.stderr.flush()


# Step 3 实验用 tool_use schema, 强约束输出只允许 4 个 enum 值之一.
# Claude CLI subprocess 不支持原生 tool_use, fallback 走 "prompt 注入 schema + 解析 JSON".
# 见 clients/claude_cli.py:_append_schema_instruction.
_INTENT_TOOL = {
    "name": "select_review_intent",
    "description": "判断 PRD 评审复杂度并返回 tier 标签 (opus/sonnet/haiku/reject 之一)",
    "input_schema": {
        "type": "object",
        "properties": {
            "tier": {
                "type": "string",
                "enum": list(_VALID_INTENTS),
                "description": "评审 tier 标签",
            },
        },
        "required": ["tier"],
    },
}


def _extract_tier_from_tool_use(response: Any) -> Optional[str]:
    """从 UnifiedResponse.tool_calls 抽 tier 字段, 兼容 dict / object 两种 block.

    CLI 走 schema 注入 fallback 时, _create_once 把 parse 后的 dict 包成 tool_calls,
    所以这里既可能从 tool_calls 拿, 也可能从 text_blocks JSON 解析.
    """
    tool_calls = getattr(response, "tool_calls", None) or []
    for tc in tool_calls:
        inp = tc.get("input") if isinstance(tc, dict) else getattr(tc, "input", None)
        if isinstance(inp, dict):
            tier = str(inp.get("tier", "")).strip().lower()
            if tier in _VALID_INTENTS:
                return tier
    # 兜底: 文本里夹 {"tier": "..."}
    text_blocks = getattr(response, "text_blocks", None) or []
    for blk in text_blocks:
        text = blk.get("text", "") if isinstance(blk, dict) else getattr(blk, "text", "")
        if not text:
            continue
        m = re.search(r'"tier"\s*:\s*"([a-z]+)"', text)
        if m and m.group(1) in _VALID_INTENTS:
            return m.group(1)
    return None


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

    Debug: 设 PECKER_ROUTER_DEBUG=1 看 raw text + split 后 first word + 最终 tier.

    Tool-use 实验 (P3 候选): 设 PECKER_ROUTER_TOOL_USE=1 走 tool_use 强约束模式,
    输出 schema 限定 enum {opus,sonnet,haiku,reject}. CLI subprocess 没 native tool
    支持, fallback "prompt 注入 schema + 解析 JSON" (clients/claude_cli.py).
    """
    use_tool = os.environ.get("PECKER_ROUTER_TOOL_USE", "").strip() in ("1", "true", "True")

    # 容错: max_tokens 调到 16 留一点尾巴 (haiku 偶尔输出 "Sonnet." 多一字符就被截)
    user_content = f"PRD 名称：{prd_name}\n用户指令：{user_instruction}"
    msgs = [{
        "role": "user",
        "content": user_content,
    }]
    _router_debug_log(
        f"prompt_chars system={len(ROUTER_PROMPT)} user={len(user_content)} "
        f"tool_use={use_tool} prd_name={prd_name!r} "
        f"instruction_head={user_instruction[:60]!r}"
    )
    try:
        # tool_use 路径: schema 强约束 + 大 max_tokens 留 schema 注入位
        tool_kwargs: Dict[str, Any] = {}
        if use_tool:
            tool_kwargs = {
                "tools": [_INTENT_TOOL],
                "tool_choice": {"type": "tool", "name": "select_review_intent"},
            }

        if client is None:
            from model_router import route_call
            response = route_call(
                "router.intent",
                system=ROUTER_PROMPT,
                messages=msgs,
                max_tokens=512 if use_tool else 16,
                **tool_kwargs,
            )
        else:
            response = client.create(
                model=MODEL_TIERS["haiku"],
                max_tokens=512 if use_tool else 16,
                system=ROUTER_PROMPT,
                messages=msgs,
                **tool_kwargs,
            )

        # tool_use: 优先从 tool_calls 拿 tier
        if use_tool:
            tier = _extract_tier_from_tool_use(response)
            _router_debug_log(
                f"tool_use_tier={tier!r} "
                f"final={tier if tier in _VALID_INTENTS else 'sonnet(fallback)'}"
            )
            if tier in _VALID_INTENTS:
                return tier
            return "sonnet"

        # 容错解析: 取首词, 去标点 / 引号
        raw = response.content[0].text.strip().lower()
        tier = re.split(r"[\s\.,;:!?'\"]", raw, maxsplit=1)[0]
        _router_debug_log(
            f"raw={raw!r} first_word={tier!r} valid={tier in _VALID_INTENTS} "
            f"final={tier if tier in _VALID_INTENTS else 'sonnet(fallback)'}"
        )
        if tier in _VALID_INTENTS:
            return tier
    except Exception as e:
        _router_debug_log(f"exception={type(e).__name__}: {str(e)[:200]}")
    _router_debug_log(f"final=sonnet(fallback)")
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
