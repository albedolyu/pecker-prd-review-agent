"""
苍鹰（Goshawk）Advisor Agent -- 交叉校验模块
功能：
  1. 用更强模型审核 4 个 worker 的评审结论
  2. 误报检测 / 漏报补充 / 冲突调解
  3. 结果合并回主评审列表
  4. 可独立 CLI 运行
"""

import argparse
import json
import random
import os
import copy
import time as _time

from dotenv import load_dotenv
from agent_config import MODEL_TIERS
from logger import get_logger

log = get_logger("goshawk")

# Metrics 埋点 — 失败 silent skip, 不阻交叉校验主流程
try:
    from review.metrics_store import record_event as _record_event
except Exception:
    def _record_event(*args, **kwargs):  # noqa: ARG001
        return False

# ============================================================
# 苍鹰 ASCII Art
# ============================================================

GOSHAWK_ART = r"""
      _____
     /     \
    | () () |    苍鹰俯瞰全局...
    |   >   |    "我不重新评审，我审核评审。"
     \_____/
      |   |
     /|   |\
    / |   | \
"""

# ============================================================
# System Prompt
# ============================================================

GOSHAWK_SYSTEM_PROMPT = """你是「苍鹰」，啄木鸟评审团的高级顾问。

你的职责不是重新评审 PRD，而是审核其他评审员（织布鸟、猫头鹰、渡鸦、鸬鹚）的评审结论。

你要做三件事：
1. 误报检测：哪些改进项是过度解读？PRD 在其他地方可能已有解释。
2. 漏报补充（最多 2 条）：仅限以下规则列表中有明确编号的规则被全部 Worker 遗漏的情况。每条必须引用具体规则编号（如 RC-005 或 V-07）和 PRD 中的具体位置。不得补充规则列表之外的问题。
   可引用的规则：V-02~V-12, RC-004~RC-015, EV-01 (验收标准), EV-04 (AI eval 集计划)
3. 冲突调解（最多 3 条，**不确定不合并**）：不同评审员对同一处的判断矛盾时，给出你的裁决，必须引用冲突双方的 item_id。

原则：
- 你的审核权重高于单个 worker，但不能推翻有充分依据的结论
- 只在有明确理由时才标记误报
- 补充的漏报必须有规则编号依据，不能编造规则列表之外的问题
- 冲突调解必须说明裁决理由，并引用相关 item_id

冲突调解保守原则 (2026-04-26 sprint Day3 抑制 sampling noise):
- **判定标准**: 两条 item 必须指向**完全相同的 PRD 位置 + 完全相同的具体问题**, 才能合并
- **不合并的情况** (即使你觉得相关):
  * 同一章节但不同子问题 (如 V-05 报"字段名不一致" + V-09 报"数据为空时未定义" — 这是两个独立 facet, 不合)
  * 同一规则号但不同位置 (如两条都是 RC-009, 但分别指向"列表页 DDL"和"详情页 DDL" — 不合)
  * 表面相似但语义不同 (如"按时间排序" vs "按发布日期排序" — 字段不同, 不合)
- **不确定就不报**: 输出 `conflict_resolutions=[]` 比错误合并更好
- **每次最多 3 条**: 超出请只挑最确定的 3 条, 其余留给 PM 自行判断

误报标记的 DAR 原则 (2026-04-26, Diversity-Aware Retention 借鉴 arXiv 2603.20640):
- worker 之间的 disagreement 是**信号不是噪声**, 不要被多数派绑架
- 如果 1 个 worker 标了误报但其他 worker 没标, **仍然 flag** 但 reason 写明"少数派判定 + 等 PM 复核"
- 不要用 "其他 worker 都没说有问题" 作为否定理由, 这等于把投票当真理
- 系统下游 (`_aggregate_advisor_results` retention_kind) 会按 minority/majority/unanimous 分桶,
  让 PM 看到 disagreement, 而不是被合并掩盖
"""

# ============================================================
# Tool Schema -- 让苍鹰结构化输出
# ============================================================

SUBMIT_ADVISOR_REVIEW_TOOL = {
    "name": "submit_advisor_review",
    "description": "提交苍鹰的交叉校验结果，包含误报检测、漏报补充、冲突调解。",
    "input_schema": {
        "type": "object",
        "properties": {
            "flagged_as_false_positive": {
                "type": "array",
                "description": "被标记为误报（过度解读）的改进项",
                "items": {
                    "type": "object",
                    "properties": {
                        "item_id": {"type": "string", "description": "改进项编号，如 R-003"},
                        "reason": {"type": "string", "description": "判断为误报的理由"},
                        "recommendation": {
                            "type": "string",
                            "description": "建议处理方式：降级为 should / 移除",
                        },
                    },
                    "required": ["item_id", "reason", "recommendation"],
                },
            },
            "additional_findings": {
                "type": "array",
                "description": "被所有 Worker 遗漏但有明确规则依据的问题，最多 2 条(硬约束)",
                "maxItems": 2,
                "items": {
                    "type": "object",
                    "properties": {
                        "rule_id": {"type": "string", "description": "规则编号，如 RC-005 或 V-07"},
                        "location": {"type": "string", "description": "PRD 中的位置"},
                        "issue": {"type": "string", "description": "具体问题"},
                        "suggestion": {"type": "string", "description": "改进建议"},
                        "severity": {
                            "type": "string",
                            "enum": ["must", "should"],
                        },
                        "evidence_type": {"type": "string", "description": "依据类型：A/B/C"},
                        "evidence_content": {"type": "string", "description": "依据内容"},
                    },
                    "required": ["rule_id", "location", "issue", "suggestion", "severity", "evidence_type", "evidence_content"],
                },
            },
            "conflict_resolutions": {
                "type": "array",
                "description": "冲突调解结果, 最多 3 条 (硬约束). 不确定的两条 item 不要合并, 留空数组比误合更好",
                "maxItems": 3,
                "items": {
                    "type": "object",
                    "properties": {
                        "items": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "冲突的改进项编号列表",
                        },
                        "resolution": {"type": "string", "description": "裁决结论"},
                        "reason": {"type": "string", "description": "裁决理由"},
                    },
                    "required": ["items", "resolution", "reason"],
                },
            },
            "confidence": {
                "type": "number",
                "description": "苍鹰对自己判断的信心，0-1",
            },
        },
        "required": [
            "flagged_as_false_positive",
            "additional_findings",
            "conflict_resolutions",
            "confidence",
        ],
    },
}

# ============================================================
# 默认模型（向后兼容: 老 caller 仍可读 DEFAULT_MODEL, 新 caller 走 model_router）
# ============================================================

# 历史: Opus CLI 2/3 轮 timeout, Sonnet 稳定 30-60s。质量略降但每次跑完。
# Wave 2: model 选择已迁到 model_router (advisor.goshawk route),
# DEFAULT_MODEL 仅供老 caller 引用 (advisor_review_default 单测 import 它做签名校验) —
# 实际 client.create 已不再读这里, 改走 route_call("advisor.goshawk", ...).
def _resolve_default_model() -> str:
    """从 model_router 取 advisor.goshawk 默认 model 实名 (避免硬编码)."""
    try:
        from model_router import get_model_for_route
        return get_model_for_route("advisor.goshawk")
    except Exception:
        # routes.yaml 未加载 / config 未就绪时的兜底, 与老逻辑等价
        return MODEL_TIERS["sonnet"]


DEFAULT_MODEL = _resolve_default_model()


# ============================================================
# 构建 Anthropic Client (Wave 2 后变 noop, 仅保留避免 break import)
# ============================================================

