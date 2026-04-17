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
import random
import re
import time
import glob as glob_module
from difflib import SequenceMatcher

import yaml

from logger import get_logger

log = get_logger("parallel")

from datetime import datetime


def _add_freshness_note(wiki_page_path, content):
    """给 wiki 页面加新鲜度标记（CC memoryAge.ts:33-42 模式）"""
    try:
        mtime = os.path.getmtime(wiki_page_path)
        days = (time.time() - mtime) / 86400
        if days > 7:
            return f"[此页面 {int(days)} 天未更新，内容可能过时，请交叉验证]\n\n{content}"
        elif days > 1:
            return f"[更新于 {int(days)} 天前]\n\n{content}"
    except OSError:
        pass
    return content


def build_wiki_manifest(wiki_pages, wiki_path=None):
    """构建 wiki 页面清单（CC extractMemories manifest 模式）"""
    lines = []
    for title, content in wiki_pages.items():
        mtime_str = ""
        if wiki_path:
            fpath = os.path.join(wiki_path, f"{title}.md")
            try:
                mtime = os.path.getmtime(fpath)
                mtime_str = f" ({datetime.fromtimestamp(mtime).strftime('%Y-%m-%d')})"
            except OSError:
                pass
        desc = content[:80].replace("\n", " ").strip()
        lines.append(f"- {title}{mtime_str}: {desc}")
    return "\n".join(lines)


# 信鸽反馈历史文件路径（延迟解析，避免在 import 时读不到 WORKSPACE 环境变量）
def _get_rule_perf_history_path():
    workspace = os.environ.get("WORKSPACE", os.path.join(os.path.dirname(__file__), "workspace"))
    return os.path.join(workspace, "output", "rule_performance_history.json")

# ============================================================
# 评审维度定义 - 已拆到 review/dimensions.py
# 2026-04-16 重构:保留 re-export 让外部 import parallel_review 不破坏
# ============================================================

from review.dimensions import (  # noqa: E402,F401
    MAX_WORKER_TURNS,
    _BASE_DIR,
    _CN_LABEL,
    _DEFAULT_DIMENSION_WIKI_KEYWORDS,
    _DEFAULT_REVIEW_DIMENSIONS,
    _REVIEW_DIMENSIONS_SCHEMA,
    _YAML_FILENAME,
    _cn_label,
    _validate_review_dimensions_yaml,
    get_review_dimensions,
    get_wiki_keywords,
    load_review_dimensions,
)

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
# Worker System Prompt 模板
# ============================================================

_WORKER_SHARED_RULES = """## 评审要求
1. 仔细阅读 PRD 内容和相关知识库页面
2. **严格只评审你 owner=自己 的规则** — 缺失 ② Worker 边界互斥:
   review-dimensions.yaml 给每条规则标了 owner,你只输出 owner=本维度的 fail。
   即使你看到其他维度的 owner 的规则违反,也禁止报告(那条规则会被对应 worker 处理)。
   越界报告会被苍鹰交叉校验降权 + 杜鹃 verdict 扣分。
3. 逐条对照检查清单,每条规则都要检查
4. 同一条规则如果在多个位置违反,每个位置单独提交一条(rule_id 相同但 location 不同)
5. 每条改进项必须有明确依据(A=内部知识, B=评审规则, C=外部参考)
6. 找不到依据的改动不得提出
7. **允许承认无问题** — 缺失 ④ Worker 拒答出口:
   如果本维度逐条看完没发现 fail,提交空 items 数组并填写 null_finding_reason 说明
   你扫了哪些规则、为什么都 pass。**禁止为了凑数硬找问题**。
8. 评审完成后,使用 submit_review_items 工具提交

## 依据分类
- A(内部知识):引用 wiki 页面,**严格使用 [[页面名]] 双方括号格式**,页面名必须在
  refs 清单中精确匹配(见后面的真实依据清单)。禁止使用《》书名号或其他括号。
- B(评审规则):引用规则编号和原文(RC-XXX 或 V-XX,必须在 refs 清单中)
- C(外部参考):竞品/行业惯例,**必须**标记「⚠️ 待确定」或「外部参考」字样

## 严重度
- must:必须修改,不改会导致 PRD 无法正确指导开发
- should:建议修改,改了会提升 PRD 质量"""

