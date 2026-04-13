"""
杜鹃 (Cuckoo) Eval Agent — 啄木鸟评审质量评测

对抗性验证：试图推翻啄木鸟的评审结果，而非确认。
三态判定：PASS / FAIL / PARTIAL

用法：
  # 完整评测：匹配预埋 bug + 依据验证
  python cuckoo_eval.py --report output/PRD_改动报告_20260411.md --test-case eval/test_cases/劳动仲裁.json

  # 仅做依据验证（不需要测试用例）
  python cuckoo_eval.py --report output/PRD_改动报告_20260411.md --workspace ./workspace

  # 从已有报告反向生成测试用例
  python cuckoo_eval.py --generate-test-case output/PRD_改动报告_20260411.md -o eval/test_cases/劳动仲裁.json
"""

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime


# ── ASCII Art ──

CUCKOO_ART = r"""
        ,-.
       / \  `.  __..-,O
      :   \ --''_..-'.'
      |    . .-' `. '.
      :     .     .`.'
       \     `.  /  ..
        \      `.   ' .
         `,       `.   \
        ,|,`.        `-.\
       '.||  ``-....__..`
        |  |
        |__|
        /||\
       //||\\
      // || \\
   __//__||__\\__
  '--------------'
"""

# 杜鹃吐槽语
VERDICT_QUIPS = {
    "PASS": "这只啄木鸟还算靠谱。",
    "FAIL": "这只啄木鸟该回炉重造了。",
    "PARTIAL": "勉强及格，但杜鹃保留意见。",
}


# ── 数据结构 ──

# TestCase 示例结构（用 dict 即可，纯分析脚本不需要 Pydantic）
# {
#     "name": "测试名称",
#     "prd_file": "PRD 文件路径",
#     "planted_bugs": [
#         {
#             "id": "BUG-001",
#             "location": "3.7",
#             "type": "笔误" | "不一致" | "字段类型" | "缺失" | "歧义",
#             "severity": "must" | "should",
#             "description": "排序方向自相矛盾",
#             "keywords": ["排序", "从晚到早"],
#         },
#     ],
#     "non_issues": [
#         {"location": "3.3", "reason": "脱敏规则已完整覆盖"},
#     ],
# }


# ── 评审报告解析 ──

def parse_review_report(report_path):
    """从啄木鸟的改动报告中提取改进项列表

    解析 R-XXX 编号、位置、问题描述、严重度、依据
    返回结构化列表
    """
    with open(report_path, "r", encoding="utf-8") as f:
        content = f.read()

    items = []

    # 策略1：解析 YAML 风格的改进项块（啄木鸟标准输出格式）
    # 匹配 "- id: R-001" 开头的块
    yaml_pattern = re.compile(
        r'-\s*id:\s*(R-\d+)\s*\n'
        r'(?:\s+位置:\s*["\']?(.+?)["\']?\s*\n)?'
        r'(?:\s+问题:\s*["\']?(.+?)["\']?\s*\n)?'
        r'(?:\s+建议:\s*["\']?(.+?)["\']?\s*\n)?'
        r'(?:\s+严重度:\s*(must|should)\s*\n)?'
        r'(?:\s+依据类型:\s*([ABC])\s*\n)?'
        r'(?:\s+依据内容:\s*["\']?(.+?)["\']?\s*\n)?',
        re.MULTILINE
    )

    for m in yaml_pattern.finditer(content):
        items.append({
            "id": m.group(1),
            "location": (m.group(2) or "").strip(),
            "problem": (m.group(3) or "").strip(),
            "suggestion": (m.group(4) or "").strip(),
            "severity": (m.group(5) or "").strip(),
            "evidence_type": (m.group(6) or "").strip(),
            "evidence_content": (m.group(7) or "").strip(),
            "raw_text": m.group(0),
        })

    # 策略2：如果 YAML 风格没解析到，尝试 Markdown 表格或列表格式
    if not items:
        items = _parse_markdown_items(content)

    # 策略3：兜底 — 用正则捞所有 R-XXX 编号行
    if not items:
        items = _parse_loose_items(content)

    return items


