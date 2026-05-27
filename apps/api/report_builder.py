"""
报告可执行化 -- 生成按 PRD 章节分组的开发任务报告
输出开发人员直接可操作的改进清单，每条附带精确位置和改写建议

2026-04-28 重构 (v2 路线图步骤 2+3):
- 用 review.finding_schema 的 InternalFinding ↔ RenderedFinding 双 schema
- profile (chill/strict) 决定哪些 severity 渲染, chill 隐藏 could
"""

import os
import re
from datetime import datetime
from collections import defaultdict

from logger import get_logger
from review.finding_schema import (
    PROFILE_CHILL,
    PROFILE_STRICT,
    filter_by_profile,
    to_rendered,
)

log = get_logger("report")


def _item_get(item, key, default=""):
    """容忍 dict 和 InternalFinding — filter_by_profile 不强转类型, 这里统一访问."""
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


def _feedback_links(finding_id, rule_id="", prd_name="", workspace="", severity=""):
    """生成 finding 反馈链接 (markdown). 渲染在 finding block 末尾.

    PECKER_FEEDBACK_BASE_URL 控制 host (默认 http://localhost:8000), 设为空字符串
    禁用 (Web/邮件等不希望出现链接的渠道)。

    Web 端 PM 点链接 → 后端 /api/feedback/* → 写 finding_outcomes_store.
    """
    base = os.environ.get("PECKER_FEEDBACK_BASE_URL", "http://localhost:8000")
    if not base or not finding_id:
        return ""
    # 编码 query (规避中文 prd_name)
    from urllib.parse import urlencode
    qs = urlencode({
        "finding_id": finding_id,
        "rule_id": rule_id or "",
        "prd_name": prd_name or "",
        "workspace": workspace or "",
        "severity": severity or "",
    })
    accept = f"{base}/api/feedback/accept?{qs}"
    reject = f"{base}/api/feedback/reject?{qs}"
    edit = f"{base}/api/feedback/edit?{qs}"
    # 用 sub 字号控制视觉权重 — 反馈链接是辅助操作不抢主信息
    return (
        f"<sub>"
        f"反馈: [接受]({accept}) · [误报]({reject}) · [改写]({edit})"
        f"</sub>"
    )


def build_actionable_report(
    items,
    prd_content,
    prd_name,
    reviewer="",
    peck_score=None,
    profile=PROFILE_CHILL,
    workspace="",
):
    """
    生成可执行的开发任务报告
    - 按 PRD 章节分组（不按评审维度）
    - 每条 item 附带精确位置 + 原文引用 + 改写建议
    - 飞书兼容 markdown 格式

    Args:
        profile: chill (默认) — must 全展示 + should >0.8 confidence + 隐藏 could
                 strict — 全部展示 (与 v1 行为一致)
    """
    if not items:
        return ""

    # profile 过滤 — chill 隐藏 could / 低 confidence should
    items = filter_by_profile(items, profile=profile)
    if not items:
        # 过滤完空了 (e.g. 全是 could 级 + chill 模式), 返回空字符串
        return ""

    date_str = datetime.now().strftime("%Y-%m-%d")
    lines = [
        f"# PRD 开发任务清单",
        f"",
        f"**PRD**: {prd_name}",
        f"**生成时间**: {date_str}",
        f"**审阅人**: {reviewer}" if reviewer else "",
        f"**啄伤度**: {peck_score}" if peck_score is not None else "",
        f"**改进项总数**: {len(items)} 条（"
        f"must: {sum(1 for i in items if _item_get(i, 'severity')=='must')}, "
        f"should: {sum(1 for i in items if _item_get(i, 'severity')=='should')}, "
        f"could: {sum(1 for i in items if _item_get(i, 'severity')=='could')}）",
        "",
        "---",
        "",
    ]

    try:
        from review.implement_convention import build_report_notice
        lines.extend(build_report_notice().splitlines())
        lines.extend(["", "---", ""])
    except Exception:
        pass

    # 按 location 章节分组
    section_groups = _group_by_section(items)

    for section_name, section_items in section_groups.items():
        must_count = sum(1 for i in section_items if _item_get(i, "severity") == "must")
        could_count = sum(1 for i in section_items if _item_get(i, "severity") == "could")
        should_count = len(section_items) - must_count - could_count

        lines.append(f"## {section_name}")
        lines.append(f"")
        section_summary = f"改进项: {len(section_items)} 条 (must: {must_count}, should: {should_count}"
        if could_count:
            section_summary += f", could: {could_count}"
        section_summary += ")"
        lines.append(section_summary)
        lines.append("")

        for item in section_items:
            # 2026-04-28 v2: 走 RenderedFinding 单源, 不再直接读 9 个 dict 字段
            # InternalFinding 字段全在 schema, 这里只挑 PR-Agent 风格 surface 字段渲染
            precise = extract_precise_location(item, prd_content)
            rewrite = generate_rewrite_pair(item, prd_content)
            rendered = to_rendered(
                item,
                quote=precise.get("quote", ""),
                rewrite=rewrite,
            )
            block = rendered.to_markdown_block()
            # 反馈链接 — PECKER_FEEDBACK_BASE_URL 启用时插到 metadata sub 行后, --- 前
            fb = _feedback_links(
                finding_id=_item_get(item, "id", ""),
                rule_id=_item_get(item, "rule_id", ""),
                prd_name=prd_name,
                workspace=workspace,
                severity=_item_get(item, "severity", ""),
            )
            if fb and "---" in block:
                # 找到末尾的 --- 分隔行, 在它前一行插入 fb
                hr_idx = next((i for i in range(len(block) - 1, -1, -1) if block[i].strip() == "---"), None)
                if hr_idx is not None:
                    block.insert(hr_idx, fb)
                    block.insert(hr_idx + 1, "")
            lines.extend(block)

    # 开发任务 checklist
    lines.append("## 开发任务 Checklist")
    lines.append("")
    for section_name, section_items in section_groups.items():
        must_items = [i for i in section_items if _item_get(i, "severity") == "must"]
        if must_items:
            lines.append(f"### {section_name}")
            for item in must_items:
                _id = _item_get(item, "id", "?")
                _issue = _item_get(item, "issue", "")[:50]
                lines.append(f"- [ ] {_id} {_issue}")
            lines.append("")

    return "\n".join(lines)


