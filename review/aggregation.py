"""多轮投票 + 跨 worker 合并去重 + 跨章节一致性标记.

从 parallel_review.py 拆出 (2026-04-16):
- majority_vote: 多轮评审结果取交集,只保留 >= min_votes 次出现的 item
- merge_and_deduplicate: 同轮多 worker 的 item 按 location+issue 相似度去重

2026-04-23 新增 (gate 6 核心卖点): is_cross_section_contradiction 启发式,
标记"同一事实/规格在 PRD 多处矛盾"这类手工 review 最易漏的 item. 前端 Phase 3
可拎到最前栏置顶展示.

两个主函数都用 SequenceMatcher 做文本相似度,独立无状态。
parallel_review.py re-export 供外部 import 保持兼容。
"""

import re
from difflib import SequenceMatcher


# 跨章节矛盾的典型信号词 (出现在 location 或 issue 里)
_CROSS_SECTION_SIGNALS = (
    "矛盾", "不一致", "冲突", "互斥",
    "前后", "两处", "两次", "多处",
    "vs ", " vs", " vs.",
    " ≠ ", " != ",
    "分别描述为", "分别写", "一处写", "另一处写",
)


def _is_cross_section_contradiction(item: dict) -> bool:
    """启发式判断一条 item 是否在描述跨章节矛盾.

    判定标准(满足任一即可):
    1. location 含 "vs" / "两处" / "/" 分隔的多个章节号 (§X.X vs §Y.Y)
    2. issue 文本含典型信号词 ("矛盾"/"不一致"/"前后"/"冲突" 等)
    3. rule_id 是 V-06(可追溯链完整性) + V-05(信息完整性/自洽) 这类天然跨章节规则

    不处理假阴性(会漏一些隐晦矛盾), 重点是不误伤 — 明显矛盾才标, 让前端栏位
    保持高密度.
    """
    location = (item.get("location") or "")
    issue = (item.get("issue") or "")
    rule_id = (item.get("rule_id") or "").strip()

    # 规则级: V-05 / V-06 本身就是跨章节自洽/追溯
    if rule_id in ("V-05", "V-06"):
        return True

    # location 级: "§6 vs §3" / "§X / §Y" 含多个章节引用
    section_hits = len(re.findall(r"§\s*\d", location))
    if section_hits >= 2:
        return True

    # 文本级: location + issue 合并后扫信号词
    combined = location + " " + issue
    for signal in _CROSS_SECTION_SIGNALS:
        if signal in combined:
            return True

    return False


def tag_cross_section_items(items: list) -> list:
    """原地给每个 item 加 is_cross_section 布尔字段. 返回同一 list 方便链式."""
    for item in items:
        if isinstance(item, dict):
            item["is_cross_section"] = _is_cross_section_contradiction(item)
    return items


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
                loc_sim = SequenceMatcher(
                    None,
                    item.get("location", ""),
                    representative.get("location", ""),
                ).ratio()
                if loc_sim >= 0.5:
                    matched_cluster = cluster
                    break
            else:
                # rule_id 不同或缺失时，用 issue 文本相似度兜底
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

    # 标记跨章节矛盾 items (给 Phase 3 前端置顶栏位用)
    tag_cross_section_items(kept)

    return kept