def _parse_markdown_items(content):
    """解析 Markdown 格式的改进项

    支持多种格式：
    - #### R-001 ✅ 已确认
    - ### R-001
    - **R-001**
    """
    items = []

    # 按 #### R-XXX 或 ### R-XXX 分割成块
    block_pattern = re.compile(
        r'(?:#{2,4})\s*(R-\d+)\s*.*?\n(.*?)(?=\n#{2,4}\s*R-\d+|\n## |\Z)',
        re.DOTALL
    )

    for m in block_pattern.finditer(content):
        item_id = m.group(1)
        block_text = m.group(2).strip()
        # 避免重复
        if any(it["id"] == item_id for it in items):
            continue
        items.append(_extract_fields_from_block(item_id, block_text))

    return items


def _parse_loose_items(content):
    """兜底解析：找所有 R-XXX 出现的行及上下文"""
    items = []
    lines = content.split("\n")

    for i, line in enumerate(lines):
        match = re.search(r'(R-\d+)', line)
        if match:
            item_id = match.group(1)
            # 已经解析过这个 ID 就跳过
            if any(it["id"] == item_id for it in items):
                continue
            # 取当前行及后续几行作为上下文
            context = "\n".join(lines[i:min(i + 8, len(lines))])
            items.append(_extract_fields_from_block(item_id, context))

    return items


def _extract_fields_from_block(item_id, block_text):
    """从一块文本中提取改进项的各个字段

    兼容两种格式：
    - **位置**：xxx（啄木鸟 Markdown 输出）
    - 位置：xxx（YAML 风格）
    """
    def _find(field_name, text):
        """在文本中搜索字段值，兼容 **字段** 和 字段 两种格式"""
        # 先试 **字段**：格式
        m = re.search(rf'\*\*{field_name}\*\*[：:]\s*(.+?)(?:\n|$)', text)
        if m:
            return m.group(1).strip()
        # 再试 - **字段**：格式（列表项）
        m = re.search(rf'-\s*\*\*{field_name}\*\*[：:]\s*(.+?)(?:\n|$)', text)
        if m:
            return m.group(1).strip()
        # 最后试纯文本格式
        m = re.search(rf'{field_name}[：:]\s*(.+?)(?:\n|$)', text)
        if m:
            return m.group(1).strip()
        return ""

    location = _find("位置", block_text)
    problem = _find("问题", block_text)
    suggestion = _find("建议", block_text)
    evidence_content = _find("依据", block_text) or _find("依据内容", block_text)

    # 严重度
    sev_match = re.search(r'(?:\*\*)?严重度(?:\*\*)?[：:]\s*(must|should)', block_text)
    severity = sev_match.group(1) if sev_match else ""

    # 依据类型
    evi_type_match = re.search(r'(?:\*\*)?依据类型(?:\*\*)?[：:]\s*([ABC])', block_text)
    evidence_type = evi_type_match.group(1) if evi_type_match else ""

    # 如果没提取到依据类型，从依据内容推断
    if not evidence_type and evidence_content:
        if "[[" in evidence_content:
            evidence_type = "A"
        elif re.search(r'(?:RC-|BMAD|V-)\d+', evidence_content):
            evidence_type = "B"
        elif "竞品" in evidence_content or "行业" in evidence_content:
            evidence_type = "C"

    # 如果没提取到问题描述，用整块文本的第一行
    if not problem:
        first_line = block_text.split("\n")[0].strip()
        # 去掉 ID 前缀
        first_line = re.sub(r'^R-\d+\s*[：:．.]?\s*', '', first_line)
        problem = first_line[:200] if first_line else ""

    return {
        "id": item_id,
        "location": location,
        "problem": problem,
        "suggestion": suggestion,
        "severity": severity,
        "evidence_type": evidence_type,
        "evidence_content": evidence_content,
        "raw_text": block_text[:500],
    }


# ── 匹配引擎 ──