def _make_client():
    """Wave 2 deprecated: 历史用 .env 创建 API client, 现在 client 由 model_router
    内部按 vendor 单例管理. 保留函数避免 break import; 对外仍返 client 实例供
    sanity_check / 老 fallback 用 (但所有正式 LLM 调用应走 route_call)."""
    from api_adapter import create_client
    return create_client()


# ============================================================
# 核心：Advisor 调用
# ============================================================

def _build_advisor_user_message(prd_content, worker_results, wiki_pages=None):
    """构建给苍鹰的 user message"""
    parts = []

    # PRD 原文
    parts.append(f"## 待审核的 PRD 原文\n\n{prd_content}")

    # 知识库（可选）
    if wiki_pages:
        parts.append("## 相关知识库页面\n")
        for title, content in wiki_pages.items():
            parts.append(f"### {title}\n{content}\n")

    # Worker 评审结果
    parts.append("## 各 Worker 的评审结果\n")
    parts.append("以下是 4 个评审员提交的所有改进项，请逐条审核：\n")

    for item in worker_results:
        item_id = item.get("id", "?")
        dim = item.get("dimension", "未知")
        loc = item.get("location", "")
        issue = item.get("issue", "")
        suggestion = item.get("suggestion", "")
        severity = item.get("severity", "")
        evidence = item.get("evidence_content", "")
        rule_id = item.get("rule_id", "")

        rule_line = f"- 规则编号：{rule_id}\n" if rule_id else ""
        parts.append(
            f"### {item_id}（{dim} | {severity}）\n"
            f"{rule_line}"
            f"- 位置：{loc}\n"
            f"- 问题：{issue}\n"
            f"- 建议：{suggestion}\n"
            f"- 依据：{evidence}\n"
        )

    parts.append(
        "请仔细审核以上所有改进项，完成后使用 submit_advisor_review 工具提交你的审核结果。\n"
        "注意：漏报补充最多 2 条，每条必须引用具体规则编号（V-02~V-12, RC-004~RC-015），不得补充规则列表之外的问题。\n\n"
        "**输出格式硬约束**：你必须且只能输出一个 JSON 对象,严格遵循 submit_advisor_review 的 schema。"
        "不要在 JSON 前后写任何解释文字、markdown code fence 或注释。"
        "确保所有 string 字段使用双引号,数组用 [],对象用 {},不要有 trailing comma。"
    )

    return "\n\n".join(parts)


def advisor_review(client, prd_content, worker_results, wiki_pages=None, model=DEFAULT_MODEL, deadline=None, on_tool_call=None):
    """
    苍鹰交叉校验主函数
    含指数退避重试 + tool_use 检测 + 催促重试 + 文本兜底

    deadline: 可选, time.monotonic() 绝对时间戳. 内部每个 retry 分支前检查剩余时间,
        不够做一次 ~8s 的 API call + sleep 时主动跳过,返回当前最好结果 + 标注
        result["truncated_by_deadline"]=True. 防止外层 wait_for 超时时内层还在 sleep.
    on_tool_call: 可选 callback(trace_dict), 记录 per-tool-call trace.
        kind ∈ {goshawk_initial, goshawk_retry (指数退避), goshawk_prompt_followup
        (催促), goshawk_empty_retry_followup (空提交复检)}.
    """
    use_router = client is None or client.__class__.__name__ == "ClaudeCodeCLIClient"

    print(GOSHAWK_ART)

    # Metrics 埋点: goshawk.started (workspace 来自 env, advisor 上下文 wiki_pages 不带 path)
    _gs_workspace = os.environ.get("WORKSPACE")
    _gs_started_at = _time.time()
    try:
        _record_event(
            "goshawk.started",
            workspace=_gs_workspace,
            model=model,
            details={"n_worker_items": len(worker_results) if worker_results else 0},
        )
    except Exception:
        pass

    user_msg = _build_advisor_user_message(prd_content, worker_results, wiki_pages)
    messages = [{"role": "user", "content": user_msg}]

    import time

    from deadline_coordinator import DeadlineCoordinator
    # 估单次 retry 分支最坏耗时: sleep 2-2.5s + API call 5-30s Opus
    coord = DeadlineCoordinator(deadline=deadline, min_per_retry=8.0)

    # Wave 2: 主审默认走 advisor.goshawk route. _make_client 仍可调,
    # 但显式 mock client (e2e / 单测) 路径继续走 client.create 兼容老 mock.
    from model_router import route_call
    # client=None 是 Web 团队版的路由哨兵: 直接走 model_router, 不再构造个人 Claude/OAT client.
    # 显式 mock client (e2e / 单测) 仍走 client.create 兼容旧测试。

    def _call(msgs, call_kind="goshawk_initial"):
        _t0 = time.time()
        # model 参数可能是完整模型名 ("claude-sonnet-4-6") 或 tier 别名 ("sonnet").
        # router 期待 tier 别名, 完整名走 fallback (不在 model_tiers → 用 route 默认).
        # 这里把已知完整名反查回 tier 别名, 保持 advisor_review_with_resampling
        # 老 model 透传语义.
        tier_override = None
        if model:
            for tier, full in MODEL_TIERS.items():
                if full == model:
                    tier_override = tier
                    break
            if tier_override is None and model in MODEL_TIERS:
                tier_override = model       # 直接传别名的情况
        if use_router:
            resp = route_call(
                "advisor.goshawk",
                system=GOSHAWK_SYSTEM_PROMPT,
                messages=msgs,
                tools=[SUBMIT_ADVISOR_REVIEW_TOOL],
                tool_choice={"type": "any"},
                max_tokens=4096,
                model_override=tier_override,
            )
        else:
            # mock client / 老 caller 路径
            resp = client.create(
                model=model,
                max_tokens=4096,
                system=GOSHAWK_SYSTEM_PROMPT,
                messages=msgs,
                tools=[SUBMIT_ADVISOR_REVIEW_TOOL],
                tool_choice={"type": "any"},
            )
        _t1 = time.time()
        if on_tool_call is not None:
            try:
                usage = resp.usage if hasattr(resp, "usage") else {}
                # goshawk 用的 client 有的返回 dict 有的返回 obj, 做兼容取值
                def _u(k):
                    if hasattr(usage, "get"):
                        return usage.get(k, 0)
                    return getattr(usage, k, 0)
                on_tool_call({
                    "dim_key": "goshawk",
                    "kind": call_kind,
                    "model": model,
                    "duration_ms": int((_t1 - _t0) * 1000),
                    "input_tokens": _u("input_tokens"),
                    "output_tokens": _u("output_tokens"),
                    "cache_read_tokens": _u("cache_read_input_tokens"),
                    "use_compact_tool": False,
                })
            except Exception:
                pass
        return resp

    # 指数退避重试 (API 级异常)
    max_retries = 2
    response = None
    last_exc = None
    for attempt in range(max_retries + 1):
        try:
            response = _call(messages, call_kind=("goshawk_initial" if attempt == 0 else "goshawk_retry"))
            break
        except Exception as e:
            last_exc = e
            if attempt == max_retries:
                raise
            delay = 2 ** (attempt + 1) + random.uniform(0, 1)
            # deadline 感知: 剩余时间不够再做一轮就主动放弃
            if not coord.can_afford_retry():
                log.warning(f"苍鹰剩余 {coord.time_left():.1f}s < 8s, 跳过指数退避")
                raise
            print(f"  终审 API 异常 (第{attempt + 1}次)，{delay:.1f}s 后重试: {str(e)[:60]}")
            time.sleep(delay)

    # Tool 调用检测：没有 tool_use 时催促重试
    result = _extract_advisor_result(response)
    has_tool = any(block.type == "tool_use" for block in response.content)
    empty_retry_used = False

    if not has_tool and coord.can_afford_retry():
        print("  终审未调用 tool，催促重试...")
        text_parts = "\n".join(block.text for block in response.content if block.type == "text")
        followup_msgs = messages + [
            {"role": "assistant", "content": text_parts},
            {"role": "user", "content": "请使用 submit_advisor_review 工具提交你的审核结果。"},
        ]
        time.sleep(2 + random.uniform(0, 0.5))
        try:
            response2 = _call(followup_msgs, call_kind="goshawk_prompt_followup")
            result2 = _extract_advisor_result(response2)
            has_tool2 = any(block.type == "tool_use" for block in response2.content)
            if has_tool2:
                result = result2
                response = response2
                has_tool = True
        except Exception as e:
            log.warning(f"苍鹰催促 retry 失败: {str(e)[:80]}")
    elif _is_empty_advisor_submission(response) and coord.can_afford_retry():
        # 苍鹰调了 tool 但三数组全空 — 同 worker 空提交 bug,给一次复核机会
        # cost: 仅 sonnet 一次额外调用,比 worker 层更值得 (苍鹰本就是关键交叉校验)
        log.warning("苍鹰首轮空提交(无误报/漏报/冲突),re-prompt 复核")
        empty_retry_used = True
        text_parts = "\n".join(
            block.text for block in response.content if block.type == "text"
        )
        followup_msgs = messages + [
            {"role": "assistant",
             "content": text_parts or "(我已审阅,首次提交 0 条 flagged/additional/conflict)"},
            {"role": "user",
             "content": ("你刚才提交的审核结果三个数组全部为空 "
                         "(flagged_as_false_positive/additional_findings/conflict_resolutions)。"
                         "请复核 Workers 的 items 一次:如确实没有误报/漏报/冲突,请在 confidence "
                         "字段写 ≥0.8 的数值作为显式背书;如有遗漏请重新 submit_advisor_review。")},
        ]
        time.sleep(2 + random.uniform(0, 0.5))
        try:
            response2 = _call(followup_msgs, call_kind="goshawk_empty_retry_followup")
            result2 = _extract_advisor_result(response2)
            # 任一数组非空 → 采用 retry 结果;仍全空 → 保留首次 (confidence 可能已被修正)
            if any(result2.get(k) for k in ("flagged_as_false_positive",
                                             "additional_findings",
                                             "conflict_resolutions")):
                result = result2
                response = response2
            elif result2.get("confidence", 0) > result.get("confidence", 0):
                # retry 后 confidence 上调 → 采用新 confidence 作为显式背书信号
                result["confidence"] = result2.get("confidence", 0)
                response = response2
        except Exception as e:
            log.warning(f"苍鹰空提交复核失败: {str(e)[:80]}")

    # 根据真实状态精细化 verdict,而不是一律"REVIEWED"
    has_any_output = any(
        result.get(k) for k in (
            "flagged_as_false_positive", "additional_findings", "conflict_resolutions"
        )
    )
    if not has_tool:
        result["verdict"] = "SILENT"  # tool 始终未被调用 (retry 也失败)
    elif has_any_output:
        result["verdict"] = "REVIEWED"
    else:
        result["verdict"] = "EMPTY_APPROVAL"  # tool 调了,但显式"三无"
    result["model_used"] = model
    result["empty_retry_used"] = empty_retry_used
    # deadline 触发过 retry skip → 上层应知道这是降级终审,不是完整结果
    if coord.was_hit:
        result["truncated_by_deadline"] = True
    # 保存 usage 供成本归因 (CC cost-tracker querySource 模式)
    result["usage"] = {
        "input_tokens": response.usage.get("input_tokens", 0) if hasattr(response.usage, 'get') else getattr(response.usage, 'input_tokens', 0),
        "output_tokens": response.usage.get("output_tokens", 0) if hasattr(response.usage, 'get') else getattr(response.usage, 'output_tokens', 0),
    }

    # Metrics 埋点: goshawk.completed
    try:
        _record_event(
            "goshawk.completed",
            workspace=_gs_workspace,
            duration_ms=int((_time.time() - _gs_started_at) * 1000),
            model=model,
            status="success",
            details={
                "verdict": result.get("verdict"),
                "confidence": result.get("confidence"),
                "false_positive_count": len(result.get("flagged_as_false_positive", []) or []),
                "additional_count": len(result.get("additional_findings", []) or []),
                "conflict_count": len(result.get("conflict_resolutions", []) or []),
                "empty_retry_used": empty_retry_used,
                "truncated_by_deadline": result.get("truncated_by_deadline", False),
            },
        )
    except Exception:
        pass

    return result


