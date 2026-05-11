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

# Metrics 埋点 — 失败 silent skip, 不阻 review 主流程
try:
    from review.metrics_store import record_event as _record_event
except Exception:
    def _record_event(*args, **kwargs):  # noqa: ARG001
        return False


def _timeout_recovery_enabled() -> bool:
    return os.environ.get("PECKER_ENABLE_WORKER_TIMEOUT_RECOVERY", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


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
    wiki_budget_chars: Optional[int] = None,
    route_model_override: Optional[str] = None,
    recovery_mode: bool = False,
    prd_context_packet: Optional[str] = None,
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
    # GPT-only 路由由 model_routes.yaml 按 worker.<dim_key> 统一分档.
    # 这里只解析"显示用 model 名",
    # 真正的 client.create 已迁到 route_call. model_tiers 入参变 deprecated 兼容
    # orchestration 老调用方, 内部不再使用.
    from model_router import get_model_for_route
    dim_tier_alias = dim.get("model")  # "sonnet" / "opus" / "haiku" or None
    try:
        model = get_model_for_route(f"worker.{dim_key}", model_override=route_model_override)
    except Exception:
        # routes.yaml 未配 worker.<dim_key> 也 fallback 失败时, 兜底用 model_tiers 老路径,
        # 仅用于 telemetry / log 显示, 真正调用走 route_call 自身的 fallback.
        # 注意: 不写硬编码模型名, 终极兜底用 model_tiers 自带的 sonnet 别名 (即使值为 None,
        # client 层 _map_model 已会 fallback, 见 test_claude_cli_map_model_none_fallbacks_to_sonnet).
        model = (model_tiers or {}).get(dim_tier_alias or "sonnet") or (model_tiers or {}).get("sonnet")

    effort = dim.get("effort", "medium")
    max_tokens = EFFORT_TOKENS.get(effort, 8192)

    cache_monitor = PromptCacheMonitor()
    workspace_dir = os.path.dirname(wiki_path) if wiki_path else None
    dynamic_system = _build_worker_system(dim_key, rule_perf_history, dimensions, workspace=workspace_dir)
    wiki_selection_telemetry: Dict[str, Any] = {}

    def _capture_wiki_selection(telemetry: Dict[str, Any]) -> None:
        wiki_selection_telemetry.clear()
        wiki_selection_telemetry.update(telemetry)

    messages = _build_worker_messages(
        prd_content,
        wiki_pages,
        dim_key,
        wiki_path,
        wiki_keywords,
        diff_context,
        on_wiki_selection=_capture_wiki_selection,
        wiki_budget_chars=wiki_budget_chars,
        recovery_mode=recovery_mode,
        prd_context_packet=prd_context_packet,
    )

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

    # step 3.3 registry 注入 rule_id enum (硬挡 LLM 幻觉 ID, P0-B 反模式核心修法)
    # — 替代 prompt 软约束 + 后置 cross_boundary 静默打标. Anthropic API
    # 直接拒非法 rule_id, 让 worker 不能用 DQ-XX/AC-XX 这种幻觉 ID 绕开.
    # PECKER_SCHEMA_FALLBACK=1 时 fallback 到 dim["checklist"] 现算 (兼容老路径).
    try:
        from review.schema_registry import SchemaRegistry
        _registry = SchemaRegistry.get(workspace=None)
        _dim_rule_ids = sorted(r.rule_id for r in _registry.dimension_rules(dim_key))
    except Exception:
        _dim_rule_ids = sorted(
            r.get("rule_id") for r in dim.get("checklist", []) if r.get("rule_id")
        )
    if _dim_rule_ids:
        dim_constrained_tool["input_schema"]["properties"]["items"]["items"][
            "properties"
        ]["rule_id"]["enum"] = _dim_rule_ids

    return {
        "dim": dim,
        "dim_key": dim_key,                  # Wave 2: 给 _worker_core 转 route_id
        "dim_tier_alias": dim_tier_alias,    # legacy dimensions.yaml tier, 保留给兼容 telemetry
        "route_model_override": route_model_override,
        "recovery_mode": recovery_mode,
        "model": model,                       # 解析后的实名 (telemetry / cost / log)
        "max_tokens": max_tokens,
        "system_blocks": system_blocks,
        "messages": messages,
        "dim_constrained_tool": dim_constrained_tool,
        "cache_monitor": cache_monitor,
        "wiki_selection_telemetry": wiki_selection_telemetry,
        "prd_context_packet_chars": len(prd_context_packet or ""),
    }


def _postprocess_items(
    items: List[Dict[str, Any]],
    dim: Dict[str, Any],
    dim_key: str,
) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """items 后处理: 过滤非 dict / 维度校正 / 规则越界标注 / MAX_ITEMS 软上限截断.

    纯函数, 可独立单测. 入参 dim 是 dimensions[dim_key] 配置, 包含 name/checklist.

    2026-04-26 sprint Day3 P0-2: 截断从硬上限 (15) 改软上限 (15 * 1.5 = 22 默认).
    实测 sampling noise: 同 PRD 同 codebase N0 浮动 8-18, 17%~100% 命中硬截断 → 14.5% overlap.
    软上限让常见量级 (8-22) 全保留, 仅在异常多产 (>22) 时截. 越界时 + WORKER_SEED 确定排序.

    2026-04-28 P1 anti-corruption drop (任务 2 R3 暴露):
    rule_id 校验改 3 类区分 (走 SchemaRegistry, 不再依赖 dim['checklist'] 现算):
      ∈ all_rule_ids ∩ dim_rule_ids   → 留 (合法本维度)
      ∈ all_rule_ids \\ dim_rule_ids  → 留 + cross_boundary 标 (跨维度合法)
      ∉ all_rule_ids                  → drop + log warning (LLM 幻觉 ID)
    返回 (items, drop_telemetry) tuple — drop_telemetry 含 dropped_unknown_rule_count
    用于 funnel jsonl emit.
    """
    from agent_config import MAX_ITEMS_PER_WORKER, WORKER_SOFT_CAP_MULTIPLIER, WORKER_SEED
    from review.schema_registry import SchemaRegistry

    # 过滤非 dict (模型偶尔返回字符串数组而非对象数组)
    items = [item for item in items if isinstance(item, dict)]

    # 强制校正维度名 (防止模型绕过 schema const)
    for item in items:
        if item.get("dimension") and item["dimension"] != dim["name"]:
            log.warning(f"[{_cn_label(dim_key)}] 维度越界: {item.get('dimension')} → {dim['name']}")
        item["dimension"] = dim["name"]

    # P1 anti-corruption drop (2026-04-28): registry 单点 SoT 做 3 类区分
    # 走 SchemaRegistry.get() workspace=None (workspace 上下文从 dim 推不出, 默认 global yaml)
    # 不影响真 worker — 真 worker 的 dim 来自 get_review_dimensions, 与 registry 同源
    registry = SchemaRegistry.get(workspace=None)
    all_rule_ids = registry.all_rule_ids()  # frozenset
    dim_rule_ids = {r.rule_id for r in registry.dimension_rules(dim_key)}

    kept_items: List[Dict[str, Any]] = []
    dropped_unknown_count = 0
    dropped_unknown_ids: List[str] = []

    for item in items:
        rid = item.get("rule_id", "")
        if not rid:
            # 无 rule_id 不动 (老行为兼容, parse 失败兜底)
            kept_items.append(item)
            continue
        if rid not in all_rule_ids:
            # 第 3 类: 幻觉 ID — drop
            dropped_unknown_count += 1
            dropped_unknown_ids.append(rid)
            log.warning(
                f"[{_cn_label(dim_key)}] drop_unknown_rule_id: rule_id={rid!r} "
                f"不在 registry.all_rule_ids() (LLM 幻觉, 任务 2 R3 暴露)"
            )
            continue
        if rid not in dim_rule_ids:
            # 第 2 类: 跨维度合法 — 留 + 标 (老 defense-in-depth 行为保留)
            log.warning(f"[{_cn_label(dim_key)}] 规则越界: {rid} 不在 {dim_key} 维度内 (但 ∈ registry)")
            item["cross_boundary"] = True
            current = item.get("confidence_score", 0.85)
            item["confidence_score"] = max(0.0, round(current - 0.3, 2))
        # 第 1 类 (合法本维度) 走默认: 不打标, 直接留
        kept_items.append(item)

    items = kept_items

    # 2026-04-26 P0-2: 软上限截断 — 大部分 PRD 不会触发, sampling noise 在边界处消失
    soft_cap = max(MAX_ITEMS_PER_WORKER, int(MAX_ITEMS_PER_WORKER * WORKER_SOFT_CAP_MULTIPLIER))
    if len(items) > soft_cap:
        log.warning(
            f"[{_cn_label(dim_key)}] Worker 输出 {len(items)} 条 > soft_cap {soft_cap}, "
            f"截断 (base={MAX_ITEMS_PER_WORKER} × {WORKER_SOFT_CAP_MULTIPLIER})"
        )
        # 按 severity(must 优先) + confidence(高优先) 排序, 保留 top N
        # WORKER_SEED 非空时 tie-break 用 hash(seed + rule_id + issue), 让 consistency_eval 可复现
        if WORKER_SEED:
            import hashlib
            def _seed_key(item):
                # 主序: severity + confidence (业务排序保留)
                # 次序: hash(seed + rule_id + issue 前 50 字), 让相同输入 deterministic
                hash_input = f"{WORKER_SEED}|{item.get('rule_id', '')}|{(item.get('issue', '') or '')[:50]}"
                tie = hashlib.md5(hash_input.encode("utf-8", errors="replace")).hexdigest()
                return (
                    0 if item.get("severity") == "must" else 1,
                    -item.get("confidence_score", 0),
                    tie,
                )
            items.sort(key=_seed_key)
        else:
            items.sort(key=lambda x: (0 if x.get("severity") == "must" else 1, -x.get("confidence_score", 0)))
        items = items[:soft_cap]

    drop_telemetry = {
        "dropped_unknown_rule_count": dropped_unknown_count,
        "dropped_unknown_rule_ids": dropped_unknown_ids,
    }
    return items, drop_telemetry


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
                        # 2026-04-26 CaRR (Chaining the Evidence) 借鉴 arXiv 2601.06021:
                        # 复杂 finding 可选给多跳 evidence chain, 每跳必须有 claim + citation,
                        # 让下游 evidence_verifier 检查推理链完整性. 简单 finding 留空数组.
                        "evidence_chain": {
                            "type": "array",
                            "description": (
                                "可选: 复杂 finding 的多跳证据链 (CaRR). 每跳给 claim + citation. "
                                "建议复杂 finding (跨多章节 / 多 wiki 页面 / 涉及推理) 给 chain. "
                                "简单 finding 留空数组. 不强制. 留空时 evidence_content 单条引用即可."
                            ),
                            "items": {
                                "type": "object",
                                "properties": {
                                    "hop_idx": {"type": "integer", "description": "跳序号 1, 2, 3..."},
                                    "claim": {"type": "string", "description": "本跳推理结论"},
                                    "citation": {
                                        "type": "string",
                                        "description": "PRD 章节号 (如 '第 3.2 节') 或 [[wiki 页面]] 引用",
                                    },
                                },
                                "required": ["hop_idx", "claim", "citation"],
                            },
                            "default": [],
                        },
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
    from review.confidence import compute_confidence
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


def _empty_submission_reason(response) -> str:
    """提取空提交时的 null_finding_reason。

    items=[] 本身可能是 worker 真正检查后给出的 clean 结论;只有同时带
    null_finding_reason,下游 STATUS 才能把它从"静默"里剥离出来。
    """
    for block in response.content:
        if block.type == "tool_use" and block.name == "submit_review_items":
            items = block.input.get("items", [])
            if items:
                continue
            reason = block.input.get("null_finding_reason", "")
            if isinstance(reason, str):
                reason = reason.strip()
                if reason:
                    return reason
    return ""


def _extract_text(response):
    """从响应中提取纯文本"""
    return "\n".join(block.text for block in response.content if block.type == "text")


def _parse_items_from_text(text):
    """兜底：从纯文本中提取 JSON 格式的改进项（模型没调 tool 时）"""
    import re as _re
    from review.confidence import compute_confidence  # B4
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


def _worker_core(
    client,
    dim_key,
    prd_content,
    wiki_pages,
    model_tiers,
    rule_perf_history=None,
    wiki_path=None,
    diff_context=None,
    on_tool_call=None,
    wiki_budget_chars=None,
    route_model_override=None,
    recovery_mode=False,
    prd_context_packet=None,
) -> WorkerResult:
    """Worker 核心逻辑（sync），返回首次 API 响应和处理后的 items 列表。
    async 版本通过 run_in_executor 包装此函数。

    返回 review.types.WorkerResult (TypedDict): dimension/items/usage/cost_usd/
    model_used/telemetry; 运行时仍是普通 dict, TypedDict 只给 IDE/mypy 静态检查。

    on_tool_call: 可选 callback(trace_dict) -> None. 每次 client.create 成功后调用,
    trace 含 {dim_key, kind=initial/prompt_followup/empty_retry_followup, model,
    duration_ms, input_tokens, output_tokens, cache_read}. 给 FastAPI SSE /
    EventStore 记 per-tool-call 粒度. CLI 模式 None 跳过, 零影响.
    """
    # 3a: telemetry — 记录 worker 开始时间
    start_time = time.time()

    # Metrics 埋点: worker.started (workspace 从 wiki_path 反推)
    _ws_for_metrics = os.path.dirname(wiki_path) if wiki_path else None
    try:
        _record_event(
            "worker.started",
            workspace=_ws_for_metrics,
            details={"dim_key": dim_key},
        )
    except Exception:
        pass

    # 上下文构建抽到 _prepare_worker_context (见本文件前部定义)
    try:
        ctx = _prepare_worker_context(
            dim_key, model_tiers, rule_perf_history, wiki_path, wiki_pages,
            prd_content, diff_context,
            wiki_budget_chars=wiki_budget_chars,
            route_model_override=route_model_override,
            recovery_mode=recovery_mode,
            prd_context_packet=prd_context_packet,
        )
    except Exception as _ctx_err:
        try:
            _record_event(
                "worker.failed",
                workspace=_ws_for_metrics,
                duration_ms=int((time.time() - start_time) * 1000),
                status="failed",
                details={"dim_key": dim_key, "error": str(_ctx_err)[:200], "stage": "prepare_context"},
            )
        except Exception:
            pass
        raise
    dim = ctx["dim"]
    model = ctx["model"]
    dim_tier_alias = ctx["dim_tier_alias"]
    route_model_override = ctx.get("route_model_override")
    max_tokens = ctx["max_tokens"]
    system_blocks = ctx["system_blocks"]
    messages = ctx["messages"]
    dim_constrained_tool = ctx["dim_constrained_tool"]
    cache_monitor = ctx["cache_monitor"]
    wiki_selection_telemetry = ctx.get("wiki_selection_telemetry", {})

    # Wave 2: 默认走 model_router 路由 (worker.<dim_key>). client 入参变 deprecated 但保留,
    # 显式传 client (e.g. e2e MagicMock 测试 / orchestration 注入) 时仍走 client.create
    # 兼容老 mock 通道 — _llm_nli_score 同款处理.
    from model_router import route_call
    use_router = client is None

    def _call(msgs, use_compact_tool=False, call_kind="initial"):
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

        _t0 = time.time()
        if use_router:
            resp = route_call(
                f"worker.{dim_key}",
                system=system_blocks,
                messages=msgs,
                tools=[tool_to_use],
                tool_choice={"type": "any"},
                max_tokens=max_tokens,            # Pattern 20: effort-aware
                model_override=route_model_override,
            )
        else:
            # 老 caller (传 client) 路径: 兼容 e2e mock 测试和 orchestration 注入
            resp = client.create(
                model=model,
                max_tokens=max_tokens,
                system=system_blocks,
                messages=msgs,
                tools=[tool_to_use],
                tool_choice={"type": "any"},
                retry_policy="worker",
            )
        _t1 = time.time()

        # Pattern 18: check after API response
        cache_monitor.check(resp.usage)

        # Per-tool-call trace (2026-04-23 B): 给 EventStore 记细粒度 tool 调用
        if on_tool_call is not None:
            try:
                on_tool_call({
                    "dim_key": dim_key,
                    "kind": call_kind,
                    "model": model,
                    "duration_ms": int((_t1 - _t0) * 1000),
                    "input_tokens": resp.usage.get("input_tokens", 0),
                    "output_tokens": resp.usage.get("output_tokens", 0),
                    "cache_read_tokens": resp.usage.get("cache_read_input_tokens", 0),
                    "key_id": resp.usage.get("key_id"),
                    "key_pool_size": resp.usage.get("key_pool_size"),
                    "attempts": resp.usage.get("attempts"),
                    "use_compact_tool": use_compact_tool,
                })
            except Exception:
                pass  # callback 异常不影响主流程

        return resp

    # client.create 内部已有分级重试，不再外层重复
    try:
        response = _call(messages)
    except Exception as _call_err:
        try:
            _record_event(
                "worker.failed",
                workspace=_ws_for_metrics,
                duration_ms=int((time.time() - start_time) * 1000),
                model=model,
                status="failed",
                details={"dim_key": dim_key, "error": str(_call_err)[:200], "stage": "initial_call"},
            )
        except Exception:
            pass
        raise

    items = _extract_items_from_response(response)
    empty_submission_reason = _empty_submission_reason(response)
    empty_submission_confirmed = bool(empty_submission_reason)

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
            response2 = _call(followup_msgs, use_compact_tool=True, call_kind="prompt_followup")
            items = _extract_items_from_response(response2)
            if _has_tool_use(response2):
                response = response2
        except Exception as e:
            log.warning(f"[{_cn_label(dim_key)}] 催促重试失败: {str(e)[:80]}")

        if not items and text:
            items = _parse_items_from_text(text)
            if items:
                log.info(f"[{_cn_label(dim_key)}] 从文本中解析出 {len(items)} 条改进项")
    elif (
        _is_empty_tool_submission(response)
        and not empty_submission_confirmed
        and current_turn < MAX_WORKER_TURNS
    ):
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
             "content": ("你刚才用 submit_review_items 提交了 0 条改进项。请逐条复核本维度 "
                         "checklist。若有遗漏,请提交真实 items;若仍确认无问题,请再次调用 "
                         "submit_review_items,保持 items=[],并填写 null_finding_reason,至少列出 "
                         "3 条已核查规则及通过理由。不要提交\"无问题\"占位 item。")},
        ]
        time.sleep(2 + random.uniform(0, 0.5))
        try:
            response2 = _call(followup_msgs, use_compact_tool=True, call_kind="empty_retry_followup")
            retry_items = _extract_items_from_response(response2)
            retry_reason = _empty_submission_reason(response2)
            if retry_items:
                items = retry_items
                response = response2
                empty_submission_reason = ""
                empty_submission_confirmed = False
                log.info(f"[{_cn_label(dim_key)}] 空提交复检后出了 {len(items)} 条")
            else:
                if _has_tool_use(response2):
                    response = response2
                empty_submission_reason = retry_reason
                empty_submission_confirmed = bool(retry_reason)
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
    # 2026-04-28 P1: 返 (items, drop_telemetry), drop_telemetry 含 dropped_unknown_rule_count
    items, drop_telemetry = _postprocess_items(items, dim, dim_key)

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
    is_degraded = (
        len(items) == 0
        and bool(worker_usage.get("output_tokens", 0))
        and not empty_submission_confirmed
    )
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
        "empty_submission_confirmed": empty_submission_confirmed,
        "empty_submission_reason": empty_submission_reason[:300],
        "wiki_selection": wiki_selection_telemetry,
        "prd_context_packet_chars": ctx.get("prd_context_packet_chars", 0),
        # 2026-04-28 P1 anti-corruption drop: LLM 出未知 rule_id 数 (任务 2 R3 暴露)
        "dropped_unknown_rule_count": drop_telemetry["dropped_unknown_rule_count"],
        "dropped_unknown_rule_ids": drop_telemetry["dropped_unknown_rule_ids"],
    }

    # Metrics 埋点: worker.completed (含 telemetry 关键字段)
    try:
        _record_event(
            "worker.completed",
            workspace=_ws_for_metrics,
            duration_ms=telemetry["duration_ms"],
            model=model,
            cost_usd=cost_usd,
            status="success",
            details={
                "dim_key": dim_key,
                "items_count": len(items),
                "tokens_in": telemetry["tokens_in"],
                "tokens_out": telemetry["tokens_out"],
                "empty_retry_used": empty_retry_used,
                "degraded": is_degraded,
                "turns_used": current_turn,
                "truncated": telemetry.get("truncated", False),
            },
        )
    except Exception:
        pass

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


