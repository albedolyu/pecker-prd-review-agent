"""Cluster C — 单 Worker 执行核心（prompt → Claude API → items 抽取）.

从 parallel_review.py 拆出 (2026-04-16 继续 SPLIT_PLAN 阶段 4):
- 常量: SUBMIT_REVIEW_ITEMS_TOOL (对外暴露的 tool schema)
- 内部: _get_compact_tool_schema (followup 催促重试用的精简版)
- 响应解析: _extract_items_from_response / _has_tool_use / _is_empty_tool_submission /
  _extract_text / _parse_items_from_text
- 执行核心: _worker_core / _run_worker_async / _run_worker_sync

本模块是唯一与 Claude Messages API 直接对话的层。依赖:
- review.prompting: 构建 system prompt / user messages
- review.dimensions: 维度配置 / MAX_WORKER_TURNS 常量

parallel_review.py re-export 这些符号, 测试里 patch("parallel_review._build_worker_*")
需要改到 patch("review.worker._build_worker_*"), 因为 patch 打在"使用"位置而非定义。
"""

import asyncio
import json
import os
import random
import time
from typing import Any, Dict, List, Optional

from logger import get_logger
from review.dimensions import (
    MAX_WORKER_TURNS,
    _cn_label,
    get_review_dimensions,
    get_wiki_keywords,
)
from review.prompting import (
    _WORKER_SHARED_RULES,
    _build_worker_messages,
    _build_worker_system,
)
from review.types import WorkerResult

log = get_logger("parallel")


# ============================================================
# _worker_core 的两个抽出 helpers (2026-04-23 #1 refactor):
# prepare_context 负责 dim/model/prompt/tool schema 构建 (L242-289);
# postprocess_items 负责 items 过滤/维度校正/越界/截断 (L389-420).
# retry 逻辑仍内联, closure state (_call / current_turn / empty_retry_used)
# 抽出来反而增加参数复杂度。
# ============================================================


def _prepare_worker_context(
    dim_key: str,
    model_tiers: Dict[str, str],
    rule_perf_history: Optional[Dict[str, Any]],
    wiki_path: Optional[str],
    wiki_pages: Dict[str, str],
    prd_content: str,
    diff_context: Optional[str] = None,
) -> Dict[str, Any]:
    """构建单 worker 所需的上下文: dim 配置 / model 选择 / system+messages /
    维度约束后的 tool schema / cache monitor / 各种 hash 指纹.

    返回字典(避免 NamedTuple 导入开销), 字段供 _worker_core 解构使用。
    """
    from agent_config import EFFORT_TOKENS
    from cache_monitor import PromptCacheMonitor
    import hashlib as _hl

    dimensions = get_review_dimensions()
    wiki_keywords = get_wiki_keywords()
    dim = dimensions[dim_key]
    model = model_tiers.get(dim["model"], model_tiers["sonnet"])

    effort = dim.get("effort", "medium")
    max_tokens = EFFORT_TOKENS.get(effort, 8192)

    cache_monitor = PromptCacheMonitor()
    workspace_dir = os.path.dirname(wiki_path) if wiki_path else None
    dynamic_system = _build_worker_system(dim_key, rule_perf_history, dimensions, workspace=workspace_dir)
    messages = _build_worker_messages(prd_content, wiki_pages, dim_key, wiki_path, wiki_keywords, diff_context)

    # system prompt 分静态/动态两段(CC DYNAMIC_BOUNDARY 模式), 静态段打 cache_control
    system_blocks = [
        {"type": "text", "text": _WORKER_SHARED_RULES, "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": dynamic_system},
    ]

    # prompt 指纹日志(CC firstChangedMessageIndex 模式)
    static_hash = _hl.md5(_WORKER_SHARED_RULES.encode()).hexdigest()[:8]
    dynamic_hash = _hl.md5(dynamic_system.encode()).hexdigest()[:8]
    msg_hash = _hl.md5(json.dumps(messages, ensure_ascii=False).encode()).hexdigest()[:8]
    log.info(f"[{_cn_label(dim_key)}] prompt_hash static={static_hash} dynamic={dynamic_hash} msg={msg_hash}")

    # 正向工具白名单: dimension 字段 schema const 约束为自身维度名
    dim_constrained_tool = json.loads(json.dumps(SUBMIT_REVIEW_ITEMS_TOOL))
    dim_constrained_tool["input_schema"]["properties"]["dimension"] = {
        "type": "string",
        "const": dim["name"],
        "description": f"评审维度(必须填 '{dim['name']}')",
    }

    return {
        "dim": dim,
        "model": model,
        "max_tokens": max_tokens,
        "system_blocks": system_blocks,
        "messages": messages,
        "dim_constrained_tool": dim_constrained_tool,
        "cache_monitor": cache_monitor,
    }