async def advisor_review_async(client, prd_content, worker_results, wiki_pages=None, model=DEFAULT_MODEL, on_tool_call=None):
    """苍鹰交叉校验异步版本（在线程池中执行同步逻辑）

    Phase G #9: 加 GOSHAWK_TIMEOUT 保护。Opus via Claude CLI 可能跑 10+ 分钟,
    超时后跳过交叉校验,直接返回一个"苍鹰超时"的空 advisor result,让 pipeline
    继续推进到 Phase 3。用户能看到 Phase 4 报告但没有苍鹰加持(降级)。
    """
    import asyncio
    import time
    from agent_config import GOSHAWK_TIMEOUT
    loop = asyncio.get_running_loop()
    # 内层感知的 deadline: 比外层 wait_for 提前 3s,给内层主动 degrade 留窗口
    deadline = time.monotonic() + max(GOSHAWK_TIMEOUT - 3, GOSHAWK_TIMEOUT * 0.9)
    try:
        return await asyncio.wait_for(
            loop.run_in_executor(
                None,
                lambda: advisor_review(
                    client, prd_content, worker_results, wiki_pages, model,
                    deadline=deadline, on_tool_call=on_tool_call,
                ),
            ),
            timeout=GOSHAWK_TIMEOUT,
        )
    except asyncio.TimeoutError:
        log.warning(f"苍鹰交叉校验超时({GOSHAWK_TIMEOUT}s),跳过终审,直接用 worker 合并结果")
        try:
            _record_event(
                "goshawk.failed",
                workspace=os.environ.get("WORKSPACE"),
                duration_ms=int(GOSHAWK_TIMEOUT * 1000),
                model=model,
                status="timeout",
                details={"error": f"goshawk timeout {GOSHAWK_TIMEOUT}s"},
            )
        except Exception:
            pass
        return {
            "flagged_as_false_positive": [],
            "additional_findings": [],
            "conflict_resolutions": [],
            "confidence": 0.0,
            "verdict": "TIMEOUT",
            "model_used": model,
        }


#: 漏报补充硬上限(schema + parser 双保险,防止模型绕过 schema)
MAX_ADDITIONAL_FINDINGS = 2

#: 冲突调解硬上限 (2026-04-26 sprint Day3 P0-2.5 抑 sampling noise)
#: 实测同 PRD 同 codebase 两轮 merged_to_facet 4→9 浮动 125%, 苍鹰判定本身 sampling-noisy
#: schema maxItems=3 + parser 强截 + prompt "不确定不合并" 三道保险
MAX_CONFLICT_RESOLUTIONS = 3

#: 误报标记占比硬上限 (2026-04-16 harness audit)
#: 原先无约束,苍鹰理论上可以把所有 worker items 全标为误报 (违反"只审不重审"拓扑)
#: 0.3 = 误报最多占 worker items 总数的 30%,超出按 confidence 从低到高截断
MAX_FALSE_POSITIVE_RATIO = 0.3