_WORKER_SYSTEM_TEMPLATE = """你是「{codename}」，啄木鸟评审团的 {dimension_name} 评审员。

## 你的逐条打分清单
{dimension_rules}

## 必须打分的规则列表
{checklist_list}

{shared_rules}
"""


def _build_worker_system(dim_key, rule_perf_history=None, dimensions=None, workspace=None):
    """为某个评审维度构建 system prompt，并动态注入：
    1. 信鸽反馈的高发问题规则（rule_perf_history）
    2. workspace 中的真实 rule_id / wiki 页面清单（防止 evidence 造假，借鉴百灵 load_real_imports）
    """
    dims = dimensions or get_review_dimensions()
    dim = dims[dim_key]

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
        shared_rules=_WORKER_SHARED_RULES,
    )

    # --- 动态注入信鸽反馈 ---
    feedback_section = _build_feedback_section(dim_key, rule_perf_history, dims)
    if feedback_section:
        base_prompt += "\n" + feedback_section

    # --- 动态注入真实依据清单（防止 evidence 造假，对应路线图 B1 前置） ---
    refs_section = _build_real_refs_section(workspace)
    if refs_section:
        base_prompt += "\n" + refs_section

    return base_prompt


def _build_feedback_section(dim_key, rule_perf_history=None, dimensions=None):
    """从已加载的 history 中筛选当前维度的高发问题规则"""
    if rule_perf_history is None:
        try:
            with open(_get_rule_perf_history_path(), "r", encoding="utf-8") as f:
                rule_perf_history = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return ""

    if not isinstance(rule_perf_history, dict):
        return ""

    # 2. 提取当前维度涉及的规则编号
    dims = dimensions or get_review_dimensions()
    dim_rules_text = dims[dim_key]["rules"]
    dim_rule_ids = set(re.findall(r"(?:RC-\d+|V-\d+)", dim_rules_text))
    if not dim_rule_ids:
        return ""

    # 3. 筛选异常规则：rejection_rate > 0.3 或 missed > 2 或 eval precision/recall 过低
    flagged = []
    for rule_id, stats in rule_perf_history.items():
        if not isinstance(stats, dict):
            continue
        # 规则编号归一化匹配（history 中可能是 "RC-005" 或 "V-07"）
        canonical = rule_id.strip()
        if canonical not in dim_rule_ids:
            continue

        rejection_rate = stats.get("rejection_rate", 0)
        missed = stats.get("stats", {}).get("missed", 0)

        # F2: 同时考虑 eval_metrics 中的 precision/recall
        eval_m = stats.get("eval_metrics") or {}
        eval_precision = eval_m.get("precision", 1.0)
        eval_recall = eval_m.get("recall", 1.0)
        eval_has_data = bool(eval_m)  # 有数据才参与判断

        triggers = (
            rejection_rate > 0.3
            or missed > 2
            or (eval_has_data and eval_precision < 0.6)
            or (eval_has_data and eval_recall < 0.6)
        )

        if triggers:
            flagged.append({
                "rule_id": canonical,
                "rejection_rate": rejection_rate,
                "missed": missed,
                "name": stats.get("name", ""),
                "recent_total": stats.get("stats", {}).get("total", 0),
                "eval_precision": eval_precision if eval_has_data else None,
                "eval_recall": eval_recall if eval_has_data else None,
            })

    # P0.2: 同时收集 impact_score 异常的规则(低效 / 高效)
    low_impact = []   # impact_score < 0.3
    high_impact = []  # impact_score > 0.8
    for rule_id, stats in rule_perf_history.items():
        if not isinstance(stats, dict):
            continue
        canonical = rule_id.strip()
        if canonical not in dim_rule_ids:
            continue
        impact = stats.get("impact_score")
        if impact is not None:
            name = stats.get("name", "")
            if impact < 0.3:
                low_impact.append({"rule_id": canonical, "name": name, "impact_score": impact})
            elif impact > 0.8:
                high_impact.append({"rule_id": canonical, "name": name, "impact_score": impact})

    if not flagged and not low_impact and not high_impact:
        return ""

    lines = []

    # 原有的异常规则反馈
    if flagged:
        # 4. 按 missed + rejection_rate + 1-precision 综合排序，取前 5 条
        def _severity(r):
            p = r["eval_precision"] if r["eval_precision"] is not None else 1.0
            return (r["missed"], r["rejection_rate"], 1.0 - p)
        flagged.sort(key=_severity, reverse=True)
        flagged = flagged[:5]

        lines += ["## 近期反馈提示", "以下规则在最近的评审中表现异常，请加强审核："]
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
            if r["eval_precision"] is not None and r["eval_precision"] < 0.6:
                parts.append(f"Eval 精确率 {int(r['eval_precision']*100)}%，降低误报")
            if r["eval_recall"] is not None and r["eval_recall"] < 0.6:
                parts.append(f"Eval 召回率 {int(r['eval_recall']*100)}%，加强检出")

            lines.append(f"- {label}：{'；'.join(parts)}")

    # P0.2: impact_score 权重注入 — Worker 感知规则历史表现
    if low_impact:
        lines.append("")
        lines.append("## 低效规则警示")
        for r in sorted(low_impact, key=lambda x: x["impact_score"]):
            label = f"{r['rule_id']}（{r['name']}）" if r["name"] else r["rule_id"]
            score = r["impact_score"]
            lines.append(
                f"- {label}：⚠ 低效规则(impact={score}),"
                f"历史上被评审人频繁驳回,谨慎报告,确保有充分依据"
            )

    if high_impact:
        lines.append("")
        lines.append("## 高效规则优先")
        for r in sorted(high_impact, key=lambda x: -x["impact_score"]):
            label = f"{r['rule_id']}（{r['name']}）" if r["name"] else r["rule_id"]
            score = r["impact_score"]
            lines.append(
                f"- {label}：✓ 高效规则(impact={score}),"
                f"历史上被评审人高度认可,优先检查"
            )

    return "\n".join(lines) + "\n"


