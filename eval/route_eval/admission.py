"""准入门槛判定 -- 候选 metrics vs baseline metrics 出 PASS/FAIL.

阈值 (来自 plan "评测体系" 第 4 节, 候选必须同时满足):
    - F1 >= baseline F1 - 0.05 (绝对值)
    - Recall >= baseline Recall - 0.05 (绝对值)
    - Consistency overlap >= baseline overlap - 5pp (绝对值)
    - p95 latency <= baseline p95 * 1.5 (相对)
    - Cost per run <= baseline cost * 2.0 (相对)
    - Hallucination 拦截率 (仅 verify.nli) >= 0.85 (绝对值)
    - Hallucination 误杀率 (仅 verify.nli) <= 0.10 (绝对值)

任一不达标 => pass=False.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


# 阈值常量 -- 集中在这里, 后续校准只改这里
F1_DELTA_TOL = -0.05            # 候选 - baseline >= -0.05
RECALL_DELTA_TOL = -0.05
OVERLAP_DELTA_TOL = -0.05       # -5pp
P95_LATENCY_RATIO = 1.5         # 候选 / baseline <= 1.5
COST_RATIO = 2.0                # 候选 / baseline <= 2.0
HALLUC_TPR_MIN = 0.85           # 拦截率绝对下限
HALLUC_FPR_MAX = 0.10           # 误杀率绝对上限


def _pluck(d: Optional[Dict[str, Any]], *keys: str, default: float = 0.0) -> float:
    """从可能 None 的 dict 嵌套取 float, 兜底 default."""
    if d is None:
        return default
    cur: Any = d
    for k in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k)
        if cur is None:
            return default
    try:
        return float(cur)
    except (TypeError, ValueError):
        return default


def admit(
    candidate_metrics: Dict[str, Any],
    baseline_metrics: Dict[str, Any],
    route_id: str,
) -> Dict[str, Any]:
    """对候选 route 跑准入判定.

    Args:
        candidate_metrics: dict 含 capability/stability/cost_latency 三大块
            schema:
                {
                    "capability": {p, r, f1, ...},
                    "stability": {overlap, ...},
                    "cost_latency": {p95_ms, cost_usd_per_run, ...},
                    "hallucination": {tpr, fpr},  # 仅 verify.nli 路由
                }
        baseline_metrics: 同上 schema
        route_id: 用于决定是否启用 hallucination 检查 (仅 verify.nli)

    Returns:
        {
            pass: bool,
            deltas: {f1, recall, overlap, p95_ratio, cost_ratio, halluc_tpr, halluc_fpr},
            fail_reasons: [str, ...],  # 空表示全 PASS
            checks: {<check_name>: {value, threshold, passed}, ...}
        }
    """
    # 抽数
    cand_f1 = _pluck(candidate_metrics, "capability", "f1")
    base_f1 = _pluck(baseline_metrics, "capability", "f1")
    cand_r = _pluck(candidate_metrics, "capability", "r")
    base_r = _pluck(baseline_metrics, "capability", "r")
    cand_overlap = _pluck(candidate_metrics, "stability", "overlap")
    base_overlap = _pluck(baseline_metrics, "stability", "overlap")
    cand_p95 = _pluck(candidate_metrics, "cost_latency", "p95_ms")
    base_p95 = _pluck(baseline_metrics, "cost_latency", "p95_ms")
    cand_cost = _pluck(candidate_metrics, "cost_latency", "cost_usd_per_run")
    base_cost = _pluck(baseline_metrics, "cost_latency", "cost_usd_per_run")

    # delta 计算
    f1_delta = round(cand_f1 - base_f1, 4)
    r_delta = round(cand_r - base_r, 4)
    overlap_delta = round(cand_overlap - base_overlap, 4)
    p95_ratio = round(cand_p95 / base_p95, 3) if base_p95 > 0 else 0.0
    cost_ratio = round(cand_cost / base_cost, 3) if base_cost > 0 else 0.0

    fail_reasons: List[str] = []
    checks: Dict[str, Dict[str, Any]] = {}

    # 1) F1
    f1_ok = f1_delta >= F1_DELTA_TOL
    checks["f1_delta"] = {
        "value": f1_delta, "threshold": F1_DELTA_TOL, "passed": f1_ok,
        "candidate": cand_f1, "baseline": base_f1,
    }
    if not f1_ok:
        fail_reasons.append(
            f"F1 delta {f1_delta:+.4f} < {F1_DELTA_TOL} "
            f"(候选 {cand_f1:.4f} vs baseline {base_f1:.4f})"
        )

    # 2) Recall
    r_ok = r_delta >= RECALL_DELTA_TOL
    checks["recall_delta"] = {
        "value": r_delta, "threshold": RECALL_DELTA_TOL, "passed": r_ok,
        "candidate": cand_r, "baseline": base_r,
    }
    if not r_ok:
        fail_reasons.append(
            f"Recall delta {r_delta:+.4f} < {RECALL_DELTA_TOL} "
            f"(候选 {cand_r:.4f} vs baseline {base_r:.4f})"
        )

    # 3) Consistency overlap
    overlap_ok = overlap_delta >= OVERLAP_DELTA_TOL
    checks["overlap_delta"] = {
        "value": overlap_delta, "threshold": OVERLAP_DELTA_TOL, "passed": overlap_ok,
        "candidate": cand_overlap, "baseline": base_overlap,
    }
    if not overlap_ok:
        fail_reasons.append(
            f"Overlap delta {overlap_delta:+.4f} < {OVERLAP_DELTA_TOL} "
            f"(候选 {cand_overlap:.4f} vs baseline {base_overlap:.4f})"
        )

    # 4) p95 latency ratio
    p95_ok = (base_p95 == 0) or (p95_ratio <= P95_LATENCY_RATIO)
    checks["p95_latency_ratio"] = {
        "value": p95_ratio, "threshold": P95_LATENCY_RATIO, "passed": p95_ok,
        "candidate": cand_p95, "baseline": base_p95,
    }
    if not p95_ok:
        fail_reasons.append(
            f"p95 latency ratio {p95_ratio} > {P95_LATENCY_RATIO} "
            f"(候选 {cand_p95}ms vs baseline {base_p95}ms)"
        )

    # 5) Cost ratio
    cost_ok = (base_cost == 0) or (cost_ratio <= COST_RATIO)
    checks["cost_ratio"] = {
        "value": cost_ratio, "threshold": COST_RATIO, "passed": cost_ok,
        "candidate": cand_cost, "baseline": base_cost,
    }
    if not cost_ok:
        fail_reasons.append(
            f"Cost ratio {cost_ratio} > {COST_RATIO} "
            f"(候选 ${cand_cost} vs baseline ${base_cost} per run)"
        )

    # 6/7) Hallucination 拦截 / 误杀 -- 仅对 verify.nli 启用
    halluc_tpr = _pluck(candidate_metrics, "hallucination", "tpr")
    halluc_fpr = _pluck(candidate_metrics, "hallucination", "fpr")
    if route_id == "verify.nli":
        tpr_ok = halluc_tpr >= HALLUC_TPR_MIN
        checks["hallucination_tpr"] = {
            "value": halluc_tpr, "threshold": HALLUC_TPR_MIN, "passed": tpr_ok,
        }
        if not tpr_ok:
            fail_reasons.append(
                f"Hallucination 拦截率 {halluc_tpr:.4f} < {HALLUC_TPR_MIN}"
            )

        fpr_ok = halluc_fpr <= HALLUC_FPR_MAX
        checks["hallucination_fpr"] = {
            "value": halluc_fpr, "threshold": HALLUC_FPR_MAX, "passed": fpr_ok,
        }
        if not fpr_ok:
            fail_reasons.append(
                f"Hallucination 误杀率 {halluc_fpr:.4f} > {HALLUC_FPR_MAX}"
            )

    return {
        "pass": len(fail_reasons) == 0,
        "deltas": {
            "f1": f1_delta,
            "recall": r_delta,
            "overlap": overlap_delta,
            "p95_ratio": p95_ratio,
            "cost_ratio": cost_ratio,
            "halluc_tpr": halluc_tpr if route_id == "verify.nli" else None,
            "halluc_fpr": halluc_fpr if route_id == "verify.nli" else None,
        },
        "fail_reasons": fail_reasons,
        "checks": checks,
        "route_id": route_id,
    }
