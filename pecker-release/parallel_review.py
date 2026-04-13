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
import glob as glob_module
from difflib import SequenceMatcher

# ============================================================
# 评审维度定义
# ============================================================

REVIEW_DIMENSIONS = {
    "structure": {
        "name": "结构层",
        "codename": "织布鸟",
        "rules": "BMAD V-02~V-06: 格式规范性、信息密度、Brief 覆盖率、成功标准可量化性、可追溯链完整性",
        "model": "sonnet",
    },
    "quality": {
        "name": "质量层",
        "codename": "猫头鹰",
        "rules": "BMAD V-07~V-12: 实现泄漏检测、领域合规性、SMART 验证、整体质量与完整性",
        "model": "sonnet",
    },
    "ai_coding": {
        "name": "AI Coding 友好度",
        "codename": "渡鸦",
        "rules": "RC-004~RC-008, RC-013~RC-015: 技术约定节、四态 UI、伪代码、跨表关联、字段DDL一致性、筛选追溯、非常规逻辑示例",
        "model": "opus",  # 需要深度推理
    },
    "data_quality": {
        "name": "数据质量",
        "codename": "鸬鹚",
        "rules": "RC-009~RC-010: 字段映射一致性、数值类字段标注来源",
        "model": "haiku",  # 相对简单
    },
}

# ============================================================
# 结构化输出 Tool Schema
# ============================================================

