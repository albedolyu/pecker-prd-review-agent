"""
并行评审模块 -- 啄木鸟 Phase 2 的四维度并行评审 Workers
功能：
  1. 四个评审维度并行调用 Messages API
  2. 结构化输出 tool schema（submit_review_items）
  3. 依据验证（Side Query）
  4. 合并去重
"""

import asyncio
import json
import os
import re
import time
import glob as glob_module
from difflib import SequenceMatcher

from logger import get_logger

log = get_logger("parallel")

# 信鸽反馈历史文件路径（延迟解析，避免在 import 时读不到 WORKSPACE 环境变量）
def _get_rule_perf_history_path():
    workspace = os.environ.get("WORKSPACE", os.path.join(os.path.dirname(__file__), "workspace"))
    return os.path.join(workspace, "output", "rule_performance_history.json")

# ============================================================
# 评审维度定义
# ============================================================

REVIEW_DIMENSIONS = {
    "structure": {
        "name": "结构层",
        "codename": "织布鸟",
        "rules": """BMAD V-02~V-06，逐条检查：

V-02 格式规范性：验证 PRD 是否遵循标准模板（标准/变体/Legacy）。
V-03 信息密度：检测对话式填充、冗余表达、重复短语。反模式：
  - "The system will allow users to..." → 直接写功能
  - "Due to the fact that" → "because"
  严重度：≥10 处 = must
V-04 Brief 覆盖率：检查 Brief → PRD 的映射完整性，识别未覆盖的 Brief 要求。
V-05 信息完整性：PRD 中引用的所有信息（字段、规则、布局）能在文档内自洽，不依赖外部未注明的文档。
V-06 可追溯链完整性：验证 愿景 → FR → 用户故事 的链路完整，不能断链。""",
        "checklist": [
            {"rule_id": "V-02", "name": "格式规范性"},
            {"rule_id": "V-03", "name": "信息密度"},
            {"rule_id": "V-04", "name": "Brief 覆盖率"},
            {"rule_id": "V-05", "name": "信息完整性"},
            {"rule_id": "V-06", "name": "可追溯链完整性"},
        ],
        "model": "sonnet",
    },
    "quality": {
        "name": "质量层",
        "codename": "猫头鹰",
        "rules": """BMAD V-07~V-12，逐条检查：

V-07 逻辑一致性：检查 PRD 内部各章节的描述是否自洽，排序规则/筛选规则/字段映射等不能互相矛盾。
V-08 实现泄漏检测：FR 不应含技术实现细节（如具体 API、框架名、SQL 语句），除非在技术约定节中。
V-09 SMART 验证：成功标准须满足 SMART 原则 — Specific（具体明确）、Measurable（可量化）、Attainable（可实现）、Relevant（与目标相关）、Traceable（可追踪）。
V-10 领域合规性：检查 PRD 是否符合业务领域的法规和合规要求。
V-11 整体质量评估：综合评价 PRD 的完整性、一致性和可操作性。
V-12 完整性评估：检查是否有遗漏的核心功能模块、边界条件、异常处理。""",
        "checklist": [
            {"rule_id": "V-07", "name": "逻辑一致性"},
            {"rule_id": "V-08", "name": "实现泄漏检测"},
            {"rule_id": "V-09", "name": "SMART 验证"},
            {"rule_id": "V-10", "name": "领域合规性"},
            {"rule_id": "V-11", "name": "整体质量评估"},
            {"rule_id": "V-12", "name": "完整性评估"},
        ],
        "model": "sonnet",
    },
    "ai_coding": {
        "name": "AI Coding 友好度",
        "codename": "渡鸦",
        "rules": """RC-004~RC-008, RC-013~RC-015，逐条检查：

RC-004 技术约定节存在（must）：PRD 必须包含技术约定节（框架/鉴权方式/基础路径），不能依赖外部文档独立支撑开发。
RC-005 四态 UI 规范已定义（must）：PRD 必须定义加载中/请求失败/筛选无结果/空数据四种 UI 状态的文案与样式。
RC-006 图片路径使用相对路径（should）：PRD 中引用的图片应使用相对路径，避免绝对路径导致协作问题。
RC-007 复杂联动逻辑有伪代码（should）：复杂联动逻辑、非结构化文本处理等必须有伪代码或流程描述。
RC-008 筛选追溯完整（must）：筛选/查询逻辑须从用户操作追溯到 WHERE 条件，中间无断点；非常规逻辑（继承/降级/空值）需有具体示例覆盖。
RC-013 伪代码字段可追溯（must）：伪代码中每个字段均可在 DDL 中找到；跨表字段标注 JOIN 来源。
RC-014 筛选逻辑追溯到 WHERE（must）：筛选/查询逻辑从用户操作追溯到 WHERE 条件，中间无断点。
RC-015 非常规逻辑有示例（should）：非常规逻辑（继承/降级/空值）须有具体示例覆盖。""",
        "checklist": [
            {"rule_id": "RC-004", "name": "技术约定节存在"},
            {"rule_id": "RC-005", "name": "四态 UI 规范已定义"},
            {"rule_id": "RC-006", "name": "图片路径使用相对路径"},
            {"rule_id": "RC-007", "name": "复杂联动逻辑有伪代码"},
            {"rule_id": "RC-008", "name": "筛选追溯完整"},
            {"rule_id": "RC-013", "name": "伪代码字段可追溯"},
            {"rule_id": "RC-014", "name": "筛选逻辑追溯到 WHERE"},
            {"rule_id": "RC-015", "name": "非常规逻辑有示例"},
        ],
        "model": "opus",  # 需要深度推理
    },
    "data_quality": {
        "name": "数据质量",
        "codename": "鸬鹚",
        "rules": """RC-009~RC-010，逐条检查：

RC-009 字段映射一致性（must）：字段映射表中字段名与物理表 DDL 一致；跨表字段须标注 JOIN 来源和优先级。
RC-010 数值类字段标注来源（must）：数值类字段（分页数/导出上限/阈值）须标注来源或标注 TBD；跨表字段须说明空值降级处理。""",
        "checklist": [
            {"rule_id": "RC-009", "name": "字段映射一致性"},
            {"rule_id": "RC-010", "name": "数值类字段标注来源"},
        ],
        "model": "sonnet",  # haiku 对复杂字段映射判定不够稳定，升级到 sonnet
    },
}

