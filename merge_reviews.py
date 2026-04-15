"""
多 Reviewer 评审合并 -- 合并两个独立评审的结果，生成共识/分歧报告
"""

import json
import os
import re
from datetime import datetime
from difflib import SequenceMatcher

from logger import get_logger

log = get_logger("merge")


def load_reviewer_items(workspace, prd_name, reviewer):
    """
    从 session 或报告中加载某个 reviewer 的评审 items
    优先从 session JSONL 提取，fallback 到报告 markdown
    """
    # 尝试从 session 提取
    sessions_dir = os.path.join(workspace, "output", ".sessions")
    safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in prd_name)
    safe_reviewer = "".join(c if c.isalnum() or c in "-_" else "_" for c in reviewer)

    if os.path.isdir(sessions_dir):
        for fname in os.listdir(sessions_dir):
            if fname.endswith(".jsonl") and safe_reviewer in fname and fname.endswith(f"_{safe_name}.jsonl"):
                items = _extract_items_from_session(os.path.join(sessions_dir, fname))
                if items:
                    log.info(f"从 session 加载 {reviewer} 的 {len(items)} 条 items")
                    return items

    # Fallback: 从报告 markdown 解析
    output_dir = os.path.join(workspace, "output")
    if os.path.isdir(output_dir):
        reports = [f for f in os.listdir(output_dir) if f.startswith("PRD_改动报告_") and f.endswith(".md")]
        for fname in sorted(reports, reverse=True):
            items = _parse_items_from_report(os.path.join(output_dir, fname))
            if items:
                log.info(f"从报告加载 {len(items)} 条 items")
                return items

    return []


