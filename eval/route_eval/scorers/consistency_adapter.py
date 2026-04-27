"""eval/consistency_eval.py 的 route_eval 适配层.

把 consistency_eval.calculate_overlap 包成统一签名:
    score_overlap(responses_n_runs) -> {overlap_pct, sampling_cv, n0_variance}

responses_n_runs: List[List[item_dict]] -- 外层是 N 次 run, 每个 run 是 review_items.
也接受 List[response_with_items], 自动剥 items 字段.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List

try:
    from eval.consistency_eval import calculate_overlap
except ImportError:  # pragma: no cover
    calculate_overlap = None


def _normalize_runs(responses_n_runs: List[Any]) -> List[List[Dict[str, Any]]]:
    """统一为 List[List[item_dict]], 接受三种入参形态."""
    out = []
    for run in responses_n_runs or []:
        if isinstance(run, list):
            # 已经是 items list
            out.append([it for it in run if isinstance(it, dict)])
        elif isinstance(run, dict):
            items = run.get("items") or run.get("review_items") or []
            out.append([it for it in items if isinstance(it, dict)])
        else:
            items = getattr(run, "items", None) or []
            out.append([it for it in items if isinstance(it, dict)])
    return out


def _sampling_cv(runs: List[List[Dict[str, Any]]]) -> float:
    """各轮 N0 (改进项数) 的变异系数 = stdev / mean. 越低越稳定."""
    counts = [len(r) for r in runs]
    if not counts:
        return 0.0
    mean = sum(counts) / len(counts)
    if mean == 0:
        return 0.0
    var = sum((c - mean) ** 2 for c in counts) / len(counts)
    return round(math.sqrt(var) / mean, 4)


def _n0_variance(runs: List[List[Dict[str, Any]]]) -> float:
    """各轮 N0 总数的方差. memory pecker_sprint_day3 提及的指标."""
    counts = [len(r) for r in runs]
    if len(counts) < 2:
        return 0.0
    mean = sum(counts) / len(counts)
    var = sum((c - mean) ** 2 for c in counts) / len(counts)
    return round(var, 4)


def score_overlap(responses_n_runs: List[Any]) -> Dict[str, float]:
    """跑 consistency_eval.calculate_overlap, 抽出 overlap_pct / sampling_cv / n0_variance.

    Returns:
        {
            overlap_pct: 0-1, 平均 pairwise overlap (Jaccard-like),
            sampling_cv: 0+, N0 变异系数 (越小越稳),
            n0_variance: 0+, N0 方差,
            stable_count: int, 全轮都出现的稳定项数,
            n_runs: int,
        }
    """
    runs = _normalize_runs(responses_n_runs)
    n_runs = len(runs)

    if n_runs < 2 or not calculate_overlap:
        return {
            "overlap_pct": 1.0 if n_runs <= 1 else 0.0,
            "sampling_cv": _sampling_cv(runs),
            "n0_variance": _n0_variance(runs),
            "stable_count": 0,
            "n_runs": n_runs,
            "_note": "n_runs<2 or calculate_overlap unavailable",
        }

    pairwise, stable, _frequency = calculate_overlap(runs)
    avg_overlap = (sum(p["overlap"] for p in pairwise) / len(pairwise)) if pairwise else 0.0

    return {
        "overlap_pct": round(avg_overlap, 4),
        "sampling_cv": _sampling_cv(runs),
        "n0_variance": _n0_variance(runs),
        "stable_count": len(stable),
        "n_runs": n_runs,
    }