# ============================================================
# 结构化输出 Tool Schema
# ============================================================

SUBMIT_REVIEW_ITEMS_TOOL = {
    "name": "submit_review_items",
    "description": "提交评审中发现的问题项。逐条检查 checklist 后，仅提交 fail 的规则。",
    "input_schema": {
        "type": "object",
        "properties": {
            "dimension": {"type": "string", "description": "评审维度"},
            "items": {
                "type": "array",
                "description": "仅提交发现问题的规则项。同一规则在多处违反时可提交多条（rule_id 相同但 location 不同）。如果全部规则都通过则提交空数组。",
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
        },
        "required": ["dimension", "items"],
    },
}

# ============================================================
# Worker System Prompt 模板
# ============================================================

_WORKER_SYSTEM_TEMPLATE = """你是「{codename}」，啄木鸟评审团的 {dimension_name} 评审员。

## 你的逐条打分清单
{dimension_rules}

## 必须打分的规则列表
{checklist_list}

## 评审要求
1. 仔细阅读 PRD 内容和相关知识库页面
2. 仅关注你负责的评审维度，不要越界评审其他维度
3. 逐条对照上述检查清单，每条规则都要检查
4. 同一条规则如果在 PRD 的多个位置都有违反，每个位置单独提交一条改进项（rule_id 相同但 location 不同）
5. 每条改进项必须有明确依据（A=内部知识, B=评审规则, C=外部参考）
6. 找不到依据的改动不得提出
7. 评审完成后，使用 submit_review_items 工具提交所有发现的问题项（如果全部通过则提交空数组）

## 依据分类
- A（内部知识）：引用 wiki 中的业务知识页面，标注页面名
- B（评审规则）：引用具体规则编号（如 RC-005、V-07），并引用规则原文
- C（外部参考）：竞品设计、行业惯例等，必须标记为「待确定⚠️」

## 严重度
- must：必须修改，不改会导致 PRD 无法正确指导开发
- should：建议修改，改了会提升 PRD 质量
"""


def _build_worker_system(dim_key):
    """为某个评审维度构建 system prompt，并动态注入信鸽反馈中的高发问题"""
    dim = REVIEW_DIMENSIONS[dim_key]

    # 构建 checklist 列表文本，明确告诉模型必须打分哪些规则
    checklist_lines = []
    for rule in dim["checklist"]:
        checklist_lines.append(f"- {rule['rule_id']}（{rule['name']}）")
    checklist_text = "\n".join(checklist_lines)

    base_prompt = _WORKER_SYSTEM_TEMPLATE.format(
        codename=dim["codename"],
        dimension_name=dim["name"],
        dimension_rules=dim["rules"],
        checklist_list=checklist_text,
    )

    # --- 动态注入信鸽反馈 ---
    feedback_section = _build_feedback_section(dim_key)
    if feedback_section:
        base_prompt += "\n" + feedback_section

    return base_prompt


def _build_feedback_section(dim_key):
    """从 rule_performance_history.json 中筛选当前维度的高发问题规则，生成提示段"""
    # 1. 读取历史文件
    try:
        with open(_get_rule_perf_history_path(), "r", encoding="utf-8") as f:
            history = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return ""

    if not isinstance(history, dict):
        return ""

    # 2. 提取当前维度涉及的规则编号
    dim_rules_text = REVIEW_DIMENSIONS[dim_key]["rules"]
    dim_rule_ids = set(re.findall(r"(?:RC-\d+|V-\d+)", dim_rules_text))
    if not dim_rule_ids:
        return ""

    # 3. 筛选异常规则：rejection_rate > 0.3 或 missed > 2
    flagged = []
    for rule_id, stats in history.items():
        if not isinstance(stats, dict):
            continue
        # 规则编号归一化匹配（history 中可能是 "RC-005" 或 "V-07"）
        canonical = rule_id.strip()
        if canonical not in dim_rule_ids:
            continue

        rejection_rate = stats.get("rejection_rate", 0)
        missed = stats.get("stats", {}).get("missed", 0)
        if rejection_rate > 0.3 or missed > 2:
            flagged.append({
                "rule_id": canonical,
                "rejection_rate": rejection_rate,
                "missed": missed,
                "name": stats.get("name", ""),
                "recent_total": stats.get("stats", {}).get("total", 0),
            })

    if not flagged:
        return ""

    # 4. 按 rejection_rate + missed 综合排序，取前 5 条
    flagged.sort(key=lambda r: (r["missed"], r["rejection_rate"]), reverse=True)
    flagged = flagged[:5]

    # 5. 生成提示文本
    lines = ["## 近期反馈提示", "以下规则在最近的评审中表现异常，请加强审核："]
    for r in flagged:
        parts = []
        if r["name"]:
            label = f"{r['rule_id']}（{r['name']}）"
        else:
            label = r["rule_id"]

        if r["missed"] > 2:
            parts.append(f"漏报率高，近 {r.get('recent_total', '?')} 次评审中 {r['missed']} 次未检出")
        if r["rejection_rate"] > 0.3:
            pct = int(r["rejection_rate"] * 100)
            parts.append(f"驳回率 {pct}%，建议仅在有充分依据时提出")

        lines.append(f"- {label}：{'；'.join(parts)}")

    return "\n".join(lines) + "\n"


def _build_worker_messages(prd_content, wiki_pages):
    """构建 worker 的 user messages，包含 PRD 和知识库内容"""
    parts = [f"## 待评审 PRD\n\n{prd_content}"]
    if wiki_pages:
        parts.append("## 相关知识库页面\n")
        for title, content in wiki_pages.items():
            parts.append(f"### {title}\n{content}\n")
    parts.append("请评审以上 PRD，逐条对照你的检查清单，然后调用 submit_review_items 工具提交发现的所有改进项。每条改进项必须标注 rule_id。")
    return [{"role": "user", "content": "\n\n".join(parts)}]


# ============================================================
# 单个 Worker 调用
# ============================================================

def _extract_items_from_response(response):
    """从 Messages API 响应中提取 submit_review_items 的 tool_use 结果"""
    for block in response.content:
        if block.type == "tool_use" and block.name == "submit_review_items":
            items = block.input.get("items", [])
            for i, item in enumerate(items, 1):
                if "id" not in item:
                    item["id"] = f"R-{i:03d}"
            return items
    return []


def _has_tool_use(response):
    """检查响应中是否包含 tool_use block"""
    return any(block.type == "tool_use" for block in response.content)


def _extract_text(response):
    """从响应中提取纯文本"""
    return "\n".join(block.text for block in response.content if block.type == "text")


def _parse_items_from_text(text):
    """兜底：从纯文本中提取 JSON 格式的改进项（模型没调 tool 时）"""
    import re as _re
    # 尝试提取 JSON 数组
    m = _re.search(r'\[[\s\S]*?\]', text)
    if m:
        try:
            items = json.loads(m.group())
            if isinstance(items, list) and items:
                for i, item in enumerate(items, 1):
                    if isinstance(item, dict) and "id" not in item:
                        item["id"] = f"R-{i:03d}"
                return items
        except (json.JSONDecodeError, TypeError):
            pass
    return []


async def _run_worker_async(client, dim_key, prd_content, wiki_pages, model_tiers):
    """异步执行单个评审维度的 worker，含 tool 调用检测和重试"""
    dim = REVIEW_DIMENSIONS[dim_key]
    model = model_tiers.get(dim["model"], model_tiers["sonnet"])
    system = _build_worker_system(dim_key)
    messages = _build_worker_messages(prd_content, wiki_pages)

    def _call(msgs):
        return client.create(
            model=model,
            max_tokens=4096,
            system=system,
            messages=msgs,
            tools=[SUBMIT_REVIEW_ITEMS_TOOL],
            tool_choice={"type": "any"},
        )

    loop = asyncio.get_running_loop()

    # 第一次调用
    try:
        response = await loop.run_in_executor(None, lambda: _call(messages))
    except Exception as e:
        log.warning(f"[{dim['codename']}] API 异常，3 秒后重试: {str(e)[:60]}")
        await asyncio.sleep(3)
        response = await loop.run_in_executor(None, lambda: _call(messages))

    items = _extract_items_from_response(response)

    # Tool 调用检测：模型返回了纯文本但没调 tool，用 follow-up 催促
    if not _has_tool_use(response):
        log.warning(f"[{dim['codename']}] 未调用 tool，催促重试")
        text = _extract_text(response)
        # 构建 follow-up 对话，把模型的文本回复接上，催促它调 tool
        followup_msgs = messages + [
            {"role": "assistant", "content": text},
            {"role": "user", "content": "请使用 submit_review_items 工具提交你的评审结果。"},
        ]
        await asyncio.sleep(2)
        try:
            response2 = await loop.run_in_executor(None, lambda: _call(followup_msgs))
            items = _extract_items_from_response(response2)
            if _has_tool_use(response2):
                response = response2  # 更新 usage 统计
        except Exception:
            pass

        # 兜底：从文本中解析 JSON
        if not items and text:
            items = _parse_items_from_text(text)
            if items:
                log.info(f"[{dim['codename']}] 从文本中解析出 {len(items)} 条改进项")

    for item in items:
        item["dimension"] = dim["name"]
    return {
        "dimension": dim_key,
        "dimension_name": dim["name"],
        "model": model,
        "items": items,
        "usage": {
            "input_tokens": response.usage["input_tokens"],
            "output_tokens": response.usage["output_tokens"],
        },
    }


def _run_worker_sync(client, dim_key, prd_content, wiki_pages, model_tiers):
    """同步执行单个评审维度的 worker，含 tool 调用检测和重试"""
    dim = REVIEW_DIMENSIONS[dim_key]
    model = model_tiers.get(dim["model"], model_tiers["sonnet"])
    system = _build_worker_system(dim_key)
    messages = _build_worker_messages(prd_content, wiki_pages)

    def _call(msgs):
        return client.create(
            model=model,
            max_tokens=4096,
            system=system,
            messages=msgs,
            tools=[SUBMIT_REVIEW_ITEMS_TOOL],
            tool_choice={"type": "any"},
        )

    try:
        response = _call(messages)
    except Exception as e:
        log.warning(f"[{dim['codename']}] API 异常，3 秒后重试: {str(e)[:60]}")
        time.sleep(3)
        response = _call(messages)

    items = _extract_items_from_response(response)

    # Tool 调用检测 + 催促重试 + 文本兜底
    if not _has_tool_use(response):
        log.warning(f"[{dim['codename']}] 未调用 tool，催促重试")
        text = _extract_text(response)
        followup_msgs = messages + [
            {"role": "assistant", "content": text},
            {"role": "user", "content": "请使用 submit_review_items 工具提交你的评审结果。"},
        ]
        time.sleep(2)
        try:
            response2 = _call(followup_msgs)
            items = _extract_items_from_response(response2)
            if _has_tool_use(response2):
                response = response2
        except Exception:
            pass

        if not items and text:
            items = _parse_items_from_text(text)
            if items:
                log.info(f"[{dim['codename']}] 从文本中解析出 {len(items)} 条改进项")

    for item in items:
        item["dimension"] = dim["name"]
    return {
        "dimension": dim_key,
        "dimension_name": dim["name"],
        "model": model,
        "items": items,
        "usage": {
            "input_tokens": response.usage["input_tokens"],
            "output_tokens": response.usage["output_tokens"],
        },
    }


# ============================================================
# 并行评审主函数
# ============================================================

async def _single_round_async(client, prd_content, wiki_pages, model_tiers):
    """单轮并行评审（内部函数），返回 workers, merged_items, usage"""
    tasks = [
        _run_worker_async(client, dim_key, prd_content, wiki_pages, model_tiers)
        for dim_key in REVIEW_DIMENSIONS
    ]

    results = await asyncio.gather(*tasks, return_exceptions=True)

    workers = []
    all_items = []
    total_input = 0
    total_output = 0

    for dim_key, result in zip(REVIEW_DIMENSIONS, results):
        if isinstance(result, Exception):
            workers.append({
                "dimension": dim_key,
                "dimension_name": REVIEW_DIMENSIONS[dim_key]["name"],
                "error": str(result),
                "items": [],
            })
        else:
            workers.append(result)
            all_items.extend(result["items"])
            total_input += result["usage"]["input_tokens"]
            total_output += result["usage"]["output_tokens"]

    merged = merge_and_deduplicate(all_items)
    return workers, merged, total_input, total_output


async def parallel_review(client, prd_content, wiki_pages, model_tiers, voting_rounds=1):
    """
    并行执行 4 个评审维度的 worker，合并结果
    - client: anthropic.Anthropic 实例
    - prd_content: PRD 全文字符串
    - wiki_pages: dict {页面标题: 页面内容}，可为空 dict
    - model_tiers: {"opus": "claude-opus-4-6", "sonnet": "claude-sonnet-4-6", "haiku": "claude-haiku-4-5"}
    - voting_rounds: 评审轮次，1=单次（默认），>=2 时启用多数投票
    返回: {"workers": [...], "merged_items": [...], "total_usage": {...}}
    """
    if voting_rounds <= 1:
        # 单轮评审，保持原有行为
        workers, merged, total_input, total_output = await _single_round_async(
            client, prd_content, wiki_pages, model_tiers
        )
        return {
            "workers": workers,
            "merged_items": merged,
            "total_usage": {
                "input_tokens": total_input,
                "output_tokens": total_output,
            },
        }

    # 多轮评审 + 多数投票
    all_rounds_merged = []  # 每轮的 merged_items
    last_workers = []
    total_input = 0
    total_output = 0

    for round_idx in range(voting_rounds):
        if round_idx > 0:
            log.info(f"[majority_vote] 第 {round_idx + 1}/{voting_rounds} 轮评审，等待 5 秒...")
            await asyncio.sleep(5)

        log.info(f"[majority_vote] 开始第 {round_idx + 1}/{voting_rounds} 轮评审")
        workers, merged, inp, out = await _single_round_async(
            client, prd_content, wiki_pages, model_tiers
        )
        all_rounds_merged.append(merged)
        last_workers = workers
        total_input += inp
        total_output += out
        log.info(f"[majority_vote] 第 {round_idx + 1} 轮完成，发现 {len(merged)} 条改进项")

    # 多数投票筛选
    voted_items = majority_vote(all_rounds_merged, min_votes=2)
    log.info(f"[majority_vote] 投票完成：{sum(len(m) for m in all_rounds_merged)} 条 → {len(voted_items)} 条")

    return {
        "workers": last_workers,
        "merged_items": voted_items,
        "total_usage": {
            "input_tokens": total_input,
            "output_tokens": total_output,
        },
    }


def _single_round_sync(client, prd_content, wiki_pages, model_tiers):
    """单轮顺序评审（内部函数），返回 workers, merged_items, usage"""
    workers = []
    all_items = []
    total_input = 0
    total_output = 0

    for dim_key in REVIEW_DIMENSIONS:
        try:
            result = _run_worker_sync(client, dim_key, prd_content, wiki_pages, model_tiers)
            workers.append(result)
            all_items.extend(result["items"])
            total_input += result["usage"]["input_tokens"]
            total_output += result["usage"]["output_tokens"]
        except Exception as e:
            workers.append({
                "dimension": dim_key,
                "dimension_name": REVIEW_DIMENSIONS[dim_key]["name"],
                "error": str(e),
                "items": [],
            })

    merged = merge_and_deduplicate(all_items)
    return workers, merged, total_input, total_output


def parallel_review_sync(client, prd_content, wiki_pages, model_tiers, voting_rounds=1):
    """
    同步版本：顺序执行 4 个 worker（给不方便用 async 的场景）
    接口和返回值与 parallel_review 一致
    - voting_rounds: 评审轮次，1=单次（默认），>=2 时启用多数投票
    """
    if voting_rounds <= 1:
        workers, merged, total_input, total_output = _single_round_sync(
            client, prd_content, wiki_pages, model_tiers
        )
        return {
            "workers": workers,
            "merged_items": merged,
            "total_usage": {
                "input_tokens": total_input,
                "output_tokens": total_output,
            },
        }

    # 多轮评审 + 多数投票
    all_rounds_merged = []
    last_workers = []
    total_input = 0
    total_output = 0

    for round_idx in range(voting_rounds):
        if round_idx > 0:
            log.info(f"[majority_vote] 第 {round_idx + 1}/{voting_rounds} 轮评审，等待 5 秒...")
            time.sleep(5)

        log.info(f"[majority_vote] 开始第 {round_idx + 1}/{voting_rounds} 轮评审")
        workers, merged, inp, out = _single_round_sync(
            client, prd_content, wiki_pages, model_tiers
        )
        all_rounds_merged.append(merged)
        last_workers = workers
        total_input += inp
        total_output += out
        log.info(f"[majority_vote] 第 {round_idx + 1} 轮完成，发现 {len(merged)} 条改进项")

    voted_items = majority_vote(all_rounds_merged, min_votes=2)
    log.info(f"[majority_vote] 投票完成：{sum(len(m) for m in all_rounds_merged)} 条 → {len(voted_items)} 条")

    return {
        "workers": last_workers,
        "merged_items": voted_items,
        "total_usage": {
            "input_tokens": total_input,
            "output_tokens": total_output,
        },
    }


# ============================================================
# 依据验证 (Side Query)
# ============================================================

def verify_evidence(items, workspace):
    """
    验证每条改进项的依据是否可回溯
    - items: 改进项列表
    - workspace: 工作目录路径
    返回: 验证后的 items 列表（失败的标记 RETRACTED）
    """
    wiki_dir = os.path.join(workspace, "wiki")
    rules_dir = os.path.join(workspace, "review-rules")

    verified = []
    for item in items:
        ev_type = item.get("evidence_type", "")
        ev_content = item.get("evidence_content", "")
        retract_reason = None

        if ev_type == "A":
            # A 类：检查 wiki/ 中是否存在对应页面
            if not _find_wiki_page(ev_content, wiki_dir):
                retract_reason = f"A 类依据验证失败：wiki 中未找到相关页面「{ev_content}」"

        elif ev_type == "B":
            # B 类：检查规则编号是否在 review-rules/ 中存在
            if not _find_rule_reference(ev_content, rules_dir):
                retract_reason = f"B 类依据验证失败：review-rules 中未找到规则「{ev_content}」"

        elif ev_type == "C":
            # C 类：必须标记"待确定⚠️"
            if "待确定" not in ev_content and "⚠️" not in ev_content:
                # 自动补标，不 retract
                item["evidence_content"] = ev_content + "（待确定⚠️）"

        if retract_reason:
            item["status"] = "RETRACTED"
            item["retract_reason"] = retract_reason
        else:
            item["status"] = "VERIFIED"

        verified.append(item)

    return verified


def _find_wiki_page(evidence_content, wiki_dir):
    """在 wiki 目录中搜索依据提到的页面"""
    if not os.path.isdir(wiki_dir):
        return False

    # 从依据内容中提取 [[页面名]] 格式的引用
    import re
    page_refs = re.findall(r"\[\[(.+?)\]\]", evidence_content)

    if page_refs:
        # 有明确的页面引用，检查文件是否存在
        for ref in page_refs:
            # 尝试精确匹配文件名
            pattern = os.path.join(wiki_dir, f"*{ref}*")
            if glob_module.glob(pattern):
                return True
        return False

    # 没有 [[]] 引用，用关键词模糊搜索
    all_wiki = glob_module.glob(os.path.join(wiki_dir, "*.md"))
    # 提取中文关键词（2~4 字词组）+ 英文关键词（长度 > 2）
    cn_keywords = re.findall(r'[\u4e00-\u9fff]{2,4}', evidence_content)
    en_keywords = [w for w in re.findall(r'[a-zA-Z_-]+', evidence_content) if len(w) > 2]
    keywords = cn_keywords + en_keywords
    for wiki_file in all_wiki:
        basename = os.path.basename(wiki_file)
        for kw in keywords[:5]:  # 最多检查前 5 个关键词
            if kw in basename:
                return True
    return False


def _find_rule_reference(evidence_content, rules_dir):
    """检查规则编号是否在 review-rules 目录中存在"""
    if not os.path.isdir(rules_dir):
        return False

    # 提取规则编号（如 RC-005, V-07, BMAD V-02 等）
    import re
    rule_ids = re.findall(r"(?:RC-\d+|BMAD\s+V-\d+|V-\d+)", evidence_content)
    if not rule_ids:
        # 没有明确规则编号，视为验证失败
        return False

    # 在 review-rules 目录下递归搜索
    all_rules_files = glob_module.glob(os.path.join(rules_dir, "**", "*"), recursive=True)
    for rules_file in all_rules_files:
        if not os.path.isfile(rules_file):
            continue
        try:
            with open(rules_file, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            for rid in rule_ids:
                # 去掉 "BMAD " 前缀做匹配
                clean_rid = rid.replace("BMAD ", "")
                if clean_rid in content:
                    return True
        except OSError:
            continue

    return False


# ============================================================
# 合并与去重
# ============================================================

def majority_vote(all_runs_items, min_votes=2):
    """
    多数投票：多轮评审结果取交集，只保留出现 >= min_votes 次的改进项
    - all_runs_items: list[list[dict]]，每轮评审的合并后改进项列表
    - min_votes: 最少出现次数，默认 2
    - 匹配逻辑：优先用 rule_id 精确匹配；无 rule_id 时降级为 issue 文本相似度 >= 0.6
    - 对于匹配上的 items，保留文本最长的那条（信息最丰富）
    """
    if not all_runs_items:
        return []

    # 把所有轮次的 items 展平，标记来源轮次
    tagged = []
    for run_idx, items_in_run in enumerate(all_runs_items):
        for item in items_in_run:
            tagged.append((run_idx, item))

    # 分组：按 rule_id + location 聚类，无 rule_id 时用 issue 文本相似度
    clusters = []  # 每个 cluster 是 list[(run_idx, item)]

    for run_idx, item in tagged:
        rule_id = item.get("rule_id", "")
        issue_text = item.get("issue", "")
        matched_cluster = None

        for cluster in clusters:
            representative = cluster[0][1]
            rep_rule_id = representative.get("rule_id", "")

            # 优先 rule_id 精确匹配
            if rule_id and rep_rule_id and rule_id == rep_rule_id:
                # rule_id 相同时，还要检查 location 相似（避免同一规则不同位置被错误合并）
                loc_sim = SequenceMatcher(
                    None,
                    item.get("location", ""),
                    representative.get("location", ""),
                ).ratio()
                if loc_sim >= 0.5:
                    matched_cluster = cluster
                    break
            elif not rule_id or not rep_rule_id:
                # 无 rule_id，降级为 issue 文本相似度
                rep_issue = representative.get("issue", "")
                if issue_text and rep_issue:
                    sim = SequenceMatcher(None, issue_text, rep_issue).ratio()
                    if sim >= 0.6:
                        matched_cluster = cluster
                        break

        if matched_cluster is not None:
            matched_cluster.append((run_idx, item))
        else:
            clusters.append([(run_idx, item)])

    # 筛选：只保留出现在 >= min_votes 个不同轮次的 cluster
    result = []
    for cluster in clusters:
        distinct_runs = len(set(run_idx for run_idx, _ in cluster))
        if distinct_runs >= min_votes:
            # 保留文本最长的那条（issue + suggestion 总长度）
            best = max(
                cluster,
                key=lambda t: len(t[1].get("issue", "")) + len(t[1].get("suggestion", "")),
            )
            result.append(best[1])

    # 重新排序和编号
    severity_rank = {"must": 0, "should": 1}
    result.sort(key=lambda x: severity_rank.get(x.get("severity", "should"), 1))
    for i, item in enumerate(result, start=1):
        item["id"] = f"R-{i:03d}"

    return result


def merge_and_deduplicate(items):
    """
    合并多个 worker 的改进项，去重并重新编号
    - 如果两条 item 的 location + issue 相似度 > 80%，保留严重度更高的
    - 重新编号为 R-001, R-002, ...
    - 按严重度排序（must 在前）
    """
    if not items:
        return []

    # 严重度排序权重
    severity_rank = {"must": 0, "should": 1}

    # 按严重度排序（must 优先）
    sorted_items = sorted(items, key=lambda x: severity_rank.get(x.get("severity", "should"), 1))

    # 去重：逐条检查是否与已保留的 item 高度相似
    kept = []
    for item in sorted_items:
        is_dup = False
        item_text = f"{item.get('location', '')} {item.get('issue', '')}"

        for existing in kept:
            existing_text = f"{existing.get('location', '')} {existing.get('issue', '')}"
            similarity = SequenceMatcher(None, item_text, existing_text).ratio()
            if similarity > 0.8:
                is_dup = True
                # 如果当前 item 严重度更高，替换已有的
                if severity_rank.get(item.get("severity"), 1) < severity_rank.get(existing.get("severity"), 1):
                    kept.remove(existing)
                    kept.append(item)
                break

        if not is_dup:
            kept.append(item)

    # 重新排序：must 在前
    kept.sort(key=lambda x: severity_rank.get(x.get("severity", "should"), 1))

    # 重新编号
    for i, item in enumerate(kept, start=1):
        item["id"] = f"R-{i:03d}"

    return kept
