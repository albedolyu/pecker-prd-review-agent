"""5 维度指标计算 -- capability / stability / cross_vendor_bias / cost_latency / failure_modes.

每个 compute_* 接 runner 收集的原始数据 (responses + call_records), 输出标准 dict.
admission.admit() 消费这些 dict 做阈值判定.

call_records 是 runner 在每次 route_call 后 append 的元数据列表:
    [{
        "ts": <iso>, "route_id": str, "vendor": str, "model": str,
        "latency_ms": int, "input_tokens": int, "output_tokens": int,
        "cost_usd": float, "stop_reason": str,
        "error_type": str | None,        # quota / json_parse / tool_use / timeout / fallback / None
        "fallback_triggered": bool,
    }, ...]
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

from .scorers.consistency_adapter import score_overlap
from .scorers.cuckoo_adapter import score_worker_outputs


# ============================================================
# 1. Capability -- P/R/F1 + severity 分布 KL 散度
# ============================================================

def _kl_divergence(p: Dict[str, int], q: Dict[str, int], smoothing: float = 1e-6) -> float:
    """KL(P||Q) 衡量两个 severity 分布的差距, smoothing 避免 log(0).

    把计数转概率, 再算 sum(p * log(p/q)). 越接近 0 越像基线.
    """
    keys = set(p.keys()) | set(q.keys())
    p_total = sum(p.values()) or 1
    q_total = sum(q.values()) or 1
    kl = 0.0
    for k in keys:
        pk = (p.get(k, 0) / p_total) + smoothing
        qk = (q.get(k, 0) / q_total) + smoothing
        kl += pk * math.log(pk / qk)
    return round(kl, 4)


def compute_classification_metrics(
    predictions: List[Dict[str, Any]],
    task_type: str = "binary",
) -> Dict[str, Any]:
    """分类任务 (NLI / intent) 指标 -- accuracy / TPR / FPR / per-class.

    Args:
        predictions: list of dict, 字段按 task_type:
            binary: {expected_hallucination: bool, detected_hallucination: bool, correct: bool}
            multiclass: {expected_tier: str, predicted_tier: str, correct: bool}
        task_type: "binary" (verify.nli) 或 "multiclass" (router.intent)

    Returns:
        {accuracy, n_samples, n_correct, ...} + task_type 专用字段
    """
    if not predictions:
        return {"accuracy": 0.0, "n_samples": 0, "n_correct": 0, "task_type": task_type}

    n = len(predictions)
    correct = sum(1 for p in predictions if p.get("correct", False))
    accuracy = correct / n if n else 0.0
    out: Dict[str, Any] = {
        "accuracy": round(accuracy, 4),
        "n_samples": n,
        "n_correct": correct,
        "task_type": task_type,
    }

    if task_type == "binary":
        # TPR (hallucination 拦截率) / FPR (误杀率) -- admission 阈值 ≥0.85 / ≤0.10
        tp = sum(1 for p in predictions
                 if p.get("expected_hallucination") and p.get("detected_hallucination"))
        fn = sum(1 for p in predictions
                 if p.get("expected_hallucination") and not p.get("detected_hallucination"))
        fp = sum(1 for p in predictions
                 if not p.get("expected_hallucination") and p.get("detected_hallucination"))
        tn = sum(1 for p in predictions
                 if not p.get("expected_hallucination") and not p.get("detected_hallucination"))
        tpr = tp / (tp + fn) if (tp + fn) else 0.0
        fpr = fp / (fp + tn) if (fp + tn) else 0.0
        out.update({
            "tpr": round(tpr, 4),
            "fpr": round(fpr, 4),
            "true_positives": tp,
            "false_negatives": fn,
            "false_positives": fp,
            "true_negatives": tn,
        })
    elif task_type == "multiclass":
        from collections import Counter
        per_class_total: Counter = Counter(p.get("expected_tier") for p in predictions)
        per_class_correct: Counter = Counter()
        for p in predictions:
            if p.get("correct"):
                per_class_correct[p.get("expected_tier")] += 1
        out["per_class_accuracy"] = {
            k: round(per_class_correct[k] / v, 4) if v else 0.0
            for k, v in per_class_total.items()
        }
        out["per_class_total"] = dict(per_class_total)

    return out


def compute_capability(
    responses: List[Any],
    ground_truth: List[Dict[str, Any]],
    baseline_severity: Optional[Dict[str, int]] = None,
) -> Dict[str, Any]:
    """worker.* / advisor.* 能力指标.

    Args:
        responses: List of {items: [...]} 或 _FakeResponse-like
        ground_truth: planted_bugs (cuckoo 风格)
        baseline_severity: 可选, baseline severity 分布, 用于算 KL

    Returns:
        {p, r, f1, severity_kl, severity_distribution, hits, misses, fps, total_items}
    """
    scored = score_worker_outputs(responses, ground_truth)
    sev_dist = scored.get("severity_distribution", {})

    severity_kl = 0.0
    if baseline_severity:
        severity_kl = _kl_divergence(sev_dist, baseline_severity)

    return {
        "p": scored["p"],
        "r": scored["r"],
        "f1": scored["f1"],
        "severity_kl": severity_kl,
        "severity_distribution": sev_dist,
        "hits": scored.get("hits", 0),
        "misses": scored.get("misses", 0),
        "fps": scored.get("fps", 0),
        "total_items": scored.get("total_items", 0),
    }


# ============================================================
# 2. Stability -- consistency overlap + N0 浮动 + sampling CV
# ============================================================

def compute_stability(responses_n_runs: List[Any]) -> Dict[str, float]:
    """同一输入 N 次 run 之间的稳定性指标.

    Args:
        responses_n_runs: List[List[item_dict]] 或 List[response-like]

    Returns:
        {overlap, n0_var, sampling_cv, stable_count, n_runs}
    """
    s = score_overlap(responses_n_runs)
    return {
        "overlap": s["overlap_pct"],
        "n0_var": s["n0_variance"],
        "sampling_cv": s["sampling_cv"],
        "stable_count": s.get("stable_count", 0),
        "n_runs": s.get("n_runs", 0),
    }


# ============================================================
# 3. Cross-vendor bias -- κ + 互补召回 + 分歧率
# ============================================================

def compute_cross_vendor_bias(
    responses_a: List[Any],
    responses_b: List[Any],
    ground_truth: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """两 vendor 对同一组输入的偏差度量.

    Args:
        responses_a, responses_b: 两 vendor 的输出 (List of {items: [...]})
        ground_truth: 可选, 用于算 complementary_recall

    Returns:
        {kappa, complementary_recall: {...}, disagreement}
    """
    from .cross_vendor import cohens_kappa, complementary_recall, disagreement_rate
    from .scorers.cuckoo_adapter import _flatten_responses_to_items

    items_a = _flatten_responses_to_items(responses_a)
    items_b = _flatten_responses_to_items(responses_b)

    # severity 标签当 kappa 输入 (按位置对齐, 长度不一致截短)
    n = min(len(items_a), len(items_b))
    sev_a = [(items_a[i].get("severity") or "should") for i in range(n)]
    sev_b = [(items_b[i].get("severity") or "should") for i in range(n)]
    kappa = cohens_kappa(sev_a, sev_b) if n > 0 else 0.0

    # 用 location+issue hash 当 hit_id, 算互补召回
    def _id(it: Dict[str, Any]) -> str:
        return f"{(it.get('location') or '').strip()}::{(it.get('issue') or it.get('problem') or '').strip()[:40]}"

    set_a = {_id(it) for it in items_a}
    set_b = {_id(it) for it in items_b}
    if ground_truth:
        gt_set = {f"{(b.get('location') or '').strip()}::{(b.get('keywords') or [''])[0][:40]}"
                  for b in ground_truth}
    else:
        gt_set = set_a | set_b  # 没 GT 时拿联合集做名义 GT

    comp = complementary_recall(set_a, set_b, gt_set)

    # 分歧率: 同一 location 上是否给出相同 severity
    decisions_a = [(it.get("location"), it.get("severity")) for it in items_a]
    decisions_b = [(it.get("location"), it.get("severity")) for it in items_b]
    common_locs = ({d[0] for d in decisions_a} & {d[0] for d in decisions_b})
    da = [next((d[1] for d in decisions_a if d[0] == loc), None) for loc in common_locs]
    db = [next((d[1] for d in decisions_b if d[0] == loc), None) for loc in common_locs]
    disagreement = disagreement_rate(da, db) if common_locs else 0.0

    return {
        "kappa": kappa,
        "complementary_recall": comp,
        "disagreement": disagreement,
    }


# ============================================================
# 4. Cost / Latency -- p50/p95/p99 + 单次成本
# ============================================================

def _percentile(sorted_values: List[float], pct: float) -> float:
    if not sorted_values:
        return 0.0
    k = (len(sorted_values) - 1) * pct
    lo = int(math.floor(k))
    hi = int(math.ceil(k))
    if lo == hi:
        return sorted_values[lo]
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (k - lo)


def compute_cost_latency(call_records: List[Dict[str, Any]]) -> Dict[str, float]:
    """从 call_records 列表算 latency 分位数 + 总/单次成本.

    Args:
        call_records: 见模块顶部 docstring

    Returns:
        {p50_ms, p95_ms, p99_ms, cost_usd_total, cost_usd_per_run,
         total_input_tokens, total_output_tokens, n_calls}
    """
    n = len(call_records or [])
    if n == 0:
        return {
            "p50_ms": 0.0, "p95_ms": 0.0, "p99_ms": 0.0,
            "cost_usd_total": 0.0, "cost_usd_per_run": 0.0,
            "total_input_tokens": 0, "total_output_tokens": 0, "n_calls": 0,
        }

    latencies = sorted(max(0.0, float(r.get("latency_ms", 0) or 0)) for r in call_records)
    costs = [max(0.0, float(r.get("cost_usd", 0) or 0)) for r in call_records]
    in_toks = sum(max(0, int(r.get("input_tokens", 0) or 0)) for r in call_records)
    out_toks = sum(max(0, int(r.get("output_tokens", 0) or 0)) for r in call_records)
    total_cost = sum(costs)

    return {
        "p50_ms": round(_percentile(latencies, 0.50), 2),
        "p95_ms": round(_percentile(latencies, 0.95), 2),
        "p99_ms": round(_percentile(latencies, 0.99), 2),
        "cost_usd_total": round(total_cost, 6),
        "cost_usd_per_run": round(total_cost / n, 6),
        "total_input_tokens": in_toks,
        "total_output_tokens": out_toks,
        "n_calls": n,
    }


# ============================================================
# 5. Failure modes -- 配额 / parse / tool_use / fallback / timeout 比率
# ============================================================

def compute_failure_modes(call_records: List[Dict[str, Any]]) -> Dict[str, float]:
    """分类统计失败模式占比.

    error_type 取值:
        - "quota": 429 / QuotaExhaustedError
        - "json_parse": JSON 抛错
        - "tool_use": tool_use 协议失败
        - "timeout": 超时
        - "fallback": 降级触发
        - None: 成功
    """
    n = len(call_records or [])
    if n == 0:
        return {
            "quota_rate": 0.0, "json_parse_fail_rate": 0.0,
            "tool_use_fail_rate": 0.0, "fallback_rate": 0.0,
            "timeout_rate": 0.0, "n_calls": 0,
        }

    counts = {"quota": 0, "json_parse": 0, "tool_use": 0, "timeout": 0, "fallback": 0}
    for r in call_records:
        et = (r.get("error_type") or "").strip().lower()
        if et in counts:
            counts[et] += 1
        if r.get("fallback_triggered"):
            counts["fallback"] += 1

    return {
        "quota_rate": round(counts["quota"] / n, 4),
        "json_parse_fail_rate": round(counts["json_parse"] / n, 4),
        "tool_use_fail_rate": round(counts["tool_use"] / n, 4),
        "fallback_rate": round(counts["fallback"] / n, 4),
        "timeout_rate": round(counts["timeout"] / n, 4),
        "n_calls": n,
    }