#: Side Query escalation 单条 item 最大验证次数 (L3 约束)
MAX_ESCALATIONS = 3


def _extract_advisor_result(response):
    """从 Messages API 响应中提取苍鹰的结构化输出"""
    for block in response.content:
        if block.type == "tool_use" and block.name == "submit_advisor_review":
            data = block.input
            additional = data.get("additional_findings", []) or []
            # 兜底截断:即使模型不遵守 schema maxItems,parser 层强制执行硬上限
            if len(additional) > MAX_ADDITIONAL_FINDINGS:
                log.warning(
                    f"苍鹰返回 {len(additional)} 条漏报补充,超出硬上限 {MAX_ADDITIONAL_FINDINGS},截断"
                )
                additional = additional[:MAX_ADDITIONAL_FINDINGS]

            # 2026-04-26 P0-2.5: 冲突调解兜底截断, 同上原理
            conflicts = data.get("conflict_resolutions", []) or []
            if len(conflicts) > MAX_CONFLICT_RESOLUTIONS:
                log.warning(
                    f"苍鹰返回 {len(conflicts)} 条冲突调解,超出硬上限 {MAX_CONFLICT_RESOLUTIONS},截断"
                )
                conflicts = conflicts[:MAX_CONFLICT_RESOLUTIONS]
            return {
                "flagged_as_false_positive": data.get("flagged_as_false_positive", []),
                "additional_findings": additional,
                "conflict_resolutions": conflicts,
                "confidence": data.get("confidence", 0.0),
            }

    # 如果没有 tool_use，返回空结果
    return {
        "flagged_as_false_positive": [],
        "additional_findings": [],
        "conflict_resolutions": [],
        "confidence": 0.0,
    }


def _retention_kind(count, n_samples):
    """按 frequency 给保留分类 (DAR Diversity-Aware Retention 借鉴, 2026-04-26).

    - unanimous: 全部同意 (n=n_samples)
    - majority: ≥ ceil(n/2) 但 < n
    - minority: 1 ≤ count < ceil(n/2) — DAR 关键: 不再过滤, 保留为低置信度信号
    - filtered: count = 0 (从未出现, 不保留)
    """
    from math import ceil
    if count == 0:
        return "filtered"
    if count == n_samples:
        return "unanimous"
    if count >= ceil(n_samples / 2):
        return "majority"
    return "minority"


def _aggregate_advisor_results(results, n_samples):
    """N 个 advisor_review 结果 + 频次聚合, 给每条 finding 加 verdict_distribution.

    Sprint #2 (LLM-as-Verifier 借鉴) + DAR (Diversity-Aware Retention 借鉴, 2026-04-26):
    Anthropic API 不暴露 logprobs (audit feasibility 报告), 用蒙特卡洛重采样近似.

    DAR 核心思想 (arXiv 2603.20640): 多 agent debate 的 disagreement 是信号不是噪声.
    早期版本"多数同意才保留" (ceil(n/2) threshold) 会丢少数派 facet, 印证 sprint memory
    `pecker_template_prd_sampling_noise_2026_04_24` 中 "苍鹰丢 facet" 根因.

    新策略 (DAR retention):
    - flagged_as_false_positive: 出现 ≥ 1 次都保留, 标 retention_kind = unanimous/majority/minority
    - additional_findings: 取第一次有补充的, 不重采避免 N 倍漏报上限 (不变)
    - conflict_resolutions: 出现 ≥ ceil(n/2) 次才保留 (这条**保留多数同意阈值**, 因为 conflict
      合并是有破坏性动作 — sprint memory Day3 实证 4→9 浮动, 不能再放宽)
    - confidence: N 次平均
    - verdict: 多数

    每条保留 finding 加 verdict_distribution: {appearances, frequency, n_samples, retention_kind}
    minority 项前端可显示"低置信度提醒" 让 PM 决定是否采纳.
    """
    from collections import Counter

    if not results:
        return None

    # 聚合 flagged_as_false_positive — DAR: ≥1 都保留
    fp_counter = {}
    for r in results:
        for fp in r.get("flagged_as_false_positive", []) or []:
            iid = fp.get("item_id", "")
            if not iid:
                continue
            if iid not in fp_counter:
                fp_counter[iid] = [0, fp]
            fp_counter[iid][0] += 1

    aggregated_fps = []
    for iid, (count, fp) in fp_counter.items():
        kind = _retention_kind(count, n_samples)
        if kind == "filtered":
            continue
        fp_with_dist = dict(fp)
        fp_with_dist["verdict_distribution"] = {
            "appearances": count,
            "frequency": round(count / len(results), 3),
            "n_samples": n_samples,
            "retention_kind": kind,   # DAR: unanimous / majority / minority
        }
        aggregated_fps.append(fp_with_dist)

    # additional_findings: 取第一次有补充的 (不变)
    aggregated_additional = []
    for r in results:
        adds = r.get("additional_findings", []) or []
        if adds:
            aggregated_additional = adds
            break

    # conflict_resolutions: 保持 ceil(n/2) 多数同意 — conflict 合并破坏性, 不放宽
    from math import ceil
    conflict_threshold = ceil(n_samples / 2)
    conflict_counter = {}
    for r in results:
        for cr in r.get("conflict_resolutions", []) or []:
            items_key = tuple(sorted(cr.get("items", []) or []))
            if not items_key:
                continue
            if items_key not in conflict_counter:
                conflict_counter[items_key] = [0, cr]
            conflict_counter[items_key][0] += 1

    aggregated_conflicts = []
    for items_key, (count, cr) in conflict_counter.items():
        if count < conflict_threshold:
            continue   # conflict 不放宽: 不到多数不合并
        kind = _retention_kind(count, n_samples)
        cr_with_dist = dict(cr)
        cr_with_dist["verdict_distribution"] = {
            "appearances": count,
            "frequency": round(count / len(results), 3),
            "n_samples": n_samples,
            "retention_kind": kind,
        }
        aggregated_conflicts.append(cr_with_dist)

    # 苍鹰 conflict 上限 (P0-2.5 maxItems=3) 仍然适用
    if len(aggregated_conflicts) > MAX_CONFLICT_RESOLUTIONS:
        aggregated_conflicts.sort(key=lambda c: -c["verdict_distribution"]["frequency"])
        aggregated_conflicts = aggregated_conflicts[:MAX_CONFLICT_RESOLUTIONS]

    confidences = [r.get("confidence", 0.0) for r in results]
    avg_conf = sum(confidences) / len(confidences) if confidences else 0.0
    verdict_counts = Counter(r.get("verdict", "REVIEWED") for r in results)

    return {
        "flagged_as_false_positive": aggregated_fps,
        "additional_findings": aggregated_additional,
        "conflict_resolutions": aggregated_conflicts,
        "confidence": round(avg_conf, 3),
        "verdict": verdict_counts.most_common(1)[0][0] if verdict_counts else "REVIEWED",
        "model_used": results[0].get("model_used", ""),
        "n_samples": n_samples,
        "n_samples_succeeded": len(results),
    }


