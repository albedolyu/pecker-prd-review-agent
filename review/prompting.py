"""Cluster B — Worker prompt 构建 + wiki/feedback 清单注入.

从 parallel_review.py 拆出 (2026-04-16 继续 SPLIT_PLAN 阶段 4):
- 常量: _WORKER_SHARED_RULES / _WORKER_SYSTEM_TEMPLATE
- wiki 工具: _add_freshness_note / build_wiki_manifest / _maybe_compact_wiki
- system prompt: _build_worker_system / _build_feedback_section / _build_real_refs_section
- user messages: _build_worker_messages

本模块无 Anthropic API 调用, 纯 prompt 构建。依赖 review.dimensions 取维度配置。
parallel_review.py re-export 这些符号, 现有调用方无需改动 import 路径。
"""

import json
import os
import re
import time
from datetime import datetime

from io_utils import try_read_json
from logger import get_logger
from review.dimensions import (
    _cn_label,
    _get_rule_perf_history_path,
    get_review_dimensions,
    get_wiki_keywords,
)

log = get_logger("parallel")


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
        rule_perf_history = try_read_json(_get_rule_perf_history_path(), default=None)
        if rule_perf_history is None:
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
    """二次截断钩子 (CC compact 模式预留接口).

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
