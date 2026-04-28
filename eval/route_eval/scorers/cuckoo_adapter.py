"""cuckoo_eval / cuckoo_scorer 的 route_eval 适配层.

把 cuckoo_scorer.match_items_to_bugs + calculate_scores 包成统一签名:
    score_worker_outputs(responses, ground_truth) -> {p, r, f1, severity_distribution}

responses: List[dict], 每条至少含 "items": [<review_item>] (从 _FakeResponse / 真 worker
output 里抽出来的改进项).
ground_truth: List[dict], cuckoo 风格 planted_bugs (含 id/location/keywords/severity/type).
"""
from __future__ import annotations

from typing import Any, Dict, List

# 项目根 sys.path 在 runner / scripts 入口处补, 这里直接 from cuckoo_scorer import 即可
try:
    from cuckoo_scorer import calculate_scores, match_items_to_bugs
except ImportError:  # pragma: no cover -- 单元测试时走 mock 也别炸
    match_items_to_bugs = None
    calculate_scores = None


def _flatten_responses_to_items(responses: List[Any]) -> List[Dict[str, Any]]:
    """把 N 个 response 的 items 拍平为单一 review_items list (按 cuckoo 期待的 schema).

    支持 3 种输入形态 (兼容 runner._BatchResponse + dry-run + 历史 dict 形态):
    - List[item]: runner.all_responses 直接 append items list (主形态)
    - {items: [...]} dict: 历史形态
    - _FakeResponse / UnifiedResponse 对象: 取 .items 属性
    """
    flat: List[Dict[str, Any]] = []
    for idx, resp in enumerate(responses or []):
        if isinstance(resp, list):
            # runner.all_responses 主形态: 单 run 的 items list 直接 append 进来
            items = resp
        elif isinstance(resp, dict):
            items = resp.get("items") or resp.get("review_items") or []
        else:
            # _FakeResponse / UnifiedResponse 类对象, 兜底取 .items 或空
            items = getattr(resp, "items", None) or []
        for j, item in enumerate(items):
            if isinstance(item, dict):
                # cuckoo 要求 item 有 id 字段 (cuckoo_scorer.py:91/203/223 硬下标 item["id"])
                # 2026-04-27 P2 修: 用 truthy 检查代替 setdefault, 因为 worker LLM 可能
                # 输出 {"id": null} / {"id": ""} 让 setdefault 失效, 仍崩 KeyError.
                merged = dict(item)
                if not merged.get("id"):
                    merged["id"] = f"r{idx}-i{j}"
                # location 也是 cuckoo_scorer._calc_match_score 硬下标依赖
                if not merged.get("location"):
                    merged["location"] = ""
                if not merged.get("problem") and merged.get("issue"):
                    merged["problem"] = merged["issue"]
                if not merged.get("suggestion"):
                    merged["suggestion"] = ""
                flat.append(merged)
    return flat


def _severity_distribution(items: List[Dict[str, Any]]) -> Dict[str, int]:
    """统计 must/should/info 三档计数, 给 KL 散度等下游算法用."""
    dist = {"must": 0, "should": 0, "info": 0, "other": 0}
    for it in items:
        sev = (it.get("severity") or "").strip().lower()
        if sev in dist:
            dist[sev] += 1
        else:
            dist["other"] += 1
    return dist


def score_worker_outputs(
    responses: List[Any],
    ground_truth: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """对 worker.* 输出跑 cuckoo P/R/F1 + severity 分布.

    Args:
        responses: List of {items: [...]} 或 _FakeResponse-like, 多次 run 的合集
        ground_truth: planted_bugs list (cuckoo 风格)

    Returns:
        {p, r, f1, severity_distribution: {must, should, info, other}, hits, misses, fps}
    """
    items = _flatten_responses_to_items(responses)
    sev_dist = _severity_distribution(items)

    if not match_items_to_bugs or not calculate_scores or not ground_truth:
        # cuckoo 模块不可用或没有 GT, 给空指标但不炸 (dry-run 期常见)
        n_items = len(items)
        return {
            "p": 0.0,
            "r": 0.0,
            "f1": 0.0,
            "severity_distribution": sev_dist,
            "hits": 0,
            "misses": len(ground_truth or []),
            "fps": n_items,
            "total_items": n_items,
            "_note": "cuckoo_scorer unavailable or empty ground_truth",
        }

    # GT 也要补 id (loader 映射 planted_bugs.id → rule_id, cuckoo_scorer 仍硬下标 bug["id"])
    normalized_gt = []
    for j, bug in enumerate(ground_truth or []):
        b = dict(bug)
        if not b.get("id"):
            b["id"] = b.get("rule_id") or f"GT-{j:03d}"
        if not b.get("keywords"):
            b["keywords"] = []
        if not b.get("severity"):
            b["severity"] = "must"
        if not b.get("location"):
            b["location"] = ""
        normalized_gt.append(b)
    matches = match_items_to_bugs(items, normalized_gt)
    # calculate_scores 需要 evidence_results tuple, dry-run 跳过 verify_evidence
    fake_evidence = (0, 0, [])
    scored = calculate_scores(matches, fake_evidence, items)

    return {
        "p": round(scored["precision"], 4),
        "r": round(scored["recall"], 4),
        "f1": round(2 * scored["precision"] * scored["recall"] /
                    (scored["precision"] + scored["recall"]), 4)
              if (scored["precision"] + scored["recall"]) > 0 else 0.0,
        "severity_distribution": sev_dist,
        "hits": len(matches["hits"]),
        "misses": len(matches["misses"]),
        "fps": len(matches["false_positives"]),
        "total_items": len(items),
    }