def advisor_review_with_resampling(
    client, prd_content, worker_results, wiki_pages=None, model=DEFAULT_MODEL,
    n_samples=1, deadline=None, on_tool_call=None,
):
    """苍鹰 N 次重采样 + 频次聚合 wrapper (Sprint #2 LLM-as-Verifier).

    n_samples=1 → 等价 advisor_review 老路径, 不引 noise (默认行为, 兼容老 caller)
    n_samples >= 2 → 并行 N 次 advisor_review + 频次聚合, 每条 finding 加 verdict_distribution

    并行策略:
    - 用 ThreadPoolExecutor (CLI subprocess thread-safe)
    - max_workers = min(n_samples, 4) 避免压栈 PECKER_MAX_CONCURRENT
    - 单次失败 skip 不整体阻塞, 全失败 fallback 到 advisor_review 单次

    Args:
        n_samples: 默认 1 (等价老行为). 推荐 4 (audit feasibility 估算). 上限不限,
                   但 8+ 串行 wallclock ~80s 不建议.

    Returns: 与 advisor_review 同 schema, 加 verdict_distribution per finding +
        n_samples / n_samples_succeeded 字段.
    """
    if n_samples <= 1:
        return advisor_review(client, prd_content, worker_results, wiki_pages, model,
                              deadline, on_tool_call)

    import concurrent.futures
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(n_samples, 4)) as pool:
        futures = [
            pool.submit(advisor_review, client, prd_content, worker_results, wiki_pages,
                        model, deadline, on_tool_call)
            for _ in range(n_samples)
        ]
        for f in concurrent.futures.as_completed(futures):
            try:
                results.append(f.result())
            except Exception as e:
                log.warning(f"[goshawk_resample] 1 次采样失败 skip: {e}")

    if not results:
        log.warning(f"[goshawk_resample] 全 {n_samples} 次失败, fallback 到单次 advisor_review")
        return advisor_review(client, prd_content, worker_results, wiki_pages, model,
                              deadline, on_tool_call)

    return _aggregate_advisor_results(results, n_samples)


# ============================================================
# Production default 入口 (修法 C, 2026-04-26)
# ============================================================
#
# 默认 production caller (run_session / api routes) 走 resampling 路径,
# 让 sprint #2 (LLM-as-Verifier 多次重采样) + DAR (Diversity-Aware Retention 少数派
# 保留) 真在线上跑. PM 可通过 env opt-out 紧急回退.
#
#   PECKER_GOSHAWK_RESAMPLE 默认 4   → 4 次采样 + DAR 频次聚合
#   PECKER_GOSHAWK_RESAMPLE = 1      → 等价老 advisor_review (单次, 紧急回退)
#   PECKER_GOSHAWK_RESAMPLE = 0      → 同 1, opt-out 别名
#
# 设计取舍: 默认 4 来自 audit feasibility 报告 (8+ 串行 wallclock ~80s 不划算).
# 改 env 数字仅影响新 session, 已跑的 session jsonl telemetry 字段不变.

DEFAULT_GOSHAWK_N_SAMPLES = 4


def _resolve_n_samples() -> int:
    """读取 PECKER_GOSHAWK_RESAMPLE env, 兜底默认值 + 容忍非法输入."""
    raw = os.getenv("PECKER_GOSHAWK_RESAMPLE", str(DEFAULT_GOSHAWK_N_SAMPLES)).strip()
    if raw in ("", "0"):
        return 1   # 0 / 空 → 单次 (老路径), 兼容 architect 建议的 opt-out 语义
    try:
        n = int(raw)
        return max(1, n)
    except ValueError:
        log.warning(f"[goshawk] PECKER_GOSHAWK_RESAMPLE={raw!r} 不是 int, 用默认 {DEFAULT_GOSHAWK_N_SAMPLES}")
        return DEFAULT_GOSHAWK_N_SAMPLES


def advisor_review_default(client, prd_content, worker_results, wiki_pages=None, model=DEFAULT_MODEL,
                            deadline=None, on_tool_call=None):
    """Production 同步入口 (CLI 用). 默认走 resampling, env 可 opt-out.

    出参 schema 与 advisor_review 完全一致, 多采样时额外携带:
      - n_samples / n_samples_succeeded
      - 每条 finding 的 verdict_distribution (含 retention_kind)
    单次 (n=1) 等价 advisor_review, 不引 sampling noise.
    """
    n_samples = _resolve_n_samples()
    return advisor_review_with_resampling(
        client, prd_content, worker_results, wiki_pages, model,
        n_samples=n_samples, deadline=deadline, on_tool_call=on_tool_call,
    )


async def advisor_review_default_async(client, prd_content, worker_results, wiki_pages=None,
                                        model=DEFAULT_MODEL, on_tool_call=None):
    """Production 异步入口 (Web API 用). 包同步 default 到 thread + 复用
    advisor_review_async 的 GOSHAWK_TIMEOUT 保护.
    """
    import asyncio
    import time
    from agent_config import GOSHAWK_TIMEOUT
    loop = asyncio.get_running_loop()
    deadline = time.monotonic() + max(GOSHAWK_TIMEOUT - 3, GOSHAWK_TIMEOUT * 0.9)
    try:
        return await asyncio.wait_for(
            loop.run_in_executor(
                None,
                lambda: advisor_review_default(
                    client, prd_content, worker_results, wiki_pages, model,
                    deadline=deadline, on_tool_call=on_tool_call,
                ),
            ),
            timeout=GOSHAWK_TIMEOUT,
        )
    except asyncio.TimeoutError:
        log.warning(f"苍鹰交叉校验超时({GOSHAWK_TIMEOUT}s),跳过终审,直接用 worker 合并结果")
        try:
            _record_event(
                "goshawk.failed",
                workspace=os.environ.get("WORKSPACE"),
                duration_ms=int(GOSHAWK_TIMEOUT * 1000),
                model=model,
                status="timeout",
                details={"error": f"goshawk timeout {GOSHAWK_TIMEOUT}s"},
            )
        except Exception:
            pass
        return {
            "flagged_as_false_positive": [],
            "additional_findings": [],
            "conflict_resolutions": [],
            "confidence": 0.0,
            "verdict": "TIMEOUT",
            "model_used": model,
        }


def summarize_resample_telemetry(goshawk_result) -> dict:
    """从 advisor_review_default 返回结果提取 DAR/sprint #2 telemetry.

    用于 caller 把多轮采样的 retention_kind 分布 / n_samples 写到 session jsonl,
    PM 后续可以聚合"unanimous / majority / minority"占比验证 DAR 落地效果.

    单轮 (n_samples=1) 时返回空 dict, 老路径 telemetry 不变. 多轮时返回:
      {
        "n_samples": 4,
        "n_samples_succeeded": 4,
        "retention_kind_dist": {"unanimous": 2, "majority": 1, "minority": 1},
        "minority_kept": 1,
      }
    """
    n_samples = goshawk_result.get("n_samples")
    if not n_samples or n_samples <= 1:
        return {}

    from collections import Counter
    dist = Counter()
    for bucket in ("flagged_as_false_positive", "conflict_resolutions"):
        for f in goshawk_result.get(bucket, []) or []:
            kind = (f.get("verdict_distribution") or {}).get("retention_kind")
            if kind:
                dist[kind] += 1

    return {
        "n_samples": n_samples,
        "n_samples_succeeded": goshawk_result.get("n_samples_succeeded", n_samples),
        "retention_kind_dist": dict(dist),
        "minority_kept": dist.get("minority", 0),
    }


def _is_empty_advisor_submission(response) -> bool:
    """苍鹰调了 submit_advisor_review 但三个数组都空。

    Parallel to worker's _is_empty_tool_submission: 防止"调了 tool 但没说什么"
    的静默失败被误当成"真无问题"。
    """
    for block in response.content:
        if block.type == "tool_use" and block.name == "submit_advisor_review":
            data = block.input
            fps = data.get("flagged_as_false_positive", []) or []
            adds = data.get("additional_findings", []) or []
            confs = data.get("conflict_resolutions", []) or []
            return not (fps or adds or confs)
    return False


