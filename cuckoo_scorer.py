"""
杜鹃 (Cuckoo) — 评分与验证模块

负责：
- 改进项与预埋 bug 匹配
- 依据真实性验证（A/B/C 三类）
- 各维度评分计算
"""

import os
import re


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
    rule_refs = re.findall(r'(RC-\d+|BMAD[\s-]V-\d+|V-\d+)', evidence_content)

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
    # 同时搜原始编号和去掉 BMAD 前缀的编号
    search_terms = [rule_ref]
    clean = re.sub(r'^BMAD[\s-]+', '', rule_ref)
    if clean != rule_ref:
        search_terms.append(clean)

    for root, dirs, files in os.walk(rules_dir):
        for f in files:
            if f.endswith((".md", ".yaml", ".yml", ".txt")):
                try:
                    fpath = os.path.join(root, f)
                    with open(fpath, "r", encoding="utf-8") as fp:
                        content = fp.read()
                    if any(term in content for term in search_terms):
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