def _build_real_refs_section(workspace):
    """扫 workspace 的真实 rule_id 和 wiki 页面清单注入 Worker prompt。

    借鉴百灵（riskbird_test_agent.load_real_imports）的防 FQN 幻觉策略：
    LLM 倾向于编造不存在的规则号和 wiki 引用，明确给出可用清单后显著降低幻觉率。

    配合 review_fixer.fix_review_items 使用——生成后如果 evidence 仍指向清单外的
    规则或页面，verify_evidence 会标记 verification_status=failed 并降权。
    """
    if not workspace or not os.path.isdir(workspace):
        return ""

    # 1. 扫 review-rules/ 抽所有 rule_id
    rule_ids = set()
    rules_dir = os.path.join(workspace, "review-rules")
    if os.path.isdir(rules_dir):
        for root, _, files in os.walk(rules_dir):
            for fn in files:
                if fn.endswith((".md", ".yaml", ".yml", ".txt")):
                    try:
                        fp = os.path.join(root, fn)
                        with open(fp, "r", encoding="utf-8") as f:
                            text = f.read()
                        rule_ids.update(re.findall(r"(?:RC-\d+|V-\d+)", text))
                    except (OSError, UnicodeDecodeError):
                        continue

    # 2. 扫 wiki/ 抽所有页面名(去 .md 扩展名,排除隐藏文件)
    # 缺失 ⑤ A 类新鲜度: 同时记录 mtime,按 30/90/180 天分级标注,worker 自然会偏好新页面
    import time as _time
    now_ts = _time.time()
    wiki_pages = []  # [(name, age_days)]
    wiki_dir = os.path.join(workspace, "wiki")
    if os.path.isdir(wiki_dir):
        for fn in sorted(os.listdir(wiki_dir)):
            if fn.endswith(".md") and not fn.startswith("."):
                fp = os.path.join(wiki_dir, fn)
                try:
                    mtime = os.path.getmtime(fp)
                    age_days = int((now_ts - mtime) / 86400)
                except OSError:
                    age_days = 0
                wiki_pages.append((fn[:-3], age_days))

    if not rule_ids and not wiki_pages:
        return ""

    lines = [
        "## 真实依据清单（强制复用）",
        "以下清单由 workspace 扫描生成。verify_evidence 会对每条 item 的依据做硬验证：",
        "引用清单外的 rule_id 或 wiki 页面 → 标记 verification_status=failed → confidence_score 降权 50%。",
        "",
        "### 依据格式铁律（违反即 FAIL）",
        "",
        "- **B 类**：`evidence_content` 必须包含 `RC-\\d+` 或 `V-\\d+` 格式的真实规则号（从下表选），禁止只写规则描述。",
        "- **A 类**：`evidence_content` 必须包含 `[[页面名]]` 双方括号格式引用，**禁止使用《》书名号、「」、引号或其他符号**。页面名必须与下表精确一致。",
        "- **C 类**：竞品/行业/经验，必须在 `evidence_content` 里明确标注 `⚠️ 待确定` 或 `外部参考`，否则算 C 类违规。",
        "- **如果你想引用的规则/页面不在下表中**：降级为 C 类 + `⚠️ 待确定`，不要强行用 A/B 造假。",
        "",
    ]

    if rule_ids:
        lines.append(f"### 可用规则编号（{len(rule_ids)} 条，仅用于 evidence_type=B）")
        lines.append("")
        # 分行显示更紧凑,每行 5 个
        sorted_rules = sorted(rule_ids)
        for i in range(0, len(sorted_rules), 5):
            lines.append("  " + "  ".join(f"`{r}`" for r in sorted_rules[i:i+5]))
        lines.append("")

    if wiki_pages:
        lines.append(f"### 可用 wiki 页面({len(wiki_pages)} 条,仅用于 evidence_type=A)")
        lines.append("")
        lines.append("**正例**:`**依据**: [A] [[约束-接口命名规范]] 第 3 节约定所有 endpoint 必须 /api/v1 前缀`")
        lines.append("**反例**:`**依据**: [A] 知识库《约束-接口命名规范》...`  <- 书名号会被判 failed")
        lines.append("**反例**:`**依据**: [A] [[不存在的页面]]`  <- 页面不在下表会被判 failed")
        lines.append("")
        lines.append("**新鲜度标注** (缺失 ⑤): `🟢 新鲜` <30天 / `🟡 一般` 30-90天 / `🟠 旧` 90-180天 / `🔴 过期` >180天")
        lines.append("过期的 wiki 页面优先级低,如果新页面也能引用,优先用新的。")
        lines.append("")
        for p, age_days in wiki_pages:
            if age_days < 30:
                badge = "🟢"
            elif age_days < 90:
                badge = "🟡"
            elif age_days < 180:
                badge = "🟠"
            else:
                badge = "🔴"
            lines.append(f"- {badge} `[[{p}]]` ({age_days}d)")
        lines.append("")

    return "\n".join(lines)