def match_items_to_bugs(review_items, planted_bugs):
    """把啄木鸟发现的改进项和预埋 bug 做匹配

    匹配逻辑：location 相似 + keywords 命中
    返回：{"hits": [...], "misses": [...], "false_positives": [...]}
    """
    hits = []          # 命中：改进项匹配到了预埋 bug
    misses = []        # 漏报：预埋 bug 没被发现
    false_positives = []  # 误报：改进项没对应任何预埋 bug

    matched_bug_ids = set()
    matched_item_ids = set()

    # 第一轮：location 精确匹配 + 关键词验证
    for bug in planted_bugs:
        best_match = None
        best_score = 0

        for item in review_items:
            score = _calc_match_score(item, bug)
            if score > best_score:
                best_score = score
                best_match = item

        if best_match and best_score >= 2 and best_match["id"] not in matched_item_ids:
            hits.append({
                "bug": bug,
                "item": best_match,
                "score": best_score,
                "location_match": _location_similar(best_match["location"], bug["location"]),
                "keyword_hits": _count_keyword_hits(best_match, bug["keywords"]),
                "severity_match": best_match.get("severity", "") == bug["severity"],
            })
            matched_bug_ids.add(bug["id"])
            matched_item_ids.add(best_match["id"])
        else:
            misses.append(bug)

    # 未匹配到任何 bug 的改进项 → 可能是误报，也可能是啄木鸟发现的额外问题
    # 先检查是否命中了 non_issues（后面在 evaluate 中处理）
    for item in review_items:
        if item["id"] not in matched_item_ids:
            false_positives.append(item)

    return {
        "hits": hits,
        "misses": misses,
        "false_positives": false_positives,
    }


def _calc_match_score(item, bug):
    """计算改进项与预埋 bug 的匹配分数"""
    score = 0

    # location 匹配（最重要，+3 分）
    if _location_similar(item["location"], bug["location"]):
        score += 3

    # 关键词命中（每个 +1 分）
    keyword_hits = _count_keyword_hits(item, bug["keywords"])
    score += keyword_hits

    # 类型相关性（+1 分）
    bug_type = bug.get("type", "")
    item_text = (item.get("problem", "") + item.get("suggestion", "")).lower()
    type_keywords = {
        "笔误": ["笔误", "拼写", "错字", "typo"],
        "不一致": ["不一致", "矛盾", "冲突", "前后"],
        "字段类型": ["字段", "类型", "格式", "数据类型"],
        "缺失": ["缺失", "遗漏", "缺少", "未定义", "未说明"],
        "歧义": ["歧义", "模糊", "不明确", "二义"],
    }
    if bug_type in type_keywords:
        for kw in type_keywords[bug_type]:
            if kw in item_text:
                score += 1
                break

    return score


def _location_similar(item_loc, bug_loc):
    """判断两个 PRD 位置是否相似

    支持格式：
    - "3.7" vs "3.7" → 精确匹配
    - "第 3.7 节" vs "3.7" → 包含匹配
    - "3.7.1" vs "3.7" → 上级匹配
    """
    if not item_loc or not bug_loc:
        return False

    # 提取数字章节号
    item_nums = re.findall(r'\d+(?:\.\d+)*', item_loc)
    bug_nums = re.findall(r'\d+(?:\.\d+)*', bug_loc)

    if not item_nums or not bug_nums:
        return False

    for i_num in item_nums:
        for b_num in bug_nums:
            # 精确匹配
            if i_num == b_num:
                return True
            # 上下级匹配
            if i_num.startswith(b_num + ".") or b_num.startswith(i_num + "."):
                return True

    return False


def _count_keyword_hits(item, keywords):
    """计算改进项中命中的关键词数量"""
    if not keywords:
        return 0

    # 拼接所有文本字段做匹配
    text = " ".join([
        item.get("problem", ""),
        item.get("suggestion", ""),
        item.get("evidence_content", ""),
        item.get("raw_text", ""),
    ]).lower()

    return sum(1 for kw in keywords if kw.lower() in text)


# ── 依据验证 ──

def verify_evidence(review_items, workspace):
    """验证啄木鸟给出的依据是否真实存在

    A 类依据：检查 wiki/ 中页面是否存在
    B 类依据：检查规则编号是否在 review-rules/ 中
    C 类依据：是否已标记"待确定"

    返回 (verified_count, failed_count, details)
    """
    wiki_dir = os.path.join(workspace, "wiki")
    rules_dir = os.path.join(workspace, "review-rules")

    details = []
    verified = 0
    failed = 0

    for item in review_items:
        ev_type = item.get("evidence_type", "")
        ev_content = item.get("evidence_content", "")

        if not ev_type and not ev_content:
            # 无依据 — 直接判定为失败
            details.append({
                "item_id": item["id"],
                "evidence_type": "无",
                "evidence_content": "",
                "verified": False,
                "reason": "改进项未附带任何依据",
            })
            failed += 1
            continue

        if ev_type == "A":
            ok, reason = _verify_type_a(ev_content, wiki_dir)
        elif ev_type == "B":
            ok, reason = _verify_type_b(ev_content, rules_dir)
        elif ev_type == "C":
            ok, reason = _verify_type_c(item)
        else:
            # 未标注类型，尝试自动推断
            ok, reason = _verify_unknown_type(ev_content, wiki_dir, rules_dir, item)

        details.append({
            "item_id": item["id"],
            "evidence_type": ev_type or "未标注",
            "evidence_content": ev_content[:200],
            "verified": ok,
            "reason": reason,
        })

        if ok:
            verified += 1
        else:
            failed += 1

    return verified, failed, details