# ============================================================
# 结果合并
# ============================================================

def _verify_wiki_evidence(item, wiki_pages):
    """Side Query L1: 校验 A 类 evidence 引用的 wiki 页面标题是否真实存在。

    3 层升级链 (CC escalation 模式):
      L1: wiki 自动验证 — 检查 [[页面名]] 是否在 wiki_pages 中
      L2: 规则兜底 — evidence_type=A 且 wiki 验证失败 → 降级为 C + advisor_note
      L3: MAX_ESCALATIONS=3,单条 item 最多验证 3 次

    Returns: (passed: bool, note: str)
    """
    import re as _re
    ev_type = item.get("evidence_type", "")
    ev_content = item.get("evidence_content", "")

    if ev_type != "A" or not ev_content:
        return True, ""

    # L1: 提取 [[页面名]] 引用
    refs = _re.findall(r"\[\[(.+?)\]\]", ev_content)
    if not refs:
        return True, ""  # 没有标准引用格式,跳过

    wiki_titles = set(wiki_pages.keys()) if wiki_pages else set()
    escalation_count = 0

    for ref in refs:
        if escalation_count >= MAX_ESCALATIONS:
            break
        escalation_count += 1

        # 精确匹配 or 模糊匹配(页面名可能是 "约束-接口命名规范" 而引用写 "接口命名规范")
        # 2026-04-26 P1-C audit fix: 模糊匹配最小长度 4, 避免 "API"/"PRD"/"DDL" 等 3 字短词
        # 误命中所有含此前缀的页面 (引用 [[API_v3_迁移指南]] 不应匹页面 [[API]])
        _MIN_FUZZY_LEN = 4
        found = any(
            ref == title
            or (len(ref) >= _MIN_FUZZY_LEN and (ref in title or title in ref))
            for title in wiki_titles
        )
        if not found:
            # L2: 降级为 C 类 + advisor_note
            item["evidence_type"] = "C"
            note = f"L2 降级: [[{ref}]] 不在 wiki 中,A→C + ⚠️ 待确定"
            if "⚠️ 待确定" not in ev_content:
                item["evidence_content"] = ev_content + " (⚠️ 待确定,wiki 页面不存在)"
            return False, note

    return True, ""


def _build_gate_log(item, advisor_result, fp_map, conflict_map):
    """为单条 item 构建 gate 决策链 (CC decisionReason 模式)

    gates 列表记录每个检查点的 pass/fail + 原因,供前端 Phase 3 悬浮显示。
    """
    gates = []
    item_id = item.get("id", "")

    # Gate 1: schema 校验 — 必须字段是否齐全
    required = ("rule_id", "location", "issue", "suggestion", "severity", "evidence_type")
    missing = [f for f in required if not item.get(f)]
    gates.append({
        "type": "schema",
        "pass": len(missing) == 0,
        "detail": f"缺少字段: {missing}" if missing else None,
    })

    # Gate 2: confidence 校验
    conf = item.get("confidence_score", 1.0)
    gates.append({
        "type": "confidence",
        "pass": conf >= 0.3,
        "score": conf,
    })

    # Gate 3: evidence 校验 — verification_status 如果存在
    v_status = item.get("verification_status", "")
    if v_status:
        gates.append({
            "type": "evidence",
            "pass": v_status != "retracted",
            "reason": item.get("verification_reason", ""),
        })

    # Gate 4: advisor 误报标记
    if item_id in fp_map:
        fp = fp_map[item_id]
        gates.append({
            "type": "advisor_false_positive",
            "pass": False,
            "reason": fp.get("reason", ""),
            "recommendation": fp.get("recommendation", ""),
        })
    else:
        gates.append({
            "type": "advisor_false_positive",
            "pass": True,
        })

    # Gate 5: advisor 冲突
    if item_id in conflict_map:
        res = conflict_map[item_id]
        gates.append({
            "type": "advisor_conflict",
            "pass": True,
            "resolution": res.get("resolution", ""),
        })

    return {"gates": gates}


def _sanity_check_false_positives(fps, items_by_id, client):
    """用 Haiku 做苍鹰误报标记的 sanity check

    对每个被标为误报的 item,问 Haiku:
    "以下评审条目被终审标记为误报,理由是 {reason}。
     原始条目:{item summary}
     你同意这是误报吗?回答 agree 或 disagree + 一句话理由"

    如果 Haiku disagree,恢复 item 的 status(不标为 REMOVED),
    加 advisor_note "苍鹰标误报但 Haiku 不同意,保留待人工确认"

    Returns:
        dict: {"sanity_check_count": int, "sanity_check_disagreed": int}
    """
    if not fps or client is None:
        return {"sanity_check_count": 0, "sanity_check_disagreed": 0}

    # Wave 2: 二次校验默认走 advisor.goshawk.recheck route (默认 haiku).
    # client 是 ClaudeCodeCLIClient 真实例时切到 router; mock client 仍走老路径
    # (兼容现有 sanity_check 测试).
    from model_router import route_call
    use_router_recheck = client.__class__.__name__ == "ClaudeCodeCLIClient"
    haiku_model = MODEL_TIERS.get("haiku", "claude-haiku-4-5")
    check_count = 0
    disagreed_count = 0

    for fp in fps:
        item_id = fp.get("item_id", "")
        reason = fp.get("reason", "")
        item = items_by_id.get(item_id)
        if not item:
            continue

        # 跳过 pinned items(已在 apply_advisor_result 中处理)
        if item.get("pinned"):
            continue

        item_summary = (
            f"[{item.get('rule_id', '')}] {item.get('location', '')} "
            f"| {item.get('severity', '')} | {item.get('issue', '')[:200]}"
        )

        prompt = (
            f"以下评审条目被终审标记为误报,理由是: {reason}\n\n"
            f"原始条目: {item_summary}\n\n"
            f"你同意这是误报吗?回答 agree 或 disagree + 一句话理由。"
        )

        try:
            if use_router_recheck:
                resp = route_call(
                    "advisor.goshawk.recheck",
                    system="",
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=256,
                )
            else:
                resp = client.create(
                    model=haiku_model,
                    max_tokens=256,
                    messages=[{"role": "user", "content": prompt}],
                    timeout=10,
                )
            text = ""
            for block in resp.content:
                if block.type == "text":
                    text += block.text.lower()
            check_count += 1

            if "disagree" in text:
                disagreed_count += 1
                # 恢复 item: 不标为 REMOVED,加备注
                if item.get("status") == "REMOVED_BY_ADVISOR":
                    item["status"] = "RESTORED_BY_SANITY_CHECK"
                item.setdefault("advisor_note", "")
                sanity_note = "苍鹰标误报但 Haiku 不同意,保留待人工确认"
                if item["advisor_note"]:
                    item["advisor_note"] += "; " + sanity_note
                else:
                    item["advisor_note"] = sanity_note
                log.info(f"[sanity_check] {item_id}: Haiku disagree — {text[:100]}")

        except Exception as e:
            # timeout 或其他异常,跳过不阻塞
            log.warning(f"[sanity_check] {item_id}: 跳过 ({str(e)[:60]})")
            continue

    telemetry = {
        "sanity_check_count": check_count,
        "sanity_check_disagreed": disagreed_count,
    }
    if check_count > 0:
        log.info(
            f"[sanity_check] 完成: {check_count} 条检查, "
            f"{disagreed_count} 条 Haiku 不同意"
        )
    return telemetry