def _maybe_compact_wiki(wiki_pages, budget):
    """二次截断钩子 (CC compact 模式预留接口)。

    当 prompt token 估算超过 COMPACT_THRESHOLD 时调用。
    目前只 log + 返回原 wiki_pages,留接口给未来真正的压缩实现。
    """
    log.info(f"[compact] _maybe_compact_wiki 被调用, pages={len(wiki_pages)}, budget={budget}")
    # TODO: 未来实现: 按相关性评分截断低分 wiki 页面,或对长页面做摘要
    return wiki_pages


def _build_worker_messages(prd_content, wiki_pages, dim_key=None, wiki_path=None, wiki_keywords=None, diff_context=None):
    """构建 worker 的 user messages，包含 PRD 和知识库内容"""
    from agent_config import MAX_WIKI_CHARS, COMPACT_THRESHOLD

    wk = wiki_keywords or get_wiki_keywords()
    parts = [f"## 待评审 PRD\n\n{prd_content}"]
    if diff_context:
        parts.insert(0, diff_context)  # diff context before PRD content
    wiki_char_total = 0
    if wiki_pages:
        # 按维度筛选相关 wiki 页面，减少无关上下文
        if dim_key and dim_key in wk:
            keywords = wk[dim_key]
            relevant = {t: c for t, c in wiki_pages.items()
                        if any(kw in t for kw in keywords)}
            filtered = relevant if relevant else wiki_pages
        else:
            filtered = wiki_pages
        # strong 页(≥3 关键词命中)= filtered 里和 relevant 交集的;
        # weak 页 = filtered 里不在 relevant 里的(fallback 到全量时全部算 weak)
        strong_titles = set(relevant.keys()) if dim_key and dim_key in wk else set()

        WEAK_SUMMARY_CHARS = 500  # weak 页只传前 500 字摘要

        parts.append("## 相关知识库页面\n")
        for title, content in filtered.items():
            # 加新鲜度标记（CC memoryAge 模式）
            if wiki_path:
                fpath = os.path.join(wiki_path, f"{title}.md")
                content = _add_freshness_note(fpath, content)
            # strong 页全文, weak 页截断到 500 字摘要
            is_strong = title in strong_titles or not strong_titles
            if not is_strong and len(content) > WEAK_SUMMARY_CHARS:
                content = content[:WEAK_SUMMARY_CHARS] + f"\n\n(... 余 {len(content) - WEAK_SUMMARY_CHARS} 字已省略 — weak 相关页摘要)"
            wiki_char_total += len(content)
            parts.append(f"### {title}\n{content}\n")

        # 1b: rapid_refill_breaker 钩子 — wiki 注入接近预算上限时 warning
        if wiki_char_total > MAX_WIKI_CHARS * 0.95:
            log.warning(f"[{_cn_label(dim_key) if dim_key else 'global'}] approaching wiki budget limit: {wiki_char_total:,} / {MAX_WIKI_CHARS:,} chars (95%+)")

    parts.append("请评审以上 PRD，逐条对照你的检查清单，然后调用 submit_review_items 工具提交发现的所有改进项。每条改进项必须标注 rule_id。")

    messages = [{"role": "user", "content": "\n\n".join(parts)}]

    # 4a: token 估算 (CC tokenEstimation 模式)
    estimated_tokens = len(json.dumps(messages, ensure_ascii=False).encode()) // 4
    log.info(f"[{_cn_label(dim_key) if dim_key else 'global'}] estimated prompt tokens: {estimated_tokens:,}")
    if estimated_tokens > 100_000:
        log.warning(f"[{_cn_label(dim_key) if dim_key else 'global'}] prompt token 估算 > 100K,可能触发 context overflow")

    # 4b: compact 钩子 — 超阈值时尝试二次截断 wiki
    if estimated_tokens > COMPACT_THRESHOLD and wiki_pages:
        wiki_pages = _maybe_compact_wiki(wiki_pages, COMPACT_THRESHOLD)

    return messages


