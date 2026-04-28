"""
报告可执行化 -- 生成按 PRD 章节分组的开发任务报告
输出开发人员直接可操作的改进清单，每条附带精确位置和改写建议
"""

import os
import re
from datetime import datetime
from collections import defaultdict

from logger import get_logger

log = get_logger("report")


def build_actionable_report(items, prd_content, prd_name, reviewer="", peck_score=None):
    """
    生成可执行的开发任务报告
    - 按 PRD 章节分组（不按评审维度）
    - 每条 item 附带精确位置 + 原文引用 + 改写建议
    - 飞书兼容 markdown 格式
    """
    if not items:
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
        f"must: {sum(1 for i in items if i.get('severity')=='must')}, "
        f"should: {sum(1 for i in items if i.get('severity')=='should')}, "
        f"could: {sum(1 for i in items if i.get('severity')=='could')}）",
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
        must_count = sum(1 for i in section_items if i.get("severity") == "must")
        could_count = sum(1 for i in section_items if i.get("severity") == "could")
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
            item_id = item.get("id", "?")
            severity = item.get("severity", "should")
            if severity == "must":
                severity_badge = "**[必须]**"
            elif severity == "could":
                # facet of primary, 苍鹰冲突合并保留的同源条 (2026-04-24)
                facet_of = item.get("facet_of", "")
                severity_badge = f"[补充·{facet_of}]" if facet_of else "[补充]"
            else:
                severity_badge = "[建议]"
            rule_id = item.get("rule_id", "")
            issue = item.get("issue", "")
            suggestion = item.get("suggestion", "")
            dimension = item.get("dimension", "")

            # 精确位置
            precise = extract_precise_location(item, prd_content)

            lines.append(f"### {item_id} {severity_badge} {rule_id}")
            lines.append(f"")
            # parser 友好字段 -- 让 cuckoo_parser 能抓到 location/severity/evidence_type
            # 这三行是给 eval 解析器看的,徽章形式 **[必须]** 给人看
            location_raw = item.get("location", "") or ""
            ev_type_raw = item.get("evidence_type", "") or ""
            if location_raw:
                lines.append(f"**位置**: {location_raw}")
            lines.append(f"**严重度**: {severity}")
            if ev_type_raw:
                lines.append(f"**依据类型**: {ev_type_raw}")
            lines.append(f"")
            lines.append(f"**问题**: {issue}")
            lines.append(f"")

            if precise.get("quote"):
                lines.append(f"**原文位置**: {precise.get('section', section_name)}")
                lines.append(f"> {precise['quote']}")
                lines.append(f"")

            # 改写建议（原文 → 建议）
            rewrite = generate_rewrite_pair(item, prd_content)
            if rewrite.get("original") and rewrite.get("suggested"):
                lines.append(f"**建议改写**:")
                lines.append(f"- ~~{rewrite['original']}~~")
                lines.append(f"- **{rewrite['suggested']}**")
            else:
                lines.append(f"**建议**: {suggestion}")

            lines.append(f"")

            # 依据(evidence) -- 让 cuckoo_eval 可以回解析,也让评审人看见溯源链
            ev_type = item.get("evidence_type", "")
            ev_content = item.get("evidence_content", "")
            if ev_type or ev_content:
                type_tag = f"[{ev_type}] " if ev_type else ""
                lines.append(f"**依据**: {type_tag}{ev_content}")
                lines.append(f"")

            if dimension:
                lines.append(f"*来源: {dimension} | {rule_id}*")

            # diff_status（如果有）
            diff_status = item.get("diff_status", "")
            if diff_status:
                status_labels = {
                    "new": "本次新发现",
                    "unfixed": "上次已报告但未修复",
                    "fixed": "已修复",
                    "carry_confirmed": "上次已确认不改",
                    "carry_rejected": "上次已驳回",
                }
                label = status_labels.get(diff_status, diff_status)
                lines.append(f"*迭代状态: {label}*")

            lines.append("")
            lines.append("---")
            lines.append("")

    # 开发任务 checklist
    lines.append("## 开发任务 Checklist")
    lines.append("")
    for section_name, section_items in section_groups.items():
        must_items = [i for i in section_items if i.get("severity") == "must"]
        if must_items:
            lines.append(f"### {section_name}")
            for item in must_items:
                lines.append(f"- [ ] {item.get('id', '?')} {item.get('issue', '')[:50]}")
            lines.append("")

    return "\n".join(lines)


def _group_by_section(items):
    """按 PRD 章节分组（从 location 字段提取）"""
    groups = defaultdict(list)
    for item in items:
        location = item.get("location", "")
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

    location = item.get("location", "")
    issue = item.get("issue", "")

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
    suggestion = item.get("suggestion", "")

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