def _postprocess_items(
    items: List[Dict[str, Any]],
    dim: Dict[str, Any],
    dim_key: str,
) -> List[Dict[str, Any]]:
    """items 后处理: 过滤非 dict / 维度校正 / 规则越界标注 / MAX_ITEMS 截断.

    纯函数, 可独立单测. 入参 dim 是 dimensions[dim_key] 配置, 包含 name/checklist.
    """
    from agent_config import MAX_ITEMS_PER_WORKER

    # 过滤非 dict (模型偶尔返回字符串数组而非对象数组)
    items = [item for item in items if isinstance(item, dict)]

    # 强制校正维度名 (防止模型绕过 schema const)
    for item in items:
        if item.get("dimension") and item["dimension"] != dim["name"]:
            log.warning(f"[{_cn_label(dim_key)}] 维度越界: {item.get('dimension')} → {dim['name']}")
        item["dimension"] = dim["name"]

    # P1.3: 规则越界硬校验 — checklist 里定义的 rule_id 才算本维度合法
    valid_rule_ids = {r["rule_id"] for r in dim.get("checklist", [])}
    for item in items:
        rid = item.get("rule_id", "")
        if rid and valid_rule_ids and rid not in valid_rule_ids:
            log.warning(f"[{_cn_label(dim_key)}] 规则越界: {rid} 不在 {dim_key} checklist 中")
            item["cross_boundary"] = True
            # 2026-04-16 harness audit 修复: 原先改 confidence, 下游只读
            # confidence_score, 让惩罚静默失效. 统一成 confidence_score.
            current = item.get("confidence_score", 0.85)
            item["confidence_score"] = max(0.0, round(current - 0.3, 2))

    # 2a: Tool Result 截断 — 单 worker 输出上限(CC tool result truncation 模式)
    if len(items) > MAX_ITEMS_PER_WORKER:
        log.warning(f"[{_cn_label(dim_key)}] Worker 输出 {len(items)} 条, 截断到 {MAX_ITEMS_PER_WORKER}")
        # 按 severity(must 优先) + confidence(高优先) 排序, 保留 top N
        items.sort(key=lambda x: (0 if x.get("severity") == "must" else 1, -x.get("confidence_score", 0)))
        items = items[:MAX_ITEMS_PER_WORKER]

    return items


# ============================================================
# 结构化输出 Tool Schema
# ============================================================


def _get_compact_tool_schema():
    """Pattern 17: Deferred Tool Loading — 精简版 tool schema。

    followup 催促重试时用精简版,去掉 items 数组里每个字段的长 description,
    减少 prompt token 占用。tool name / input_schema structure 不变,
    模型仍能正确调用。
    """
    return {
        "name": "submit_review_items",
        "description": "提交评审发现的问题项。全部 pass 时 items 为空数组。",
        "input_schema": {
            "type": "object",
            "properties": {
                "dimension": {"type": "string"},
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "rule_id": {"type": "string"},
                            "location": {"type": "string"},
                            "issue": {"type": "string"},
                            "suggestion": {"type": "string"},
                            "severity": {"type": "string", "enum": ["must", "should"]},
                            "evidence_type": {"type": "string", "enum": ["A", "B", "C"]},
                            "evidence_content": {"type": "string"},
                        },
                        "required": ["rule_id", "location", "issue", "suggestion", "severity", "evidence_type", "evidence_content"],
                    },
                },
                "confidence_in_findings": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                "null_finding_reason": {"type": "string"},
            },
            "required": ["dimension", "items"],
        },
    }