# ============================================================
# 单个 Worker 调用
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


def _worker_core(client, dim_key, prd_content, wiki_pages, model_tiers, rule_perf_history=None, wiki_path=None, diff_context=None):
    """Worker 核心逻辑（sync），返回首次 API 响应和处理后的 items 列表。
    async 版本通过 run_in_executor 包装此函数。"""
    # 3a: telemetry — 记录 worker 开始时间
    start_time = time.time()
    dimensions = get_review_dimensions()
    wiki_keywords = get_wiki_keywords()
    dim = dimensions[dim_key]
    model = model_tiers.get(dim["model"], model_tiers["sonnet"])

    # Pattern 20: Effort-Aware Prompt Adaptation — 从 dim config 读 effort level
    from agent_config import EFFORT_TOKENS
    effort = dim.get("effort", "medium")
    max_tokens = EFFORT_TOKENS.get(effort, 8192)

    # Pattern 18: 每个 worker 独立的 cache monitor 实例(线程安全)
    from cache_monitor import PromptCacheMonitor
    cache_monitor = PromptCacheMonitor()
    # 从 wiki_path 反推 workspace(wiki_path 总是 workspace/wiki),注入真实依据清单防幻觉
    workspace_dir = os.path.dirname(wiki_path) if wiki_path else None
    dynamic_system = _build_worker_system(dim_key, rule_perf_history, dimensions, workspace=workspace_dir)
    messages = _build_worker_messages(prd_content, wiki_pages, dim_key, wiki_path, wiki_keywords, diff_context)

    # CC 模式：system prompt 分静态/动态两段（参考 prompts.ts:560 的 DYNAMIC_BOUNDARY）
    # 静态段（共享规则）打 cache_control，4 个 worker 共享缓存
    # 动态段（维度规则 + 反馈注入）不缓存
    system_blocks = [
        {"type": "text", "text": _WORKER_SHARED_RULES, "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": dynamic_system},
    ]

    # prompt 指纹日志 (CC firstChangedMessageIndex 模式)
    # server-side prompt cache 自动匹配 hash,这里记录 hash 方便调试缓存命中
    import hashlib as _hl
    static_hash = _hl.md5(_WORKER_SHARED_RULES.encode()).hexdigest()[:8]
    dynamic_hash = _hl.md5(dynamic_system.encode()).hexdigest()[:8]
    msg_hash = _hl.md5(json.dumps(messages, ensure_ascii=False).encode()).hexdigest()[:8]
    log.info(f"[{_cn_label(dim_key)}] prompt_hash static={static_hash} dynamic={dynamic_hash} msg={msg_hash}")

    # 正向工具白名单: tool_choice 里标注维度名,让 submit_review_items 的
    # dimension 字段被 schema 约束为只能填自己的维度名 (CC allowedTools 模式)
    dim_constrained_tool = json.loads(json.dumps(SUBMIT_REVIEW_ITEMS_TOOL))
    dim_constrained_tool["input_schema"]["properties"]["dimension"] = {
        "type": "string",
        "const": dim["name"],
        "description": f"评审维度(必须填 '{dim['name']}')",
    }

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
        except Exception:
            pass

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

    # 过滤非 dict 元素（模型偶尔返回字符串数组而非对象数组）
    items = [item for item in items if isinstance(item, dict)]

    # 强制校正维度名 (防止模型绕过 schema const 约束)
    for item in items:
        if item.get("dimension") and item["dimension"] != dim["name"]:
            log.warning(f"[{_cn_label(dim_key)}] 维度越界: {item.get('dimension')} → {dim['name']}")
        item["dimension"] = dim["name"]

    # P1.3: Worker 规则越界硬校验 — checklist 里定义的 rule_id 才是本维度的合法范围
    valid_rule_ids = {r["rule_id"] for r in dim.get("checklist", [])}
    for item in items:
        rid = item.get("rule_id", "")
        if rid and valid_rule_ids and rid not in valid_rule_ids:
            log.warning(f"[{_cn_label(dim_key)}] 规则越界: {rid} 不在 {dim_key} checklist 中")
            item["cross_boundary"] = True
            # 2026-04-16 harness audit 修复: 原先改的是 confidence 字段,
            # 下游(scorer/merge/verify)全部只读 confidence_score,导致越界惩罚静默失效。
            # 统一成 confidence_score,让惩罚真的作用到下游加权。
            current = item.get("confidence_score", 0.85)
            item["confidence_score"] = max(0.0, round(current - 0.3, 2))

    # 2a: Tool Result 截断 — 单 worker 输出上限 (CC tool result truncation 模式)
    from agent_config import MAX_ITEMS_PER_WORKER
    if len(items) > MAX_ITEMS_PER_WORKER:
        log.warning(f"[{_cn_label(dim_key)}] Worker 输出 {len(items)} 条,截断到 {MAX_ITEMS_PER_WORKER}")
        # 按 severity (must 优先) + confidence (高优先) 排序,保留 top N
        items.sort(key=lambda x: (0 if x.get("severity") == "must" else 1, -x.get("confidence_score", 0)))
        items = items[:MAX_ITEMS_PER_WORKER]

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