def _verify_type_a(evidence_content, wiki_dir):
    """A 类依据验证：wiki/ 中对应页面是否存在"""
    if not os.path.isdir(wiki_dir):
        return False, f"wiki/ 目录不存在: {wiki_dir}"

    # 提取 [[页面名]] 引用
    wiki_refs = re.findall(r'\[\[(.+?)\]\]', evidence_content)

    if not wiki_refs:
        # 没有明确的 wiki 引用，但标注为 A 类 — 尝试模糊匹配
        return False, "A 类依据未包含 [[页面名]] 引用"

    # 检查每个引用的页面是否存在
    missing = []
    for ref in wiki_refs:
        found = False
        for f in os.listdir(wiki_dir):
            if f.endswith(".md"):
                name_no_ext = f[:-3]
                if name_no_ext == ref or ref in name_no_ext or name_no_ext in ref:
                    found = True
                    break
        if not found:
            missing.append(ref)

    if missing:
        return False, f"wiki 中未找到页面: {', '.join(missing)}"
    return True, f"wiki 页面存在: {', '.join(wiki_refs)}"


def _verify_type_b(evidence_content, rules_dir):
    """B 类依据验证：规则编号是否在 review-rules/ 中"""
    # 提取规则编号（RC-XXX, V-XX, BMAD 等）
    rule_refs = re.findall(r'(RC-\d+|V-\d+|BMAD[\s-]\w+)', evidence_content)

    if not rule_refs:
        return False, "B 类依据未包含有效的规则编号（RC-XXX 或 V-XX）"

    if not os.path.isdir(rules_dir):
        # 规则目录不存在，但引用了规则编号 — 视为无法验证
        return False, f"review-rules/ 目录不存在: {rules_dir}"

    # 在规则文件中搜索编号
    found_rules = set()
    missing_rules = set()

    for rule_ref in rule_refs:
        found = _search_rule_in_dir(rule_ref, rules_dir)
        if found:
            found_rules.add(rule_ref)
        else:
            missing_rules.add(rule_ref)

    if missing_rules:
        return False, f"规则目录中未找到: {', '.join(missing_rules)}"
    return True, f"规则编号验证通过: {', '.join(found_rules)}"


def _search_rule_in_dir(rule_ref, rules_dir):
    """在规则目录中递归搜索规则编号"""
    for root, dirs, files in os.walk(rules_dir):
        for f in files:
            if f.endswith((".md", ".yaml", ".yml", ".txt")):
                try:
                    fpath = os.path.join(root, f)
                    with open(fpath, "r", encoding="utf-8") as fp:
                        if rule_ref in fp.read():
                            return True
                except (UnicodeDecodeError, IOError):
                    continue
    return False


def _verify_type_c(item):
    """C 类依据验证：是否已标记为"待确定"（应该标记才算合规）"""
    raw = item.get("raw_text", "") + item.get("evidence_content", "")
    markers = ["待确定", "待确认", "⚠️", "外部参考", "待验证"]

    if any(m in raw for m in markers):
        return True, "C 类依据已正确标记为待确定"
    return False, "C 类依据未标记为待确定（违反铁律：C 类必须标注⚠️）"


def _verify_unknown_type(evidence_content, wiki_dir, rules_dir, item):
    """未标注依据类型，尝试自动推断并验证"""
    # 有 [[]] 引用 → 可能是 A 类
    if "[[" in evidence_content:
        ok, reason = _verify_type_a(evidence_content, wiki_dir)
        return ok, f"[自动推断为 A 类] {reason}"

    # 有 RC-/V- 编号 → 可能是 B 类
    if re.search(r'RC-\d+|V-\d+', evidence_content):
        ok, reason = _verify_type_b(evidence_content, rules_dir)
        return ok, f"[自动推断为 B 类] {reason}"

    return False, "依据类型未标注，无法验证"


# ── 评分计算 ──