def apply_advisor_result(review_items, advisor_result, wiki_pages=None, client=None):
    """
    将苍鹰的审核结果合并回改进项列表
    - 误报：降级 severity 或移除，加 advisor_note + gate_log
    - 漏报：追加到列表末尾，标记 source="苍鹰补充"
    - 冲突：合并冲突项，保留裁决
    - wiki 验证: A 类 evidence 的 wiki 引用存在性检查 (L1-L3)
    返回: 合并后的新列表 (每条 item 含 gate_log 字段)
    """
    items = copy.deepcopy(review_items)
    items_by_id = {item["id"]: item for item in items}

    # 2026-04-16 harness audit 修复: 误报标记硬上限 (拓扑完整性)
    # 苍鹰是 meta-reviewer,"只审不重审"—— 不允许它否定大部分 worker 输出。
    # 超过 MAX_FALSE_POSITIVE_RATIO 的误报 flag 按 item 原始 confidence 从低到高截断
    # (优先保留那些 worker 自己都不太确定的 item 被标误报,符合直觉)。
    import math as _math
    max_fps = max(1, _math.ceil(len(items) * MAX_FALSE_POSITIVE_RATIO))
    fps_raw = advisor_result.get("flagged_as_false_positive", []) or []
    if len(fps_raw) > max_fps:
        # 按被 flag 的 item 的 confidence_score 升序 (低 conf 优先被 flag,因为更可能是错)
        def _fp_sort_key(fp):
            tgt = items_by_id.get(fp.get("item_id", ""))
            return tgt.get("confidence_score", 1.0) if tgt else 1.0
        fps_raw_sorted = sorted(fps_raw, key=_fp_sort_key)
        fps_capped = fps_raw_sorted[:max_fps]
        log.warning(
            f"苍鹰返回 {len(fps_raw)} 条误报标记,超出硬上限 {max_fps} "
            f"(items={len(items)} * ratio={MAX_FALSE_POSITIVE_RATIO}),截断"
        )
        advisor_result = dict(advisor_result)  # 不改原 dict
        advisor_result["flagged_as_false_positive"] = fps_capped

    # 预建 fp / conflict 索引,供 gate_log 查询
    fp_map = {}
    for fp in advisor_result.get("flagged_as_false_positive", []):
        fp_map[fp.get("item_id", "")] = fp
    conflict_map = {}
    for res in advisor_result.get("conflict_resolutions", []):
        for cid in res.get("items", []):
            conflict_map[cid] = res

    # 1. 处理误报
    for fp in advisor_result.get("flagged_as_false_positive", []):
        item_id = fp["item_id"]
        if item_id not in items_by_id:
            continue

        target = items_by_id[item_id]

        # Pattern 23: Pinned Edit State — 用户 pin 的 item 不被苍鹰修改
        if target.get("pinned"):
            target.setdefault("gate_log", [])
            target["gate_log"].append(f"pinned: 跳过苍鹰误报标记 ({fp.get('reason', '')[:60]})")
            continue

        rec = fp.get("recommendation", "")

        if "移除" in rec:
            # 标记为移除（不物理删除，留审计痕迹）
            target["status"] = "REMOVED_BY_ADVISOR"
            target["advisor_note"] = f"终审认为过度解读了。{fp['reason']}"
            print(f'  终审：{item_id} 这条改进项...终审认为过度解读了。')
        else:
            # 降级为 should
            target["severity"] = "should"
            target["advisor_note"] = f"终审建议降级。{fp['reason']}"
            print(f'  终审：{item_id} 降级为 should -- {fp["reason"]}')

    # 2. 处理漏报补充
    # 计算新编号起点
    max_num = 0
    for item in items:
        item_id = item.get("id", "")
        if item_id.startswith("R-"):
            try:
                num = int(item_id.split("-")[1])
                max_num = max(max_num, num)
            except (ValueError, IndexError):
                pass

    # B4: 苍鹰补充项的 confidence 需要衰减(is_supplement=True)
    from review.confidence import compute_confidence
    for i, finding in enumerate(advisor_result.get("additional_findings", [])[:MAX_ADDITIONAL_FINDINGS], start=1):
        new_id = f"R-{max_num + i:03d}"
        evi_type = finding.get("evidence_type", "A")
        meta_confidence = compute_confidence(evi_type, is_supplement=True)  # B4
        new_item = {
            "id": new_id,
            "rule_id": finding.get("rule_id", ""),
            "location": finding.get("location", ""),
            "issue": finding.get("issue", ""),
            "suggestion": finding.get("suggestion", ""),
            "severity": finding.get("severity", "should"),
            "evidence_type": evi_type,
            "evidence_content": finding.get("evidence_content", finding.get("evidence", "")),
            "confidence_score": meta_confidence,  # B4(已有,后端用)
            # ============ Phase G #3: provenance 字段 ============
            # 标记这条是苍鹰补遗,前端 Phase 3 会显示"苍鹰补遗 · 红章"
            "provenance": "meta_added",
            "confidence": meta_confidence,             # 前端用的标准化字段(0..1)
            "cited_by_workers": ["final-reviewer"],     # 只有苍鹰一个人指证
            "dimension": "苍鹰补充",
            "source": "苍鹰补充",
        }
        items.append(new_item)
        print(f'  终审：所有编辑都没看到这个?补充 {new_id} (confidence={meta_confidence}).')

    # 3. 处理冲突调解 — facet 保留模式 (2026-04-24)
    # 老语义: 被合并项 MERGED_BY_ADVISOR 直接从 active_items 过滤,丢失同主因下的具体 facet
    # 新语义: 被合并项 status=MERGED_BY_ADVISOR + severity=could + facet_of=primary_id, 不过滤
    # 动机: 模板型 PRD 上苍鹰过激合并 (一个宏观问题吞 3+ 章节 facet),漏给 PM 同源具体面
    for resolution in advisor_result.get("conflict_resolutions", []):
        conflict_ids = resolution.get("items", [])
        if len(conflict_ids) < 2:
            continue

        # 保留第一个为 primary，其余降为 could 级 facet
        primary_id = conflict_ids[0]
        if primary_id not in items_by_id:
            continue

        primary = items_by_id[primary_id]
        primary["advisor_note"] = (
            f"冲突调解：{resolution['resolution']}（理由：{resolution['reason']}）"
        )

        # 将其余冲突项保留为 could 级 facet (不过滤,链回 primary)
        for cid in conflict_ids[1:]:
            if cid in items_by_id:
                facet = items_by_id[cid]
                facet["status"] = "MERGED_BY_ADVISOR"   # 保留状态名做审计追溯
                facet["severity"] = "could"              # 降级,与 must/should 区分
                facet["facet_of"] = primary_id           # 链回主条,前端可呈现"X 的同源 facet"
                facet["provenance"] = "facet_of_advisor"
                facet["advisor_note"] = (
                    f"作为 {primary_id} 的同源 facet 保留 (位置/依据可能不同)"
                )

    # Side Query L1-L3: wiki 标题验证 (仅在有 wiki_pages 时执行)
    if wiki_pages:
        for item in items:
            passed, note = _verify_wiki_evidence(item, wiki_pages)
            if not passed:
                log.info(f"[goshawk] {item.get('id', '?')} wiki 验证: {note}")
                item.setdefault("advisor_note", "")
                if item["advisor_note"]:
                    item["advisor_note"] += "; " + note
                else:
                    item["advisor_note"] = note

    # Haiku sanity check: 对被标为误报的 item 做二次校验
    # 只在有 false_positive 且 client 可用时触发(大部分评审 0 条 fp,零开销)
    sanity_telemetry = {"sanity_check_count": 0, "sanity_check_disagreed": 0}
    fps_list = advisor_result.get("flagged_as_false_positive", [])
    if fps_list and client is not None:
        sanity_telemetry = _sanity_check_false_positives(fps_list, items_by_id, client)

    # 为每条 item 生成 gate_log (CC decisionReason 模式)
    for item in items:
        item["gate_log"] = _build_gate_log(item, advisor_result, fp_map, conflict_map)

    # 过滤掉被移除的（MERGED_BY_ADVISOR 不再过滤,改为 could 级 facet 保留,见上方 conflict_resolutions 处理）
    # 注意: RESTORED_BY_SANITY_CHECK 的 item 不会被过滤
    active_items = [
        item
        for item in items
        if item.get("status") != "REMOVED_BY_ADVISOR"
    ]

    # 附加 sanity check telemetry 到第一个 active item(供上层消费)
    if active_items and sanity_telemetry["sanity_check_count"] > 0:
        active_items[0].setdefault("_sanity_telemetry", sanity_telemetry)

    return active_items