async def _run_worker_async(client, dim_key, prd_content, wiki_pages, model_tiers, rule_perf_history=None, wiki_path=None, diff_context=None):
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


def _run_worker_sync(client, dim_key, prd_content, wiki_pages, model_tiers, rule_perf_history=None, wiki_path=None, diff_context=None):
    """同步包装：直接调用 _worker_core"""
    return _worker_core(client, dim_key, prd_content, wiki_pages, model_tiers, rule_perf_history, wiki_path, diff_context)




# ============================================================
# 并行评审主函数
# ============================================================

async def _single_round_async(client, prd_content, wiki_pages, model_tiers, wiki_path=None, diff_context=None, on_worker_done=None):
    """单轮并行评审（内部函数），返回 workers, merged_items, usage

    Args:
        on_worker_done: 可选 callback,签名为 (dim_key: str, result: dict) -> None
            每个 worker 完成时(成功或失败)都会调用,让上层(FastAPI SSE)感知进度。
            默认 None,保持向后兼容,CLI 现有流程零影响。
    """
    dimensions = get_review_dimensions()

    # 读一次 rule performance history，传给所有 worker（避免 4 次 I/O）
    rule_perf_history = None
    try:
        with open(_get_rule_perf_history_path(), "r", encoding="utf-8") as f:
            rule_perf_history = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass

    # 错峰启动: Windows 下 4 个 claude CLI 子进程同时启动会触发 Node.js libuv assertion
    # (UV_HANDLE_CLOSING / 0xC0000409 STATUS_STACK_BUFFER_OVERRUN),给每个 worker 加 stagger
    async def _staggered(idx, dim_key):
        await asyncio.sleep(idx * 0.3)  # 0.5→0.3: 省 0.8s 总启动时间
        try:
            result = await _run_worker_async(
                client, dim_key, prd_content, wiki_pages, model_tiers, rule_perf_history, wiki_path, diff_context
            )
            # 新增: worker 完成后通知外层(FastAPI SSE 用,CLI 模式下 callback 为 None 就跳过)
            if on_worker_done is not None:
                try:
                    on_worker_done(dim_key, result)
                except Exception:
                    pass  # callback 异常绝不影响主流程
            return result
        except Exception as e:
            # 失败也要通知,这样 UI 能显示 worker 失败状态而不是永远挂 pending
            if on_worker_done is not None:
                try:
                    on_worker_done(dim_key, {"error": str(e)[:200]})
                except Exception:
                    pass
            raise

    tasks = [
        _staggered(idx, dim_key)
        for idx, dim_key in enumerate(dimensions)
    ]

    # 总体超时兜底:即使单 Worker 超时被捕获,线程池层面仍可能因极端情况拖住
    from agent_config import TOTAL_REVIEW_TIMEOUT
    try:
        results = await asyncio.wait_for(
            asyncio.gather(*tasks, return_exceptions=True),
            timeout=TOTAL_REVIEW_TIMEOUT,
        )
    except asyncio.TimeoutError:
        # 外层 deadman switch 触发,把未完成的任务占位为 timeout 错误
        log.error(f"并行评审总体超时({TOTAL_REVIEW_TIMEOUT}s),强制结束")
        results = [
            asyncio.TimeoutError(f"总体超时({TOTAL_REVIEW_TIMEOUT}s)")
            for _ in tasks
        ]

    workers = []
    all_items = []
    total_input = 0
    total_output = 0

    failed_dims = []
    api_unavailable = False
    for dim_key, result in zip(dimensions, results):
        if isinstance(result, Exception):
            err_msg = str(result)
            log.warning(f"[{_cn_label(dim_key)}] Worker 失败: {err_msg[:80]}")
            failed_dims.append(dim_key)
            workers.append({
                "dimension": dim_key,
                "dimension_name": dimensions[dim_key]["name"],
                "error": err_msg,
                "items": [],
            })
            if "503" in err_msg or "No available account" in err_msg or "upstream_error" in err_msg:
                api_unavailable = True
        else:
            workers.append(result)
            all_items.extend(result["items"])
            total_input += result["usage"]["input_tokens"]
            total_output += result["usage"]["output_tokens"]

    # 断路器: 可配置的最大 worker 连续失败数 (CC circuit breaker 模式)
    from agent_config import MAX_CONSECUTIVE_WORKER_FAILURES

    # API 不可用时给出明确提示，不要报"过多 Worker 失败"
    if api_unavailable and len(failed_dims) > MAX_CONSECUTIVE_WORKER_FAILURES:
        raise RuntimeError(f"API 不可用（503），请检查中转站额度后重试")

    # 断路器触发: 失败 worker 数超过阈值
    if len(failed_dims) > MAX_CONSECUTIVE_WORKER_FAILURES:
        raise RuntimeError(f"断路器触发: Worker 失败 ({len(failed_dims)}/4) 超过阈值 {MAX_CONSECUTIVE_WORKER_FAILURES}: {failed_dims}")

    # Scratchpad：记录各 worker 发现的规则 ID（CC coordinatorMode.ts 的 scratchpad 模式）
    scratchpad = {}
    for w in workers:
        if "error" not in w or not w.get("error"):
            dim = w.get("dimension", "")
            scratchpad[dim] = {
                "found_rule_ids": w.get("found_rule_ids", []),
                "item_count": len(w.get("items", [])),
            }

    merged = merge_and_deduplicate(all_items)
    return workers, merged, total_input, total_output