SUBMIT_REVIEW_ITEMS_TOOL = {
    "name": "submit_review_items",
    "description": (
        "提交评审中发现的问题项。逐条检查 checklist 后,仅提交 fail 的规则。"
        "全部 pass 时,items 必须为空数组,同时 null_finding_reason 必须填写说明你已逐条看过"
        "(缺失 ④ Worker 拒答出口:允许承认 PRD 这一维度无问题,而不是硬找)。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "dimension": {"type": "string", "description": "评审维度"},
            "items": {
                "type": "array",
                "description": (
                    "仅提交发现问题的规则项。同一规则在多处违反时可提交多条"
                    "(rule_id 相同但 location 不同)。如果全部规则都通过则提交空数组。"
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "rule_id": {"type": "string", "description": "规则编号如 V-02, RC-005"},
                        "location": {"type": "string", "description": "PRD 中的章节"},
                        "issue": {"type": "string", "description": "具体问题"},
                        "suggestion": {"type": "string", "description": "改进建议"},
                        "severity": {"type": "string", "enum": ["must", "should"]},
                        "evidence_type": {"type": "string", "enum": ["A", "B", "C"]},
                        "evidence_content": {"type": "string", "description": "依据内容"},
                    },
                    "required": ["rule_id", "location", "issue", "suggestion", "severity", "evidence_type", "evidence_content"],
                },
            },
            "confidence_in_findings": {
                "type": "number",
                "minimum": 0.0,
                "maximum": 1.0,
                "description": (
                    "你对本次发现的整体置信度 0.0-1.0。如果 PRD 这一维度看完不确定有问题,"
                    "降低置信度;不要为了凑数硬找。"
                ),
                "default": 1.0,
            },
            "null_finding_reason": {
                "type": "string",
                "description": (
                    "items 为空时必填:简述你为什么认为本维度无 fail(逐条扫了哪些规则,"
                    "为什么都 pass)。这是缺失 ④ 的 Worker 拒答出口,胡乱拒答会被苍鹰反驳。"
                    "items 非空时此字段可为空。"
                ),
                "default": "",
            },
        },
        "required": ["dimension", "items"],
    },
}


# ============================================================
# 响应解析
# ============================================================


def _extract_items_from_response(response):
    """从 Messages API 响应中提取所有 submit_review_items 的 tool_use 结果"""
    all_items = []
    for block in response.content:
        if block.type == "tool_use" and block.name == "submit_review_items":
            items = block.input.get("items", [])
            # 中转站大 payload 修复：items 可能被拆成字符数组，拼接后重新解析
            if items and isinstance(items[0], str) and len(items) > 10:
                try:
                    joined = "".join(items)
                    # 确保是有效的 JSON 数组
                    if not joined.strip().startswith("["):
                        joined = "[" + joined + "]"
                    parsed = json.loads(joined)
                    if isinstance(parsed, list):
                        items = parsed
                        log.info(f"修复字符数组: {len(items)} chars → {len(parsed)} items")
                except (json.JSONDecodeError, TypeError):
                    log.warning(f"字符数组修复失败，尝试提取 JSON 对象")
                    # 兜底：从拼接字符串中提取所有 JSON 对象
                    import re as _re
                    objects = _re.findall(r'\{[^{}]*\}', joined)
                    items = []
                    for obj_str in objects:
                        try:
                            items.append(json.loads(obj_str))
                        except json.JSONDecodeError:
                            continue
            all_items.extend(items)
    # 统一编号（过滤非 dict 元素）
    all_items = [item for item in all_items if isinstance(item, dict)]
    # B4: 给 Worker 产出的 item 打上 confidence_score,让 merge/伯劳能消费
    from cuckoo_parser import compute_confidence
    for i, item in enumerate(all_items, 1):
        if "id" not in item:
            item["id"] = f"R-{i:03d}"
        if "confidence_score" not in item:
            item["confidence_score"] = compute_confidence(item.get("evidence_type", ""))
    return all_items


def _has_tool_use(response):
    """检查响应中是否包含 tool_use block"""
    return any(block.type == "tool_use" for block in response.content)


def _is_empty_tool_submission(response) -> bool:
    """模型调了 submit_review_items 但 items 数组为空。

    这是 data_quality / quality worker 50% 静默率的典型触发点:
    模型 tool_choice=any 被强制走 tool,但没想到具体改进项,交了空提交。
    与"没调 tool"不同,不能用 _has_tool_use 检测,需要检查 items 字段。
    """
    for block in response.content:
        if block.type == "tool_use" and block.name == "submit_review_items":
            items = block.input.get("items", [])
            if not items:
                return True
    return False


def _extract_text(response):
    """从响应中提取纯文本"""
    return "\n".join(block.text for block in response.content if block.type == "text")


def _parse_items_from_text(text):
    """兜底：从纯文本中提取 JSON 格式的改进项（模型没调 tool 时）"""
    import re as _re
    from cuckoo_parser import compute_confidence  # B4
    # 尝试提取 JSON 数组
    m = _re.search(r'\[[\s\S]*?\]', text)
    if m:
        try:
            items = json.loads(m.group())
            if isinstance(items, list) and items:
                for i, item in enumerate(items, 1):
                    if isinstance(item, dict):
                        if "id" not in item:
                            item["id"] = f"R-{i:03d}"
                        if "confidence_score" not in item:
                            item["confidence_score"] = compute_confidence(item.get("evidence_type", ""))
                return items
        except (json.JSONDecodeError, TypeError):
            pass
    return []


# ============================================================
# 执行核心
# ============================================================


