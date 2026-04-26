"""评审漏斗 telemetry 辅助 — 纯函数, 无 I/O (T3 2026-04-24).

spec: docs/review-funnel-schema.md

5 层漏斗: worker_raw → after_dedup → after_evidence_verify → after_goshawk → after_pm_decision

本模块只做 "从 parallel_review / verify_evidence / apply_advisor_result / Phase 3 decisions
这些中间结果算 funnel event payload" 的工作, 不做 I/O 不做 emit.
调用方 (api/routes/review.py / run_session.py) 把结果塞给 evt.append / emitter.emit.

设计动机:
- Emit 点散落在 API + CLI 两条 flow, 逻辑统一 → 抽出纯函数共用
- 纯函数好 mock / 好断言, 不用跑完整评审就能测所有 edge case
- Emit 失败不阻塞评审: 调用方用 try/except 包, 本模块不关心 resilience
"""
from __future__ import annotations

from collections import Counter


def compute_worker_raw_stage(workers):
    """从 parallel_review 返回的 workers 列表算 N0 stage payload.

    Args:
        workers: list of worker result dict, 每个含 "dimension" + "items" + 可选 "telemetry"

    Returns:
        {
            "count": 所有 worker items 总数,
            "by_dimension": {dim: count, ...},
            "empty_retry_dimensions": [触发空提交重试的维度],
        }
    """
    by_dim: dict[str, int] = {}
    empty_retry: list[str] = []
    for w in workers:
        dim = w.get("dimension", "unknown")
        by_dim[dim] = len(w.get("items", []))
        tele = w.get("telemetry") or {}
        if tele.get("empty_retry_used"):
            empty_retry.append(dim)
    return {
        "count": sum(by_dim.values()),
        "by_dimension": by_dim,
        "empty_retry_dimensions": empty_retry,
    }


def compute_dedup_stage(worker_raw_count, merged_items):
    """N0 → N1 (merge_and_deduplicate 之后) payload."""
    return {
        "count": len(merged_items),
        "dropped_count": max(0, worker_raw_count - len(merged_items)),
    }


def compute_evidence_verify_stage(v_sum, wiki_telemetry):
    """verify_evidence 后 N2 stage payload. v_sum 来自 summarize_verification, 扩展后含 downgraded_*."""
    return {
        "count": v_sum.get("verified", 0),   # verified (含 caveat) 算通过
        "retracted_count": v_sum.get("retracted", 0),
        "downgraded_count": v_sum.get("downgraded", 0),
        "retracted_by_reason": v_sum.get("retracted_by_reason_code", {}),
        "downgraded_by_reason": v_sum.get("downgraded_by_reason_code", {}),
        "wiki_mode": wiki_telemetry.get("mode", "unknown"),
        "authority_distribution": wiki_telemetry.get("authority_distribution", {}),
    }


def compute_goshawk_stage(post_items, goshawk_result):
    """apply_advisor_result 返回的 items + goshawk_result → N3 stage payload.

    post_items 是 apply_advisor_result 过滤 REMOVED_BY_ADVISOR 后的列表
    (含 MERGED_BY_ADVISOR 的 facet, P0-1 commit 213ca4c 起保留).

    removed_count 从 goshawk_result.flagged_as_false_positive 的 "移除" 建议数算,
    因为这些 item 已被 apply_advisor_result 过滤掉不在 post_items 里.
    """
    fps = goshawk_result.get("flagged_as_false_positive", []) or []
    # 2026-04-26 P1-G: removed 关键词扩展 — 模型可能写 "移除"/"删除"/"删掉"
    _REMOVED_KEYWORDS = ("移除", "删除", "删掉")
    removed_count = sum(
        1 for fp in fps
        if any(kw in (fp.get("recommendation", "") or "") for kw in _REMOVED_KEYWORDS)
    )

    # 2026-04-26 P0-B: 用 explicit set 避免 double-count.
    # 老逻辑用减法 (kept = total - merged - added - restored) 假设三类互斥,
    # 但 RESTORED_BY_SANITY_CHECK 的 item 可能也带 provenance=meta_added (苍鹰补充被误标后又复活),
    # 减法会双扣. 改为 set 排他归类: 一个 item 只属于一个桶.
    merged_ids = {i["id"] for i in post_items if i.get("status") == "MERGED_BY_ADVISOR"}
    fp_restored_ids = {i["id"] for i in post_items if i.get("status") == "RESTORED_BY_SANITY_CHECK"}
    added_ids = {
        i["id"] for i in post_items
        if i.get("provenance") == "meta_added" or i.get("source") == "苍鹰补充"
    }
    # 优先级: restored > merged > added > kept (避免重叠 item 被多桶统计)
    classified_ids = merged_ids | fp_restored_ids | added_ids
    kept_count = sum(1 for i in post_items if i["id"] not in classified_ids)
    merged_to_facet = len(merged_ids)
    added = len(added_ids - merged_ids - fp_restored_ids)  # 扣除已归 merged/restored 的
    fp_restored = len(fp_restored_ids)

    facet_links = [
        {"facet": i["id"], "primary": i.get("facet_of", "")}
        for i in post_items if i.get("facet_of")
    ]

    return {
        "count": len(post_items),
        "delta_breakdown": {
            "removed": removed_count,
            "merged_to_facet": merged_to_facet,
            "added": added,
            "false_positive_restored": fp_restored,
            "kept_intact": kept_count,
        },
        "facet_links": facet_links,
    }