async def parallel_review(client, prd_content, wiki_pages, model_tiers, voting_rounds=1, wiki_path=None, diff_context=None, on_worker_done=None):
    """
    并行执行 4 个评审维度的 worker，合并结果
    - client: anthropic.Anthropic 实例
    - prd_content: PRD 全文字符串
    - wiki_pages: dict {页面标题: 页面内容}，可为空 dict
    - model_tiers: {"opus": "claude-opus-4-6", "sonnet": "claude-sonnet-4-6", "haiku": "claude-haiku-4-5"}
    - voting_rounds: 评审轮次，1=单次（默认），>=2 时启用多数投票
    - on_worker_done: 可选 callback (dim_key, result_dict) -> None,
      每个 worker 完成时调用,给 FastAPI SSE 层推进度。默认 None 保持 CLI 兼容。
    返回: {"workers": [...], "merged_items": [...], "total_usage": {...}}
    """
    if voting_rounds <= 1:
        # 单轮评审，保持原有行为
        workers, merged, total_input, total_output = await _single_round_async(
            client, prd_content, wiki_pages, model_tiers, wiki_path, diff_context,
            on_worker_done=on_worker_done,
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
            client, prd_content, wiki_pages, model_tiers, wiki_path, diff_context,
            on_worker_done=on_worker_done,
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


def _single_round_sync(client, prd_content, wiki_pages, model_tiers, wiki_path=None, diff_context=None):
    """单轮顺序评审（内部函数），返回 workers, merged_items, usage"""
    dimensions = get_review_dimensions()

    # 读一次 rule performance history，传给所有 worker（避免 4 次 I/O）
    rule_perf_history = None
    try:
        with open(_get_rule_perf_history_path(), "r", encoding="utf-8") as f:
            rule_perf_history = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass

    workers = []
    all_items = []
    total_input = 0
    total_output = 0
    failed_dims = []

    for dim_key in dimensions:
        try:
            result = _run_worker_sync(client, dim_key, prd_content, wiki_pages, model_tiers, rule_perf_history, wiki_path, diff_context)
            workers.append(result)
            all_items.extend(result["items"])
            total_input += result["usage"]["input_tokens"]
            total_output += result["usage"]["output_tokens"]
        except Exception as e:
            err_msg = str(e)
            log.warning(f"[{_cn_label(dim_key)}] Worker 失败: {err_msg[:80]}")
            failed_dims.append(dim_key)
            workers.append({
                "dimension": dim_key,
                "dimension_name": dimensions[dim_key]["name"],
                "error": err_msg,
                "items": [],
            })
            # API 不可用（503/账户耗尽）时直接中断，不浪费后续 worker 的调用
            if "503" in err_msg or "No available account" in err_msg or "upstream_error" in err_msg:
                log.warning(f"API 不可用，跳过剩余 worker")
                for remaining_key in list(dimensions.keys()):
                    if remaining_key not in [w.get("dimension") for w in workers]:
                        failed_dims.append(remaining_key)
                        workers.append({
                            "dimension": remaining_key,
                            "dimension_name": dimensions[remaining_key]["name"],
                            "error": "跳过（API 不可用）",
                            "items": [],
                        })
                break

    # 断路器: 可配置的最大 worker 连续失败数 (CC circuit breaker 模式)
    from agent_config import MAX_CONSECUTIVE_WORKER_FAILURES
    if len(failed_dims) > MAX_CONSECUTIVE_WORKER_FAILURES:
        raise RuntimeError(f"断路器触发: Worker 失败 ({len(failed_dims)}/4) 超过阈值 {MAX_CONSECUTIVE_WORKER_FAILURES}: {failed_dims}")

    # Scratchpad：记录各 worker 发现的规则 ID
    scratchpad = {}
    for w in workers:
        if "error" not in w or not w.get("error"):
            dim = w.get("dimension", "")
            scratchpad[dim] = {
                "found_rule_ids": w.get("found_rule_ids", []),
                "item_count": len(w.get("items", [])),
            }

    merged = merge_and_deduplicate(all_items)
    return workers, merged, total_input, total_output


def parallel_review_sync(client, prd_content, wiki_pages, model_tiers, voting_rounds=1, wiki_path=None, diff_context=None):
    """
    同步版本：顺序执行 4 个 worker（给不方便用 async 的场景）
    接口和返回值与 parallel_review 一致
    - voting_rounds: 评审轮次，1=单次（默认），>=2 时启用多数投票
    """
    if voting_rounds <= 1:
        workers, merged, total_input, total_output = _single_round_sync(
            client, prd_content, wiki_pages, model_tiers, wiki_path, diff_context
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
            client, prd_content, wiki_pages, model_tiers, wiki_path, diff_context
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

# ============================================================
# 依据验证 (Side Query) - 已拆到 review/evidence_verify.py
# 2026-04-16 重构:保留 re-export 让外部 import parallel_review 不破坏
# ============================================================

from review.evidence_verify import (  # noqa: E402,F401
    _build_wiki_index,
    _find_rule_reference,
    _find_wiki_page,
    _verify_b_class_semantic,
    summarize_verification,
    verify_evidence,
)


# ============================================================
# 合并与去重 - 已拆到 review/aggregation.py (2026-04-16)
# ============================================================

from review.aggregation import majority_vote, merge_and_deduplicate  # noqa: E402,F401