def _worker_core(client, dim_key, prd_content, wiki_pages, model_tiers, rule_perf_history=None, wiki_path=None, diff_context=None) -> WorkerResult:
    """Worker 核心逻辑（sync），返回首次 API 响应和处理后的 items 列表。
    async 版本通过 run_in_executor 包装此函数。

    返回 review.types.WorkerResult (TypedDict): dimension/items/usage/cost_usd/
    model_used/telemetry; 运行时仍是普通 dict, TypedDict 只给 IDE/mypy 静态检查。
    """
    # 3a: telemetry — 记录 worker 开始时间
    start_time = time.time()

    # 上下文构建抽到 _prepare_worker_context (见本文件前部定义)
    ctx = _prepare_worker_context(
        dim_key, model_tiers, rule_perf_history, wiki_path, wiki_pages,
        prd_content, diff_context,
    )
    dim = ctx["dim"]
    model = ctx["model"]
    max_tokens = ctx["max_tokens"]
    system_blocks = ctx["system_blocks"]
    messages = ctx["messages"]
    dim_constrained_tool = ctx["dim_constrained_tool"]
    cache_monitor = ctx["cache_monitor"]

    def _call(msgs, use_compact_tool=False):
        # Pattern 17: followup 催促重试时用精简版 tool schema
        tool_to_use = dim_constrained_tool
        if use_compact_tool:
            tool_to_use = _get_compact_tool_schema()
            tool_to_use["input_schema"]["properties"]["dimension"] = {
                "type": "string",
                "const": dim["name"],
            }

        # Pattern 18: snapshot before API call
        system_text = json.dumps(system_blocks, ensure_ascii=False)
        tools_json = json.dumps([tool_to_use], ensure_ascii=False)
        cache_monitor.snapshot(system_text, tools_json, model, dim_key=dim_key)

        resp = client.create(
            model=model,
            max_tokens=max_tokens,  # Pattern 20: effort-aware
            system=system_blocks,
            messages=msgs,
            tools=[tool_to_use],
            tool_choice={"type": "any"},
            retry_policy="worker",
        )

        # Pattern 18: check after API response
        cache_monitor.check(resp.usage)

        return resp

    # client.create 内部已有分级重试，不再外层重复
    response = _call(messages)

    items = _extract_items_from_response(response)

    # Tool 调用检测 + 催促重试 + 文本兜底 (CC maxTurns 约束)
    current_turn = 1  # 已用 1 轮
    empty_retry_used = False  # telemetry: 是否触发了"空提交重试"分支
    if not _has_tool_use(response) and current_turn < MAX_WORKER_TURNS:
        current_turn += 1
        log.warning(f"[{_cn_label(dim_key)}] turn={current_turn}/{MAX_WORKER_TURNS} 未调用 tool,催促重试")
        text = _extract_text(response)
        followup_msgs = messages + [
            {"role": "assistant", "content": text},
            {"role": "user", "content": "请使用 submit_review_items 工具提交你的评审结果。"},
        ]
        time.sleep(2 + random.uniform(0, 0.5))
        try:
            # Pattern 17: followup 用精简版 tool schema 节省 token
            response2 = _call(followup_msgs, use_compact_tool=True)
            items = _extract_items_from_response(response2)
            if _has_tool_use(response2):
                response = response2
        except Exception as e:
            log.warning(f"[{_cn_label(dim_key)}] 催促重试失败: {str(e)[:80]}")

        if not items and text:
            items = _parse_items_from_text(text)
            if items:
                log.info(f"[{_cn_label(dim_key)}] 从文本中解析出 {len(items)} 条改进项")
    elif _is_empty_tool_submission(response) and current_turn < MAX_WORKER_TURNS:
        # 空提交重试: 模型调了 tool 但 items=[],常见于 data_quality/quality
        # 静默率 50% 的典型场景 (session 2 真实出现)。
        # 给一次复检机会,让它要么补充遗漏要么写清楚"为何为空"。
        current_turn += 1
        empty_retry_used = True
        log.warning(f"[{_cn_label(dim_key)}] turn={current_turn}/{MAX_WORKER_TURNS} 空提交,re-prompt 复检")
        prev_text = _extract_text(response)
        followup_msgs = messages + [
            {"role": "assistant",
             "content": prev_text or "(我已完成首次审查,提交了 0 条改进项)"},
            {"role": "user",
             "content": ("你刚才用 submit_review_items 提交了 0 条改进项。请在本维度 checklist 里"
                         "逐条复核一遍,如仍认为无问题请在 items 里提交一条 severity='nit'、"
                         "location='整体'、issue='本维度复核后确认无问题:简述检查了哪 3 条具体项'"
                         "作为显式确认;如有遗漏请重新 submit_review_items。")},
        ]
        time.sleep(2 + random.uniform(0, 0.5))
        try:
            response2 = _call(followup_msgs, use_compact_tool=True)
            retry_items = _extract_items_from_response(response2)
            if retry_items:
                items = retry_items
                response = response2
                log.info(f"[{_cn_label(dim_key)}] 空提交复检后出了 {len(items)} 条")
            else:
                log.info(f"[{_cn_label(dim_key)}] 空提交复检后仍为 0 条 (可能真无问题)")
        except Exception as e:
            log.warning(f"[{_cn_label(dim_key)}] 空提交复检失败: {str(e)[:80]}")
    elif not _has_tool_use(response):
        # maxTurns 已耗尽,直接走文本兜底
        log.warning(f"[{_cn_label(dim_key)}] maxTurns={MAX_WORKER_TURNS} 已耗尽,走文本兜底")
        text = _extract_text(response)
        if text:
            items = _parse_items_from_text(text)
            if items:
                log.info(f"[{_cn_label(dim_key)}] 文本兜底解析出 {len(items)} 条改进项")

    # items 后处理抽到 _postprocess_items (纯函数, 可独立单测)
    items = _postprocess_items(items, dim, dim_key)

    # 提取 worker 发现的关键规则 ID（供 scratchpad 跨 worker 共享）
    found_rule_ids = list(set(item.get("rule_id", "") for item in items if item.get("rule_id")))

    # 成本归因 (CC cost-tracker querySource 模式)
    from api_adapter import compute_call_cost_usd
    worker_usage = {
        "input_tokens": response.usage["input_tokens"],
        "output_tokens": response.usage["output_tokens"],
        "cache_read_input_tokens": response.usage.get("cache_read_input_tokens", 0),
        "cache_creation_input_tokens": response.usage.get("cache_creation_input_tokens", 0),
    }
    cost_usd = compute_call_cost_usd(model, worker_usage)

    # 3a: 结构化 telemetry (CC telemetry 模式)
    is_degraded = (len(items) == 0 and bool(worker_usage.get("output_tokens", 0)))
    telemetry = {
        "duration_ms": int((time.time() - start_time) * 1000),
        "tokens_in": worker_usage["input_tokens"],
        "tokens_out": worker_usage["output_tokens"],
        "cost_usd": cost_usd,
        "items_count": len(items),
        "degraded": is_degraded,
        "turns_used": current_turn,
        "truncated": getattr(response, "truncated", False),
        "empty_retry_used": empty_retry_used,
    }

    return {
        "dimension": dim_key,
        "dimension_name": dim["name"],
        "model": model,
        "items": items,
        "found_rule_ids": found_rule_ids,
        "usage": {
            "input_tokens": response.usage["input_tokens"],
            "output_tokens": response.usage["output_tokens"],
        },
        "cost_usd": cost_usd,
        "telemetry": telemetry,
    }