def compute_pm_decision_stage(decisions):
    """Phase 3 decisions dict → N4 stage payload.

    decisions: {item_id: {"action": accept|reject|edit, "reason_category": ..., ...}}
    """
    accepted = sum(1 for d in decisions.values() if d.get("action") == "accept")
    rejected = sum(1 for d in decisions.values() if d.get("action") == "reject")
    edited = sum(1 for d in decisions.values() if d.get("action") == "edit")
    pending = sum(1 for d in decisions.values()
                  if d.get("action") not in ("accept", "reject", "edit"))

    reject_reasons: Counter[str] = Counter()
    for d in decisions.values():
        if d.get("action") == "reject":
            reject_reasons[d.get("reason_category", "model_noise")] += 1

    return {
        "total_items": len(decisions),
        "accepted": accepted,
        "rejected": rejected,
        "edited": edited,
        "pending": pending,
        "rejected_by_reason": dict(reject_reasons),
    }


# 可疑信号阈值 — spec docs/review-funnel-schema.md 第二节 funnel_summary
_DEDUP_RETENTION_LOW = 0.6
_EVIDENCE_VERIFY_RETENTION_LOW = 0.6
_GOSHAWK_RETENTION_LOW = 0.7
_PM_RETENTION_LOW = 0.3


def compute_funnel_summary(stages):
    """各 stage count → funnel_summary with retention + suspicious_flags.

    Args:
        stages: {
            "N0_worker_raw": int,
            "N1_after_dedup": int,
            "N2_after_evidence_verify": int,
            "N3_after_goshawk": int,
            "N4_after_pm_decision": int | None,   # CLI 没 Phase 3 → None
        }
    """
    n0 = stages.get("N0_worker_raw", 0)
    n1 = stages.get("N1_after_dedup", 0)
    n2 = stages.get("N2_after_evidence_verify", 0)
    n3 = stages.get("N3_after_goshawk", 0)
    n4 = stages.get("N4_after_pm_decision")

    def _safe_div(a, b):
        return round(a / b, 3) if b > 0 else 1.0

    retention = {
        "dedup_retention": _safe_div(n1, n0),
        "evidence_verify_retention": _safe_div(n2, n1),
        "goshawk_retention": _safe_div(n3, n2),
    }
    if n4 is not None:
        retention["pm_retention"] = _safe_div(n4, n3)

    flags = []
    if n0 > 0 and retention["dedup_retention"] < _DEDUP_RETENTION_LOW:
        flags.append(f"dedup_retention_low_{retention['dedup_retention']}")
    if n1 > 0 and retention["evidence_verify_retention"] < _EVIDENCE_VERIFY_RETENTION_LOW:
        flags.append(f"evidence_verify_retention_low_{retention['evidence_verify_retention']}")
    if n2 > 0 and retention["goshawk_retention"] < _GOSHAWK_RETENTION_LOW:
        flags.append(f"goshawk_retention_low_{retention['goshawk_retention']}")
    if n4 is not None and n3 > 0 and retention.get("pm_retention", 1.0) < _PM_RETENTION_LOW:
        flags.append(f"pm_retention_low_{retention['pm_retention']}")

    return {
        "stages": stages,
        "stage_retention": retention,
        "suspicious_flags": flags,
    }


def get_wiki_telemetry(workspace):
    """读 wiki 目录返回 {mode, authority_distribution} — 有 I/O, 不放 pure-function 测试.

    放在这里 (而非 evidence_verify.py) 是因为它是 funnel 专用辅助, 没必要污染 evidence_verify
    的核心职责. 调用方在 emit 前后各一次, 用时才读.

    2026-04-27 P0-A 修复: 走 content_loader.iter_wiki_files 同步外挂 canonical
    wiki — 之前 glob workspace local 只看到 13 个 generated, 现在能看到 49 个
    canonical, authority_distribution 不再空. wiki_mode 跟 _is_wiki_sparse 联动.
    """
    import os
    from content_loader import iter_wiki_files
    from review.evidence_verify import _wiki_authority_tier, _is_wiki_sparse, _META_WIKI_FILENAMES

    wiki_dir = os.path.join(workspace, "wiki")
    md_files = iter_wiki_files(wiki_dir)
    if not md_files:
        return {"mode": "sparse", "authority_distribution": {}}

    # 同 basename 去重 (workspace 优先, 跟 _build_wiki_index 一致), 防外挂 canonical
    # 与 workspace 同名 page 重复计数 (e.g., PM 在 workspace 落地了一个 canonical 副本)
    by_basename: dict[str, str] = {}
    for p in md_files:
        bn = os.path.basename(p)
        if bn in _META_WIKI_FILENAMES:
            continue
        by_basename[bn] = p  # 后到覆盖 (workspace local 在 iter 后部)

    dist: Counter[str] = Counter()
    for p in by_basename.values():
        dist[_wiki_authority_tier(p)] += 1

    mode = "sparse" if _is_wiki_sparse(wiki_dir) else "rich"
    return {"mode": mode, "authority_distribution": dict(dist)}
