"""
PRD 迭代 Diff -- 检测重复评审，提供 section 级变更和历史决策上下文
"""

import os
import re
from difflib import SequenceMatcher

from logger import get_logger

log = get_logger("diff")


def detect_previous_review(workspace, prd_name):
    """扫描 output/ 找同名 PRD 的上次评审快照，返回 dict 或 None"""
    output_dir = os.path.join(workspace, "output")
    if not os.path.isdir(output_dir):
        return None

    snapshots = []
    for fname in os.listdir(output_dir):
        if fname.startswith("PRD_原版_") and fname.endswith(".md"):
            m = re.search(r'(\d{8})', fname)
            date_str = m.group(1) if m else ""
            snapshots.append({"path": os.path.join(output_dir, fname), "date": date_str})

    if not snapshots:
        return None

    snapshots.sort(key=lambda s: s["date"], reverse=True)
    latest = snapshots[0]

    report_path = None
    reports = [f for f in os.listdir(output_dir) if f.startswith("PRD_改动报告_") and f.endswith(".md")]
    for fname in sorted(reports, reverse=True):
        if latest["date"] in fname:
            report_path = os.path.join(output_dir, fname)
            break
    if not report_path and reports:
        report_path = os.path.join(output_dir, sorted(reports, reverse=True)[0])

    return {"snapshot_path": latest["path"], "report_path": report_path, "date": latest["date"]}


def compute_section_diff(old_prd, new_prd):
    """按 markdown 标题切分，比较每个 section 的变更状态"""
    old_sections = _split_sections(old_prd)
    new_sections = _split_sections(new_prd)
    old_map = {s["heading"]: s["text"] for s in old_sections}
    new_map = {s["heading"]: s["text"] for s in new_sections}
    all_headings = list(dict.fromkeys(
        [s["heading"] for s in old_sections] + [s["heading"] for s in new_sections]
    ))

    diffs = []
    for heading in all_headings:
        old_text = old_map.get(heading, "")
        new_text = new_map.get(heading, "")
        if heading not in old_map:
            status = "added"
        elif heading not in new_map:
            status = "removed"
        elif old_text == new_text:
            status = "unchanged"
        else:
            sim = SequenceMatcher(None, old_text, new_text).ratio()
            status = "unchanged" if sim > 0.95 else "modified"
        diffs.append({"heading": heading, "status": status, "old_text": old_text, "new_text": new_text})
    return diffs


def _split_sections(text):
    """按 ## 或 ### 标题切分 markdown"""
    sections = []
    current_heading = "(开头)"
    current_lines = []
    for line in text.split("\n"):
        m = re.match(r'^(#{2,3})\s+(.+)', line)
        if m:
            if current_lines:
                sections.append({"heading": current_heading, "text": "\n".join(current_lines)})
            current_heading = m.group(2).strip()
            current_lines = [line]
        else:
            current_lines.append(line)
    if current_lines:
        sections.append({"heading": current_heading, "text": "\n".join(current_lines)})
    return sections


def load_previous_decisions(report_path):
    """从上次改动报告中解析 item 决策"""
    if not report_path or not os.path.exists(report_path):
        return []
    with open(report_path, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()

    items = []
    current_status = "pending"
    for line in content.split("\n"):
        stripped = line.strip()
        if re.match(r'^##\s*已确认', stripped):
            current_status = "confirmed"
            continue
        elif re.match(r'^##\s*已驳回', stripped):
            current_status = "rejected"
            continue
        elif re.match(r'^##\s*待确定', stripped):
            current_status = "pending"
            continue
        elif re.match(r'^##\s', stripped):
            current_status = "pending"
            continue

        m = re.match(r'.*?(R-\d{3})\s*[|｜]?\s*(.+)', stripped)
        if m:
            rest = m.group(2)
            rule_m = re.search(r'(V-\d+|RC-\d+)', rest)
            parts = re.split(r'[|｜]', rest)
            items.append({
                "id": m.group(1),
                "rule_id": rule_m.group(1) if rule_m else "",
                "location": parts[0].strip() if parts else "",
                "issue": parts[1].strip() if len(parts) > 1 else rest.strip(),
                "status": current_status,
            })
    return items


def classify_previous_items(prev_items, section_diffs):
    """根据 section 变更状态分类历史 item"""
    diff_map = {d["heading"]: d["status"] for d in section_diffs}
    for item in prev_items:
        matched = _find_section_status(item.get("location", ""), diff_map)
        if matched is None or matched == "unchanged":
            item["diff_status"] = f"carry_{item.get('status', 'pending')}"
        elif matched == "removed":
            item["diff_status"] = "fixed"
        elif matched == "modified":
            item["diff_status"] = "unfixed"
        elif matched == "added":
            item["diff_status"] = "new"
    return prev_items


def _find_section_status(location, diff_map):
    """模糊匹配 location 到 section heading"""
    if not location:
        return None
    if location in diff_map:
        return diff_map[location]
    for heading, status in diff_map.items():
        if location in heading or heading in location:
            return status
    location_words = set(re.findall(r'[\u4e00-\u9fff]{2,}', location))
    if location_words:
        for heading, status in diff_map.items():
            if location_words & set(re.findall(r'[\u4e00-\u9fff]{2,}', heading)):
                return status
    return None


def build_diff_context(section_diffs, prev_items_classified):
    """构建注入 worker prompt 的 diff 上下文"""
    lines = ["## 迭代评审上下文（本次是重新评审）\n"]
    modified = [d for d in section_diffs if d["status"] == "modified"]
    added = [d for d in section_diffs if d["status"] == "added"]
    unchanged = [d for d in section_diffs if d["status"] == "unchanged"]

    lines.append(f"PRD 变更摘要：{len(modified)} 节修改，{len(added)} 节新增，{len(unchanged)} 节未变\n")

    if modified:
        lines.append("### 已修改的章节（需重新评审）")
        for d in modified:
            lines.append(f"- {d['heading']}")
        lines.append("")

    carry_confirmed = [i for i in prev_items_classified if i.get("diff_status") == "carry_confirmed"]
    if carry_confirmed:
        lines.append("### 上次已确认不修改的问题（请勿重新报告）")
        for item in carry_confirmed:
            lines.append(f"- {item['id']} [{item.get('rule_id', '')}] {item.get('issue', '')[:60]}")
        lines.append("")

    unfixed = [i for i in prev_items_classified if i.get("diff_status") == "unfixed"]
    if unfixed:
        lines.append("### 上次发现但仍未修复的问题（请重点检查）")
        for item in unfixed:
            lines.append(f"- {item['id']} [{item.get('rule_id', '')}] {item.get('issue', '')[:60]}")
        lines.append("")

    return "\n".join(lines)