"""
改进项工程化修复层 — 对应路线图 B1，借鉴百灵 riskbird_test_fixer

在 items 进入 build_actionable_report / 伯劳门禁之前做：
1. evidence_type 为空时从 evidence_content 自动推断
2. 调 cuckoo_scorer.verify_evidence 验证依据真实性
3. 给每个 item 打 verification_status 字段（verified/failed/unchecked）
4. 对 failed 的 A/B 类 item 降权（confidence_score *= 0.5）

配合 parallel_review._build_real_refs_section 形成完整闭环：
- 前置：Worker prompt 注入真实 rule_ids 清单，降低幻觉
- 后置：仍然造假的 evidence 被自动降权标记
"""

import re


def infer_evidence_type(ev_content):
    """从 evidence_content 推断 evidence_type

    优先级: A (wiki 引用 [[...]]) > B (规则号 RC-/V-) > C (竞品/行业/惯例)
    """
    if not ev_content:
        return ""
    if "[[" in ev_content and "]]" in ev_content:
        return "A"
    if re.search(r"(?:RC-\d+|V-\d+|BMAD[\s-]*V-\d+)", ev_content):
        return "B"
    if "竞品" in ev_content or "行业" in ev_content or "惯例" in ev_content:
        return "C"
    return ""


def fix_review_items(items, workspace):
    """对 items 列表做工程化修复 + 依据验证回写

    Args:
        items: list of review items dict
        workspace: workspace 目录路径（用于读 wiki/ 和 review-rules/）

    Returns:
        (fixed_items, stats)

        stats = {
            "total": int,
            "inferred_type": int,   # 自动推断了多少条 evidence_type
            "verified": int,         # verification_status=verified
            "failed": int,           # verification_status=failed
            "unchecked": int,        # verification_status=unchecked
            "downgraded": int,       # A/B failed 的降权数
        }
    """
    stats = {
        "total": len(items) if items else 0,
        "inferred_type": 0,
        "verified": 0,
        "failed": 0,
        "unchecked": 0,
        "downgraded": 0,
    }
    if not items:
        return items, stats

    # 避免循环 import
    from cuckoo_scorer import verify_evidence
    from cuckoo_parser import compute_confidence

    # 1. 补齐 evidence_type
    for item in items:
        ev_type = (item.get("evidence_type") or "").strip()
        ev_content = (item.get("evidence_content") or "").strip()
        if not ev_type and ev_content:
            inferred = infer_evidence_type(ev_content)
            if inferred:
                item["evidence_type"] = inferred
                stats["inferred_type"] += 1

    # 2. 调 verify_evidence 拿验证结果（返回 (verified, failed, details)）
    try:
        _, _, details = verify_evidence(items, workspace)
    except Exception:
        # verify 失败时全部标 unchecked 并返回
        for item in items:
            item["verification_status"] = "unchecked"
            stats["unchecked"] += 1
        return items, stats

    by_item_id = {d["item_id"]: d for d in details}

    # 3. 回写 verification_status + A/B 失败降权
    for item in items:
        iid = item.get("id", "")
        ev_type = (item.get("evidence_type") or "").strip().upper()
        ev_content = (item.get("evidence_content") or "").strip()

        if not ev_type and not ev_content:
            item["verification_status"] = "unchecked"
            stats["unchecked"] += 1
            continue

        detail = by_item_id.get(iid)
        if not detail:
            item["verification_status"] = "unchecked"
            stats["unchecked"] += 1
            continue

        if detail.get("verified"):
            item["verification_status"] = "verified"
            stats["verified"] += 1
        else:
            item["verification_status"] = "failed"
            item["verification_reason"] = (detail.get("reason") or "")[:200]
            stats["failed"] += 1
            # A/B 类 failed 自动降权 (confidence *= 0.5)
            if ev_type in ("A", "B"):
                base = item.get("confidence_score")
                if base is None:
                    base = compute_confidence(ev_type)
                item["confidence_score"] = round(base * 0.5, 2)
                stats["downgraded"] += 1

    return items, stats