# ============================================================
# 报告生成
# ============================================================

def format_advisor_report(advisor_result):
    """格式化苍鹰的审核报告（Markdown），附在评审报告末尾"""
    lines = [
        "",
        "---",
        "",
        "## 苍鹰交叉校验报告",
        "",
        f"模型：{advisor_result.get('model_used', 'unknown')}",
        f"判定：{advisor_result.get('verdict', 'REVIEWED')}",
        f"信心度：{advisor_result.get('confidence', 0):.0%}",
        "",
    ]

    # 误报检测
    fps = advisor_result.get("flagged_as_false_positive", [])
    lines.append(f"### 误报检测（{len(fps)} 条）")
    lines.append("")
    if fps:
        for fp in fps:
            lines.append(f"- **{fp['item_id']}**：{fp['reason']}")
            lines.append(f"  - 建议：{fp['recommendation']}")
    else:
        lines.append("无误报。鸟群判断一致。")
    lines.append("")

    # 漏报补充
    findings = advisor_result.get("additional_findings", [])
    lines.append(f"### 漏报补充（{len(findings)} 条）")
    lines.append("")
    if findings:
        for f in findings:
            rule_tag = f"[{f.get('rule_id')}] " if f.get('rule_id') else ""
            lines.append(f"- {rule_tag}**{f.get('location', '')}**（{f.get('severity', 'should')}）：{f.get('issue', '')}")
            lines.append(f"  - 依据：{f.get('evidence_content', f.get('evidence', ''))}")
    else:
        lines.append("无补充。鸟群覆盖全面。")
    lines.append("")

    # 冲突调解
    conflicts = advisor_result.get("conflict_resolutions", [])
    lines.append(f"### 冲突调解（{len(conflicts)} 条）")
    lines.append("")
    if conflicts:
        for c in conflicts:
            ids = ", ".join(c.get("items", []))
            lines.append(f"- **{ids}**：{c['resolution']}")
            lines.append(f"  - 理由：{c['reason']}")
    else:
        lines.append("无冲突。各维度评审员意见统一。")
    lines.append("")

    return "\n".join(lines)


# ============================================================
# CLI 入口
# ============================================================

def _parse_review_items_from_report(report_path):
    """
    从评审报告 Markdown 中解析出改进项列表
    简易解析：找 R-NNN 格式的条目
    """
    import re

    with open(report_path, "r", encoding="utf-8") as f:
        content = f.read()

    items = []
    # 匹配 ### R-001 或 **R-001** 等格式
    pattern = re.compile(
        r"(?:###?\s*)?(?:\*\*)?(?P<id>R-\d{3})(?:\*\*)?"
        r".*?位置[：:]\s*(?P<location>.+?)$"
        r".*?问题[：:]\s*(?P<issue>.+?)$"
        r".*?建议[：:]\s*(?P<suggestion>.+?)$"
        r".*?严重度[：:]\s*(?P<severity>must|should)",
        re.MULTILINE | re.DOTALL,
    )

    for m in pattern.finditer(content):
        items.append({
            "id": m.group("id"),
            "location": m.group("location").strip(),
            "issue": m.group("issue").strip(),
            "suggestion": m.group("suggestion").strip(),
            "severity": m.group("severity").strip(),
            "dimension": "",
            "evidence_type": "",
            "evidence_content": "",
        })

    # 兜底：如果正则没匹配到，用简易方式提取
    if not items:
        for line in content.split("\n"):
            m = re.match(r".*?(R-\d{3}).*", line)
            if m:
                items.append({
                    "id": m.group(1),
                    "location": "",
                    "issue": line.strip(),
                    "suggestion": "",
                    "severity": "should",
                    "dimension": "",
                    "evidence_type": "",
                    "evidence_content": "",
                })

    return items, content


def _resolve_model(model_arg):
    """将 CLI 参数转为完整模型名，统一从 agent_config 取"""
    return MODEL_TIERS.get(model_arg, model_arg)


def main():
    load_dotenv()

    parser = argparse.ArgumentParser(
        description="苍鹰 Advisor -- 啄木鸟评审团的高级顾问，交叉校验 worker 评审结果"
    )
    parser.add_argument("--prd", required=True, help="PRD 文件路径")
    parser.add_argument("--report", required=True, help="评审报告文件路径（含改进项）")
    parser.add_argument(
        "--model",
        default="opus",
        help="模型档位：opus / sonnet / haiku，或完整模型名（默认 opus）",
    )
    parser.add_argument("--wiki", default=None, help="wiki 知识库目录路径（可选）")
    parser.add_argument("--output", default=None, help="输出文件路径（默认打印到终端）")

    args = parser.parse_args()

    # 读 PRD
    with open(args.prd, "r", encoding="utf-8") as f:
        prd_content = f.read()

    # 从报告中解析改进项
    review_items, report_content = _parse_review_items_from_report(args.report)

    if not review_items:
        print("终审：报告中没有找到改进项（R-NNN），无需审核。")
        return

    print(f"终审：发现 {len(review_items)} 条改进项，开始交叉校验...\n")

    # 读知识库（可选）
    wiki_pages = {}
    if args.wiki and os.path.isdir(args.wiki):
        import glob as g

        for wiki_file in g.glob(os.path.join(args.wiki, "*.md")):
            title = os.path.splitext(os.path.basename(wiki_file))[0]
            with open(wiki_file, "r", encoding="utf-8", errors="replace") as f:
                wiki_pages[title] = f.read()

    # 调用苍鹰
    model = _resolve_model(args.model)
    from api_adapter import create_client
    client = create_client()
    result = advisor_review(client, prd_content, review_items, wiki_pages, model)

    # 合并结果(CLI 模式也传 client,启用 sanity check)
    updated_items = apply_advisor_result(review_items, result, client=client)

    # 生成报告
    report = format_advisor_report(result)

    # 输出
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(report_content)
            f.write(report)
        print(f"\n终审：审核报告已写入 {args.output}")
    else:
        print(report)

    # 打印摘要
    fp_count = len(result.get("flagged_as_false_positive", []))
    add_count = len(result.get("additional_findings", []))
    conf_count = len(result.get("conflict_resolutions", []))
    print(
        f"\n终审完毕：误报 {fp_count} 条，补充 {add_count} 条，"
        f"调解 {conf_count} 处冲突，信心度 {result.get('confidence', 0):.0%}"
    )


if __name__ == "__main__":
    main()