def calculate_scores(matches, evidence_results, review_items):
    """计算各维度评分

    返回：
    - recall: 命中 / (命中 + 漏报)
    - precision: 真阳 / (真阳 + 假阳)
    - location_accuracy: 位置匹配准确数 / 命中数
    - evidence_reliability: 依据验证通过数 / 总依据数
    - severity_accuracy: 严重度分级正确数 / 命中数
    - format_completeness: 字段完整的改进项 / 总改进项
    - overall_verdict: PASS(>80%) / PARTIAL(50-80%) / FAIL(<50%)
    """
    hits = matches["hits"]
    misses = matches["misses"]
    false_positives = matches["false_positives"]
    verified_count, failed_count, _ = evidence_results

    total_bugs = len(hits) + len(misses)
    total_items = len(review_items)

    # 召回率
    recall = len(hits) / total_bugs if total_bugs > 0 else 0.0

    # 精确率（排除与 non_issues 匹配的误报）
    true_positives = len(hits)
    false_positive_count = len(false_positives)
    precision = true_positives / (true_positives + false_positive_count) if (true_positives + false_positive_count) > 0 else 0.0

    # 位置匹配准确率
    location_correct = sum(1 for h in hits if h["location_match"])
    location_accuracy = location_correct / len(hits) if hits else 0.0

    # 依据可靠度
    total_evidence = verified_count + failed_count
    evidence_reliability = verified_count / total_evidence if total_evidence > 0 else 0.0

    # 严重度分级准确率
    severity_correct = sum(1 for h in hits if h["severity_match"])
    severity_accuracy = severity_correct / len(hits) if hits else 0.0

    # 格式完整度（检查必填字段齐全的改进项占比）
    required_fields = ["id", "location", "problem", "severity", "evidence_type", "evidence_content"]
    complete_count = 0
    for item in review_items:
        if all(item.get(f, "").strip() for f in required_fields):
            complete_count += 1
    format_completeness = complete_count / total_items if total_items > 0 else 0.0

    # 综合得分（加权平均）
    weights = {
        "recall": 0.30,          # 召回最重要 — 漏报比误报更危险
        "precision": 0.20,
        "location_accuracy": 0.10,
        "evidence_reliability": 0.20,
        "severity_accuracy": 0.10,
        "format_completeness": 0.10,
    }
    overall = (
        recall * weights["recall"]
        + precision * weights["precision"]
        + location_accuracy * weights["location_accuracy"]
        + evidence_reliability * weights["evidence_reliability"]
        + severity_accuracy * weights["severity_accuracy"]
        + format_completeness * weights["format_completeness"]
    )

    if overall >= 0.80:
        verdict = "PASS"
    elif overall >= 0.50:
        verdict = "PARTIAL"
    else:
        verdict = "FAIL"

    return {
        "recall": recall,
        "precision": precision,
        "location_accuracy": location_accuracy,
        "evidence_reliability": evidence_reliability,
        "severity_accuracy": severity_accuracy,
        "format_completeness": format_completeness,
        "overall_score": overall,
        "overall_verdict": verdict,
        "detail": {
            "hit_count": len(hits),
            "miss_count": len(misses),
            "false_positive_count": false_positive_count,
            "total_bugs": total_bugs,
            "total_items": total_items,
            "verified_evidence": verified_count,
            "failed_evidence": failed_count,
        },
    }


# ── Eval 报告生成 ──