async def _run_worker_async(
    client,
    dim_key,
    prd_content,
    wiki_pages,
    model_tiers,
    rule_perf_history=None,
    wiki_path=None,
    diff_context=None,
    on_tool_call=None,
    *,
    retry_on_timeout: bool = True,
    recovery_mode: bool = False,
) -> WorkerResult:
    """异步包装：在线程池中执行 _worker_core，带超时保护"""
    from agent_config import WORKER_TIMEOUT
    from agent_config import MAX_WIKI_CHARS
    from review.adaptive import choose_worker_model_override, wiki_budget_for_dim

    loop = asyncio.get_running_loop()
    wiki_budget_chars = wiki_budget_for_dim(
        dim_key,
        MAX_WIKI_CHARS,
        prd_content=prd_content,
        wiki_pages=wiki_pages,
        recovery_mode=recovery_mode,
    )
    from review.prd_context import (
        build_prd_context_packet,
        prd_context_packet_budget,
        should_use_prd_context_packet,
    )
    prd_context_packet = None
    if should_use_prd_context_packet(
        prd_content,
        wiki_pages,
        recovery_mode=recovery_mode,
    ):
        prd_context_packet = build_prd_context_packet(
            prd_content,
            dim_key=dim_key,
            max_chars=prd_context_packet_budget(recovery_mode=recovery_mode),
        )
    route_model_override = choose_worker_model_override(
        dim_key,
        prd_content=prd_content,
        wiki_pages=wiki_pages,
        recovery_mode=recovery_mode,
    )
    timeout_s = WORKER_TIMEOUT
    if recovery_mode:
        timeout_s = max(WORKER_TIMEOUT, float(os.environ.get("PECKER_WORKER_RECOVERY_TIMEOUT", "120")))
    try:
        return await asyncio.wait_for(
            loop.run_in_executor(
                None,
                lambda: _worker_core(
                    client,
                    dim_key,
                    prd_content,
                    wiki_pages,
                    model_tiers,
                    rule_perf_history,
                    wiki_path,
                    diff_context,
                    on_tool_call,
                    wiki_budget_chars=wiki_budget_chars,
                    route_model_override=route_model_override,
                    recovery_mode=recovery_mode,
                    prd_context_packet=prd_context_packet,
                ),
            ),
            timeout=timeout_s,
        )
    except asyncio.TimeoutError:
        if retry_on_timeout and not recovery_mode and _timeout_recovery_enabled():
            first_error = f"Worker 超时({WORKER_TIMEOUT}s)"
            log.warning(f"[{_cn_label(dim_key)}] {first_error}, recovery retry")
            recovered = await _run_worker_async(
                client,
                dim_key,
                prd_content,
                wiki_pages,
                model_tiers,
                rule_perf_history=rule_perf_history,
                wiki_path=wiki_path,
                diff_context=diff_context,
                on_tool_call=on_tool_call,
                retry_on_timeout=False,
                recovery_mode=True,
            )
            if not recovered.get("error"):
                recovery = dict(recovered.get("recovery") or {})
                recovery.update({
                    "attempts": 2,
                    "first_error": first_error,
                    "model_override": "gpt55",
                    "wiki_budget_chars": wiki_budget_chars,
                })
                recovered["recovery"] = recovery
                recovered["status"] = "recovered"
                telemetry = recovered.setdefault("telemetry", {})
                telemetry["recovery"] = recovery
                return recovered
            recovered["recovery"] = {
                "attempts": 2,
                "first_error": first_error,
                "recovery_error": recovered.get("error"),
            }
            return recovered
        # 超时 Worker 不抛出,返回错误结构,让 gather 正常汇总其他 Worker 结果
        dim_name = get_review_dimensions().get(dim_key, {}).get("name", dim_key)
        log.warning(f"[{_cn_label(dim_key)}] Worker 超时({WORKER_TIMEOUT}s),跳过")
        try:
            _record_event(
                "worker.failed",
                workspace=os.path.dirname(wiki_path) if wiki_path else None,
                duration_ms=int(WORKER_TIMEOUT * 1000),
                status="timeout",
                details={"dim_key": dim_key, "error": f"Worker 超时({WORKER_TIMEOUT}s)"},
            )
        except Exception:
            pass
        return {
            "dimension": dim_key,
            "dimension_name": dim_name,
            "error": f"Worker 超时({WORKER_TIMEOUT}s)",
            "items": [],
            "usage": {"input_tokens": 0, "output_tokens": 0},
            "status": "timeout",
            "recovery": {"attempts": 1},
        }


def _run_worker_sync(client, dim_key, prd_content, wiki_pages, model_tiers, rule_perf_history=None, wiki_path=None, diff_context=None, on_tool_call=None) -> WorkerResult:
    """同步包装：直接调用 _worker_core"""
    return _worker_core(client, dim_key, prd_content, wiki_pages, model_tiers, rule_perf_history, wiki_path, diff_context, on_tool_call)