async def _run_worker_async(client, dim_key, prd_content, wiki_pages, model_tiers, rule_perf_history=None, wiki_path=None, diff_context=None) -> WorkerResult:
    """异步包装：在线程池中执行 _worker_core，带超时保护"""
    from agent_config import WORKER_TIMEOUT
    loop = asyncio.get_running_loop()
    try:
        return await asyncio.wait_for(
            loop.run_in_executor(
                None, lambda: _worker_core(client, dim_key, prd_content, wiki_pages, model_tiers, rule_perf_history, wiki_path, diff_context)
            ),
            timeout=WORKER_TIMEOUT,
        )
    except asyncio.TimeoutError:
        # 超时 Worker 不抛出,返回错误结构,让 gather 正常汇总其他 Worker 结果
        dim_name = get_review_dimensions().get(dim_key, {}).get("name", dim_key)
        log.warning(f"[{_cn_label(dim_key)}] Worker 超时({WORKER_TIMEOUT}s),跳过")
        return {
            "dimension": dim_key,
            "dimension_name": dim_name,
            "error": f"Worker 超时({WORKER_TIMEOUT}s)",
            "items": [],
            "usage": {"input_tokens": 0, "output_tokens": 0},
            "status": "timeout",
        }


def _run_worker_sync(client, dim_key, prd_content, wiki_pages, model_tiers, rule_perf_history=None, wiki_path=None, diff_context=None) -> WorkerResult:
    """同步包装：直接调用 _worker_core"""
    return _worker_core(client, dim_key, prd_content, wiki_pages, model_tiers, rule_perf_history, wiki_path, diff_context)