def _extract_items_from_session(session_path):
    """从 JSONL session 文件中提取并行评审注入的 items"""
    items = []
    with open(session_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                turn = json.loads(line)
                for msg in turn.get("messages", []):
                    content = msg.get("content", "")
                    if isinstance(content, str) and "并行评审团" in content:
                        # 从注入消息中提取 items
                        for m in re.finditer(r'(R-\d{3})\s*\|\s*(.+?)\s*\|\s*(.+?)\s*\|\s*(must|should)', content):
                            items.append({
                                "id": m.group(1),
                                "location": m.group(2).strip(),
                                "issue": m.group(3).strip(),
                                "severity": m.group(4),
                            })
            except json.JSONDecodeError:
                continue
    return items


def _parse_items_from_report(report_path):
    """从改动报告 markdown 中解析 items"""
    with open(report_path, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()

    items = []
    for line in content.split("\n"):
        m = re.match(r'.*?(R-\d{3})\s*[|｜]?\s*(.+)', line.strip())
        if m:
            rest = m.group(2)
            parts = re.split(r'[|｜]', rest)
            severity_m = re.search(r'(must|should)', rest)
            items.append({
                "id": m.group(1),
                "location": parts[0].strip() if parts else "",
                "issue": parts[1].strip() if len(parts) > 1 else rest.strip(),
                "severity": severity_m.group(1) if severity_m else "should",
            })
    return items


def merge_reviews(items_a, items_b, reviewer_a="A", reviewer_b="B"):
    """
    合并两个 reviewer 的评审结果
    返回 {"merged_items": [...], "agreement": {...}, "stats": {...}}
    """
    # 标记来源
    for item in items_a:
        item["found_by"] = [reviewer_a]
    for item in items_b:
        item["found_by"] = [reviewer_b]

    # 合并 + 匹配
    all_items = items_a + items_b
    merged = []
    used_b = set()

    for item_a in items_a:
        best_match = None
        best_sim = 0
        for j, item_b in enumerate(items_b):
            if j in used_b:
                continue
            sim = _item_similarity(item_a, item_b)
            if sim > best_sim and sim >= 0.6:
                best_match = j
                best_sim = sim

        if best_match is not None:
            # 共识：两人都发现了
            used_b.add(best_match)
            merged_item = _merge_pair(item_a, items_b[best_match], reviewer_a, reviewer_b)
            merged.append(merged_item)
        else:
            # 仅 A 发现
            merged.append(item_a)

    # 仅 B 发现
    for j, item_b in enumerate(items_b):
        if j not in used_b:
            merged.append(item_b)

    # 重新编号
    severity_rank = {"must": 0, "should": 1}
    merged.sort(key=lambda x: severity_rank.get(x.get("severity", "should"), 1))
    for i, item in enumerate(merged, 1):
        item["id"] = f"M-{i:03d}"

    # 统计
    agreed = [i for i in merged if len(i.get("found_by", [])) > 1]
    only_a = [i for i in merged if i.get("found_by") == [reviewer_a]]
    only_b = [i for i in merged if i.get("found_by") == [reviewer_b]]

    return {
        "merged_items": merged,
        "agreement": {
            "agreed": len(agreed),
            "only_a": len(only_a),
            "only_b": len(only_b),
            "total": len(merged),
            "agreement_rate": len(agreed) / max(1, len(merged)),
        },
        "stats": {
            "reviewer_a": reviewer_a,
            "reviewer_b": reviewer_b,
            "items_a": len(items_a),
            "items_b": len(items_b),
        },
    }


def _item_similarity(a, b):
    """计算两个 item 的相似度"""
    # rule_id 精确匹配加权
    if a.get("rule_id") and b.get("rule_id") and a["rule_id"] == b["rule_id"]:
        return 0.8 + 0.2 * SequenceMatcher(None, a.get("issue", ""), b.get("issue", "")).ratio()
    # issue 文本相似度
    return SequenceMatcher(None,
        f"{a.get('location', '')} {a.get('issue', '')}",
        f"{b.get('location', '')} {b.get('issue', '')}",
    ).ratio()


def _merge_pair(item_a, item_b, reviewer_a, reviewer_b):
    """合并两个匹配的 item，取更严格的严重度和更长的建议

    B4: 共识项(两人都发现)的 confidence_score 取较大值 + 共识奖励(+0.05,上限 1.0)
    """
    severity = "must" if item_a.get("severity") == "must" or item_b.get("severity") == "must" else "should"
    # 保留更长的 issue 和 suggestion
    issue = item_a.get("issue", "") if len(item_a.get("issue", "")) >= len(item_b.get("issue", "")) else item_b.get("issue", "")
    suggestion = item_a.get("suggestion", "") if len(item_a.get("suggestion", "")) >= len(item_b.get("suggestion", "")) else item_b.get("suggestion", "")

    # B4: 合并置信度 — 取较大值 + 共识奖励,上限 1.0
    conf_a = item_a.get("confidence_score", 0.0) or 0.0
    conf_b = item_b.get("confidence_score", 0.0) or 0.0
    merged_conf = min(max(conf_a, conf_b) + 0.05, 1.0)

    return {
        "id": item_a.get("id", ""),
        "rule_id": item_a.get("rule_id") or item_b.get("rule_id", ""),
        "location": item_a.get("location") or item_b.get("location", ""),
        "issue": issue,
        "suggestion": suggestion,
        "severity": severity,
        "found_by": [reviewer_a, reviewer_b],
        "evidence_type": item_a.get("evidence_type") or item_b.get("evidence_type", ""),
        "evidence_content": item_a.get("evidence_content") or item_b.get("evidence_content", ""),
        "confidence_score": round(merged_conf, 2),  # B4
    }


def _confidence_bucket(score):
    """B4: confidence_score 分档标签"""
    if score >= 0.85:
        return "高"
    if score >= 0.65:
        return "中"
    return "低"


def format_merged_report(merge_result):
    """生成合并报告 markdown"""
    lines = [
        "# PRD 评审合并报告",
        "",
        f"**审阅人**: {merge_result['stats']['reviewer_a']} + {merge_result['stats']['reviewer_b']}",
        f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        "## 合并统计",
        "",
        f"| 指标 | 数值 |",
        f"|------|------|",
        f"| {merge_result['stats']['reviewer_a']} 发现 | {merge_result['stats']['items_a']} 条 |",
        f"| {merge_result['stats']['reviewer_b']} 发现 | {merge_result['stats']['items_b']} 条 |",
        f"| 共识 | {merge_result['agreement']['agreed']} 条 |",
        f"| 仅 {merge_result['stats']['reviewer_a']} | {merge_result['agreement']['only_a']} 条 |",
        f"| 仅 {merge_result['stats']['reviewer_b']} | {merge_result['agreement']['only_b']} 条 |",
        f"| 合并后总计 | {merge_result['agreement']['total']} 条 |",
        f"| 共识率 | {merge_result['agreement']['agreement_rate']:.0%} |",
        "",
    ]

    # B4: 置信度分布
    merged_items = merge_result.get("merged_items", [])
    if merged_items:
        buckets = {"高": 0, "中": 0, "低": 0}
        total_conf = 0.0
        for it in merged_items:
            c = it.get("confidence_score", 0.0) or 0.0
            buckets[_confidence_bucket(c)] += 1
            total_conf += c
        avg = total_conf / len(merged_items) if merged_items else 0.0
        lines.extend([
            "## 置信度分布（B4）",
            "",
            f"**平均置信度**: {avg:.2f}",
            "",
            "| 档位 | 数量 | 说明 |",
            "|------|------|------|",
            f"| 高 (>=0.85) | {buckets['高']} | 共识 + A 类依据或更高 |",
            f"| 中 (0.65-0.85) | {buckets['中']} | 单人发现 + A/B 类依据 |",
            f"| 低 (<0.65) | {buckets['低']} | C 类依据或苍鹰补充项 |",
            "",
        ])

    # 分组输出
    agreed = [i for i in merge_result["merged_items"] if len(i.get("found_by", [])) > 1]
    only_a = [i for i in merge_result["merged_items"] if i.get("found_by") == [merge_result["stats"]["reviewer_a"]]]
    only_b = [i for i in merge_result["merged_items"] if i.get("found_by") == [merge_result["stats"]["reviewer_b"]]]

    if agreed:
        lines.append("## 共识项（两人均发现）")
        lines.append("")
        for item in agreed:
            lines.append(f"- **{item['id']}** [{item.get('severity','should')}] {item.get('location','')}: {item.get('issue','')}")
        lines.append("")

    if only_a:
        lines.append(f"## 仅 {merge_result['stats']['reviewer_a']} 发现")
        lines.append("")
        for item in only_a:
            lines.append(f"- **{item['id']}** [{item.get('severity','should')}] {item.get('location','')}: {item.get('issue','')}")
        lines.append("")

    if only_b:
        lines.append(f"## 仅 {merge_result['stats']['reviewer_b']} 发现")
        lines.append("")
        for item in only_b:
            lines.append(f"- **{item['id']}** [{item.get('severity','should')}] {item.get('location','')}: {item.get('issue','')}")
        lines.append("")

    return "\n".join(lines)


# CLI 入口
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="合并两个 reviewer 的评审结果")
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--prd", required=True)
    parser.add_argument("--reviewers", required=True, help="两个 reviewer 名，逗号分隔")
    args = parser.parse_args()

    reviewers = [r.strip() for r in args.reviewers.split(",")]
    if len(reviewers) != 2:
        print("需要恰好 2 个 reviewer 名")
        exit(1)

    items_a = load_reviewer_items(args.workspace, args.prd, reviewers[0])
    items_b = load_reviewer_items(args.workspace, args.prd, reviewers[1])
    print(f"{reviewers[0]}: {len(items_a)} 条, {reviewers[1]}: {len(items_b)} 条")

    result = merge_reviews(items_a, items_b, reviewers[0], reviewers[1])
    report = format_merged_report(result)

    output_path = os.path.join(args.workspace, "output", f"PRD_合并报告_{datetime.now().strftime('%Y%m%d')}.md")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"合并报告: {output_path}")