SUBMIT_REVIEW_ITEMS_TOOL = {
    "name": "submit_review_items",
    "description": "提交评审改进项。每条必须有完整的依据。",
    "input_schema": {
        "type": "object",
        "properties": {
            "dimension": {"type": "string", "description": "评审维度"},
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "location": {"type": "string", "description": "PRD 中的章节/段落"},
                        "issue": {"type": "string", "description": "具体问题"},
                        "suggestion": {"type": "string", "description": "改进建议"},
                        "severity": {"type": "string", "enum": ["must", "should"]},
                        "evidence_type": {"type": "string", "enum": ["A", "B", "C"]},
                        "evidence_content": {"type": "string", "description": "依据内容"},
                    },
                    "required": ["id", "location", "issue", "suggestion", "severity", "evidence_type", "evidence_content"],
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

## 你的评审维度
{dimension_name}：{dimension_rules}

## 评审要求
1. 仔细阅读 PRD 内容和相关知识库页面
2. 仅关注你负责的评审维度，不要越界评审其他维度
3. 每条改进项必须有明确依据（A=内部知识, B=评审规则, C=外部参考）
4. 找不到依据的改动不得提出
5. 评审完成后，使用 submit_review_items 工具提交所有改进项

## 依据分类
- A（内部知识）：引用 wiki 中的业务知识页面，标注页面名
- B（评审规则）：引用 BMAD 验证步骤或 Review Checklist 条目编号
- C（外部参考）：竞品设计、行业惯例等，必须标记为「待确定⚠️」

## 严重度
- must：必须修改，不改会导致 PRD 无法正确指导开发
- should：建议修改，改了会提升 PRD 质量
"""


def _build_worker_system(dim_key):
    """为某个评审维度构建 system prompt"""
    dim = REVIEW_DIMENSIONS[dim_key]
    return _WORKER_SYSTEM_TEMPLATE.format(
        codename=dim["codename"],
        dimension_name=dim["name"],
        dimension_rules=dim["rules"],
    )


def _build_worker_messages(prd_content, wiki_pages):
    """构建 worker 的 user messages，包含 PRD 和知识库内容"""
    parts = [f"## 待评审 PRD\n\n{prd_content}"]
    if wiki_pages:
        parts.append("## 相关知识库页面\n")
        for title, content in wiki_pages.items():
            parts.append(f"### {title}\n{content}\n")
    parts.append("请评审以上 PRD，然后调用 submit_review_items 工具提交你发现的所有改进项。")
    return [{"role": "user", "content": "\n\n".join(parts)}]


# ============================================================
# 单个 Worker 调用
# ============================================================

def _extract_items_from_response(response):
    """从 Messages API 响应中提取 submit_review_items 的 tool_use 结果"""
    for block in response.content:
        if block.type == "tool_use" and block.name == "submit_review_items":
            return block.input.get("items", [])
    return []


async def _run_worker_async(client, dim_key, prd_content, wiki_pages, model_tiers):
    """异步执行单个评审维度的 worker"""
    dim = REVIEW_DIMENSIONS[dim_key]
    model = model_tiers.get(dim["model"], model_tiers["sonnet"])
    system = _build_worker_system(dim_key)
    messages = _build_worker_messages(prd_content, wiki_pages)

    # 在线程池中调用同步的 messages.create（anthropic SDK 是同步的）
    loop = asyncio.get_running_loop()
    response = await loop.run_in_executor(
        None,
        lambda: client.messages.create(
            model=model,
            max_tokens=4096,
            system=system,
            messages=messages,
            tools=[SUBMIT_REVIEW_ITEMS_TOOL],
            tool_choice={"type": "any"},  # 强制使用工具输出
        ),
    )

    items = _extract_items_from_response(response)
    # 给每条 item 打上维度标签
    for item in items:
        item["dimension"] = dim["name"]
    return {
        "dimension": dim_key,
        "dimension_name": dim["name"],
        "model": model,
        "items": items,
        "usage": {
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
        },
    }


def _run_worker_sync(client, dim_key, prd_content, wiki_pages, model_tiers):
    """同步执行单个评审维度的 worker"""
    dim = REVIEW_DIMENSIONS[dim_key]
    model = model_tiers.get(dim["model"], model_tiers["sonnet"])
    system = _build_worker_system(dim_key)
    messages = _build_worker_messages(prd_content, wiki_pages)

    response = client.messages.create(
        model=model,
        max_tokens=4096,
        system=system,
        messages=messages,
        tools=[SUBMIT_REVIEW_ITEMS_TOOL],
        tool_choice={"type": "any"},
    )

    items = _extract_items_from_response(response)
    for item in items:
        item["dimension"] = dim["name"]
    return {
        "dimension": dim_key,
        "dimension_name": dim["name"],
        "model": model,
        "items": items,
        "usage": {
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
        },
    }


# ============================================================
# 并行评审主函数
# ============================================================

async def parallel_review(client, prd_content, wiki_pages, model_tiers):
    """
    并行执行 4 个评审维度的 worker，合并结果
    - client: anthropic.Anthropic 实例
    - prd_content: PRD 全文字符串
    - wiki_pages: dict {页面标题: 页面内容}，可为空 dict
    - model_tiers: {"opus": "claude-opus-4-6", "sonnet": "claude-sonnet-4-6", "haiku": "claude-haiku-4-5"}
    返回: {"workers": [...], "merged_items": [...], "total_usage": {...}}
    """
    tasks = [
        _run_worker_async(client, dim_key, prd_content, wiki_pages, model_tiers)
        for dim_key in REVIEW_DIMENSIONS
    ]

    # 并行执行，单个 worker 失败不中断整体
    results = await asyncio.gather(*tasks, return_exceptions=True)

    workers = []
    all_items = []
    total_input = 0
    total_output = 0

    for dim_key, result in zip(REVIEW_DIMENSIONS, results):
        if isinstance(result, Exception):
            # worker 失败，记录错误但不中断
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

    return {
        "workers": workers,
        "merged_items": merged,
        "total_usage": {
            "input_tokens": total_input,
            "output_tokens": total_output,
        },
    }


def parallel_review_sync(client, prd_content, wiki_pages, model_tiers):
    """
    同步版本：顺序执行 4 个 worker（给不方便用 async 的场景）
    接口和返回值与 parallel_review 一致
    """
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

    return {
        "workers": workers,
        "merged_items": merged,
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
    # 取依据中的关键词（去掉常见停用词）
    keywords = [w for w in evidence_content.split() if len(w) > 2]
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
    rule_ids = re.findall(r"(?:RC-\d+|V-\d+|BMAD\s+V-\d+)", evidence_content)
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