def generate_eval_report(test_case, scores, matches, evidence_results):
    """生成 Markdown 格式的评测报告"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    verdict = scores["overall_verdict"]
    detail = scores["detail"]
    _, _, ev_details = evidence_results

    lines = []

    # 杜鹃登场
    lines.append(CUCKOO_ART)
    lines.append(f"# 杜鹃评测报告")
    lines.append("")
    lines.append(f"> VERDICT: **{verdict}** -- {VERDICT_QUIPS[verdict]}")
    lines.append("")

    # 测试概览
    lines.append("## 测试概览")
    lines.append("")
    lines.append(f"- 测试名称: {test_case.get('name', '未命名')}")
    lines.append(f"- PRD 文件: {test_case.get('prd_file', '未指定')}")
    lines.append(f"- 预埋 bug 数: {detail['total_bugs']}")
    lines.append(f"- 啄木鸟改进项数: {detail['total_items']}")
    lines.append(f"- 评测时间: {now}")
    lines.append("")

    # 各维度得分
    lines.append("## 各维度得分")
    lines.append("")
    lines.append("| 维度 | 得分 | 权重 | 说明 |")
    lines.append("|------|------|------|------|")
    lines.append(f"| 召回率 (Recall) | {scores['recall']:.1%} | 30% | 命中 {detail['hit_count']} / 预埋 {detail['total_bugs']} |")
    lines.append(f"| 精确率 (Precision) | {scores['precision']:.1%} | 20% | 真阳 {detail['hit_count']} / 总发现 {detail['total_items']} |")
    lines.append(f"| 位置准确率 | {scores['location_accuracy']:.1%} | 10% | 位置匹配正确数 / 命中数 |")
    lines.append(f"| 依据可靠度 | {scores['evidence_reliability']:.1%} | 20% | 验证通过 {detail['verified_evidence']} / 总依据 {detail['verified_evidence'] + detail['failed_evidence']} |")
    lines.append(f"| 严重度准确率 | {scores['severity_accuracy']:.1%} | 10% | 分级正确数 / 命中数 |")
    lines.append(f"| 格式完整度 | {scores['format_completeness']:.1%} | 10% | 字段齐全的改进项 / 总改进项 |")
    lines.append(f"| **综合得分** | **{scores['overall_score']:.1%}** | - | 加权平均 |")
    lines.append("")

    # 命中明细
    lines.append("## 命中明细")
    lines.append("")
    if matches["hits"]:
        for h in matches["hits"]:
            bug = h["bug"]
            item = h["item"]
            lines.append(f"### {bug['id']} -> {item['id']}")
            lines.append(f"- Bug: [{bug['type']}] {bug['description']}")
            lines.append(f"- Bug 位置: {bug['location']}")
            lines.append(f"- 改进项: {item['problem']}")
            lines.append(f"- 改进项位置: {item['location']}")
            lines.append(f"- 匹配分: {h['score']} | 位置匹配: {'Y' if h['location_match'] else 'N'} | 关键词命中: {h['keyword_hits']} | 严重度: {'Y' if h['severity_match'] else 'N'}")
            lines.append("")
    else:
        lines.append("（无命中）")
        lines.append("")

    # 漏报明细
    lines.append("## 漏报明细")
    lines.append("")
    if matches["misses"]:
        for bug in matches["misses"]:
            lines.append(f"### {bug['id']} -- 漏报!")
            lines.append(f"- 类型: {bug['type']}")
            lines.append(f"- 位置: {bug['location']}")
            lines.append(f"- 严重度: {bug['severity']}")
            lines.append(f"- 描述: {bug['description']}")
            lines.append(f"- 关键词: {', '.join(bug.get('keywords', []))}")
            lines.append("")
    else:
        lines.append("（无漏报）")
        lines.append("")

    # 误报明细
    lines.append("## 误报 / 额外发现")
    lines.append("")
    if matches["false_positives"]:
        for item in matches["false_positives"]:
            lines.append(f"### {item['id']} -- 未匹配预埋 bug")
            lines.append(f"- 位置: {item['location']}")
            lines.append(f"- 问题: {item['problem']}")
            lines.append(f"- 严重度: {item.get('severity', '未标注')}")
            lines.append(f"- 依据: [{item.get('evidence_type', '?')}] {item.get('evidence_content', '无')[:100]}")
            lines.append("")
    else:
        lines.append("（无误报）")
        lines.append("")

    # 依据验证明细
    lines.append("## 依据验证明细")
    lines.append("")
    if ev_details:
        lines.append("| 改进项 | 依据类型 | 验证结果 | 说明 |")
        lines.append("|--------|----------|----------|------|")
        for d in ev_details:
            status = "PASS" if d["verified"] else "FAIL"
            lines.append(f"| {d['item_id']} | {d['evidence_type']} | {status} | {d['reason'][:80]} |")
        lines.append("")
    else:
        lines.append("（无依据需要验证）")
        lines.append("")

    # 最终判定
    lines.append("---")
    lines.append("")
    lines.append(f"## VERDICT: {verdict}")
    lines.append("")
    lines.append(f"> {VERDICT_QUIPS[verdict]}")
    lines.append("")

    return "\n".join(lines)


def generate_evidence_only_report(evidence_results, review_items):
    """生成仅包含依据验证的报告（不需要测试用例时使用）"""
    verified, failed, details = evidence_results
    total = verified + failed
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    reliability = verified / total if total > 0 else 0.0
    if reliability >= 0.80:
        verdict = "PASS"
    elif reliability >= 0.50:
        verdict = "PARTIAL"
    else:
        verdict = "FAIL"

    lines = []
    lines.append(CUCKOO_ART)
    lines.append("# 杜鹃依据验证报告")
    lines.append("")
    lines.append(f"> VERDICT: **{verdict}** -- {VERDICT_QUIPS[verdict]}")
    lines.append("")
    lines.append("## 概览")
    lines.append("")
    lines.append(f"- 改进项总数: {len(review_items)}")
    lines.append(f"- 依据验证通过: {verified}")
    lines.append(f"- 依据验证失败: {failed}")
    lines.append(f"- 依据可靠度: {reliability:.1%}")
    lines.append(f"- 评测时间: {now}")
    lines.append("")

    lines.append("## 验证明细")
    lines.append("")
    if details:
        lines.append("| 改进项 | 依据类型 | 验证结果 | 说明 |")
        lines.append("|--------|----------|----------|------|")
        for d in details:
            status = "PASS" if d["verified"] else "FAIL"
            lines.append(f"| {d['item_id']} | {d['evidence_type']} | {status} | {d['reason'][:80]} |")
        lines.append("")

        # 失败项详情
        failed_items = [d for d in details if not d["verified"]]
        if failed_items:
            lines.append("## 失败项详情")
            lines.append("")
            for d in failed_items:
                lines.append(f"### {d['item_id']}")
                lines.append(f"- 依据类型: {d['evidence_type']}")
                lines.append(f"- 依据内容: {d['evidence_content']}")
                lines.append(f"- 失败原因: {d['reason']}")
                lines.append("")

    lines.append("---")
    lines.append("")
    lines.append(f"## VERDICT: {verdict}")
    lines.append("")
    lines.append(f"> {VERDICT_QUIPS[verdict]}")
    lines.append("")

    return "\n".join(lines)


# ── 预设测试用例生成器 ──

def generate_test_case_from_report(report_path):
    """从已有的评审报告反向生成测试用例

    把当前改进项作为"预期发现"，方便快速建立 baseline
    """
    items = parse_review_report(report_path)

    if not items:
        print(f"WARNING: 未从报告中解析到任何改进项: {report_path}")
        return None

    # 从报告文件名推断 PRD 名称
    basename = os.path.basename(report_path)
    prd_name = re.sub(r'PRD_改动报告_\d+\.md', '', basename).strip("_")
    if not prd_name:
        prd_name = basename

    planted_bugs = []
    for i, item in enumerate(items, 1):
        # 从改进项的文本中提取关键词
        text = item.get("problem", "") + " " + item.get("suggestion", "")
        # 取最长的名词短语作为关键词（简单策略：按标点分段取前几个词）
        words = re.findall(r'[\u4e00-\u9fa5a-zA-Z]+', text)
        keywords = list(set(words[:5]))  # 取前 5 个不重复的词

        # 推断 bug 类型
        bug_type = _infer_bug_type(text)

        planted_bugs.append({
            "id": f"BUG-{i:03d}",
            "location": item.get("location", ""),
            "type": bug_type,
            "severity": item.get("severity", "should"),
            "description": item.get("problem", "")[:100],
            "keywords": keywords,
        })

    test_case = {
        "name": f"{prd_name} baseline 测试",
        "prd_file": "",  # 需要手动填入
        "generated_from": report_path,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "planted_bugs": planted_bugs,
        "non_issues": [],  # 需要手动填入
    }

    return test_case


def _infer_bug_type(text):
    """从问题描述推断 bug 类型"""
    type_indicators = {
        "笔误": ["笔误", "拼写", "错字", "打错", "typo"],
        "不一致": ["不一致", "矛盾", "冲突", "前后不同", "前后矛盾"],
        "字段类型": ["字段", "类型不匹配", "数据类型", "格式错误"],
        "缺失": ["缺失", "遗漏", "缺少", "未定义", "未说明", "没有提及"],
        "歧义": ["歧义", "模糊", "不明确", "可能有多种理解"],
    }
    text_lower = text.lower()
    for bug_type, indicators in type_indicators.items():
        if any(ind in text_lower for ind in indicators):
            return bug_type
    return "歧义"  # 默认


# ── CLI 入口 ──

def main():
    parser = argparse.ArgumentParser(
        description="杜鹃 (Cuckoo) — 啄木鸟 PRD 评审质量评测",
        epilog=(
            "示例:\n"
            "  python cuckoo_eval.py --report output/PRD_改动报告_20260411.md --test-case eval/test_cases/劳动仲裁.json\n"
            "  python cuckoo_eval.py --report output/PRD_改动报告_20260411.md --workspace ./workspace\n"
            "  python cuckoo_eval.py --generate-test-case output/PRD_改动报告_20260411.md -o eval/test_cases/劳动仲裁.json\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument("--report", help="啄木鸟评审报告路径")
    parser.add_argument("--test-case", help="测试用例 JSON 文件路径")
    parser.add_argument("--workspace", default="./workspace", help="工作目录路径（默认 ./workspace）")
    parser.add_argument("--generate-test-case", metavar="REPORT", help="从评审报告反向生成测试用例")
    parser.add_argument("-o", "--output", help="输出文件路径（报告或测试用例）")

    args = parser.parse_args()

    # 模式1：从报告生成测试用例
    if args.generate_test_case:
        report_path = os.path.abspath(args.generate_test_case)
        if not os.path.isfile(report_path):
            print(f"ERROR: 报告文件不存在: {report_path}")
            sys.exit(1)

        print(CUCKOO_ART)
        print("杜鹃正在从评审报告反向生成测试用例...\n")

        test_case = generate_test_case_from_report(report_path)
        if not test_case:
            sys.exit(1)

        if args.output:
            out_path = os.path.abspath(args.output)
            os.makedirs(os.path.dirname(out_path), exist_ok=True)
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(test_case, f, ensure_ascii=False, indent=2)
            print(f"测试用例已写入: {out_path}")
            print(f"预埋 bug 数: {len(test_case['planted_bugs'])}")
            print("\n注意：请手动检查并补充 prd_file 和 non_issues 字段")
        else:
            print(json.dumps(test_case, ensure_ascii=False, indent=2))

        sys.exit(0)

    # 后续模式都需要 --report
    if not args.report:
        parser.print_help()
        sys.exit(1)

    report_path = os.path.abspath(args.report)
    if not os.path.isfile(report_path):
        print(f"ERROR: 报告文件不存在: {report_path}")
        sys.exit(1)

    workspace = os.path.abspath(args.workspace)

    print(CUCKOO_ART)
    print("杜鹃开始评测...\n")

    # 解析评审报告
    review_items = parse_review_report(report_path)
    print(f"从报告中解析到 {len(review_items)} 条改进项")

    if not review_items:
        print("WARNING: 未解析到任何改进项，杜鹃无事可做")
        sys.exit(0)

    # 依据验证（不管有没有测试用例都做）
    print("正在验证依据...")
    evidence_results = verify_evidence(review_items, workspace)
    verified, failed, _ = evidence_results
    print(f"依据验证: 通过 {verified}, 失败 {failed}")

    # 模式2：完整评测（有测试用例）
    if args.test_case:
        tc_path = os.path.abspath(args.test_case)
        if not os.path.isfile(tc_path):
            print(f"ERROR: 测试用例文件不存在: {tc_path}")
            sys.exit(1)

        with open(tc_path, "r", encoding="utf-8") as f:
            test_case = json.load(f)

        planted_bugs = test_case.get("planted_bugs", [])
        print(f"测试用例: {test_case.get('name', '未命名')}")
        print(f"预埋 bug 数: {len(planted_bugs)}")

        # 匹配
        print("正在匹配改进项与预埋 bug...")
        matches = match_items_to_bugs(review_items, planted_bugs)
        print(f"命中: {len(matches['hits'])}, 漏报: {len(matches['misses'])}, 误报/额外: {len(matches['false_positives'])}")

        # 评分
        scores = calculate_scores(matches, evidence_results, review_items)
        print(f"\n综合得分: {scores['overall_score']:.1%}")
        print(f"VERDICT: {scores['overall_verdict']} -- {VERDICT_QUIPS[scores['overall_verdict']]}\n")

        # 生成报告
        report = generate_eval_report(test_case, scores, matches, evidence_results)

    # 模式3：仅依据验证（无测试用例）
    else:
        print("\n未提供测试用例，仅执行依据验证\n")
        report = generate_evidence_only_report(evidence_results, review_items)

    # 输出报告
    if args.output:
        out_path = os.path.abspath(args.output)
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"评测报告已写入: {out_path}")
    else:
        print(report)


if __name__ == "__main__":
    main()