def _group_by_section(items):
    """按 PRD 章节分组（从 location 字段提取）"""
    groups = defaultdict(list)
    for item in items:
        location = _item_get(item, "location", "")
        # 提取章节名（如 "3.7 排序规则" → "3.7 排序规则"）
        section = _normalize_section(location) or "其他"
        groups[section].append(item)

    # 按章节号排序
    def sort_key(section_name):
        m = re.match(r'(\d+)\.?(\d*)', section_name)
        if m:
            major = int(m.group(1))
            minor = int(m.group(2)) if m.group(2) else 0
            return (major, minor)
        return (999, 0)

    return dict(sorted(groups.items(), key=lambda kv: sort_key(kv[0])))


def _normalize_section(location):
    """归一化 location 为章节名"""
    if not location:
        return ""
    # 去掉 "第X章" 格式
    location = re.sub(r'^第(\d+)章\s*', r'\1 ', location)
    # 去掉多余空格
    return location.strip()


def extract_precise_location(item, prd_content):
    """
    从 PRD 原文中定位 item 所指的具体段落
    返回 {"section": str, "quote": str, "line_range": str}
    """
    if not prd_content:
        return {}

    location = _item_get(item, "location", "")
    issue = _item_get(item, "issue", "")

    # 尝试从 issue 中提取关键短语（引号内的内容）
    quoted = re.findall(r'[「"\'](.*?)[」"\']', issue)

    # 在 PRD 中搜索关键短语
    for phrase in quoted:
        if len(phrase) < 4:
            continue
        idx = prd_content.find(phrase)
        if idx >= 0:
            # 取前后各 50 字符作为上下文
            start = max(0, idx - 30)
            end = min(len(prd_content), idx + len(phrase) + 30)
            context = prd_content[start:end].strip()
            # 计算行号
            line_num = prd_content[:idx].count("\n") + 1
            return {
                "section": location,
                "quote": context,
                "line_range": f"L{line_num}",
            }

    # 兜底：用 location 中的关键词搜索
    cn_keywords = re.findall(r'[\u4e00-\u9fff]{2,6}', issue)
    for kw in cn_keywords[:3]:
        idx = prd_content.find(kw)
        if idx >= 0:
            start = max(0, idx - 20)
            end = min(len(prd_content), idx + len(kw) + 50)
            context = prd_content[start:end].strip()
            return {"section": location, "quote": context}

    return {"section": location}


def generate_rewrite_pair(item, prd_content):
    """
    生成 {原文, 建议改写} 对
    从 suggestion 中提取 "X → Y" 或 "将X改为Y" 格式
    """
    suggestion = _item_get(item, "suggestion", "")

    # 模式 1: "X → Y" 或 "X -> Y"
    m = re.search(r'[「"](.*?)[」"]\s*[→\->]+\s*[「"](.*?)[」"]', suggestion)
    if m:
        return {"original": m.group(1), "suggested": m.group(2)}

    # 模式 2: "将 X 改为 Y"
    m = re.search(r'将\s*[「"](.*?)[」"]\s*改[为成]\s*[「"](.*?)[」"]', suggestion)
    if m:
        return {"original": m.group(1), "suggested": m.group(2)}

    # 模式 3: suggestion 本身就是改写建议
    if len(suggestion) < 100:
        return {"original": "", "suggested": suggestion}

    return {}


def format_feishu_markdown(text):
    """飞书兼容格式调整"""
    # 飞书不支持 ~~删除线~~，用 [删除] 替代
    text = re.sub(r'~~(.+?)~~', r'[删除]\1[/删除]', text)
    # 飞书表格兼容（保持 | 格式）
    return text
