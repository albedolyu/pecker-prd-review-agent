from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Set


CORE_DIMENSIONS = ("结构层", "质量层", "AI Coding 友好度", "数据质量")
MIN_ITEM_RATIO = 0.80
MIN_RULE_RATIO = 0.70


def _items(report: Dict[str, Any]) -> List[Dict[str, Any]]:
    items = report.get("items") or report.get("verified_items") or []
    return [item for item in items if isinstance(item, dict)]


def _item_count(report: Dict[str, Any]) -> int:
    return int(report.get("merged_count") or len(_items(report)))


def _dimension_counts(report: Dict[str, Any]) -> Counter:
    counts: Counter = Counter()
    for item in _items(report):
        dim = item.get("dimension")
        if dim:
            counts[str(dim)] += 1
    return counts


def _rule_ids(report: Dict[str, Any]) -> Set[str]:
    rules = set()
    for item in _items(report):
        rid = item.get("rule_id")
        if rid:
            rules.add(str(rid))
    return rules


def _ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 1.0
    return round(numerator / denominator, 4)


def evaluate_output_regression(
    baseline: Dict[str, Any],
    current: Dict[str, Any],
    *,
    min_item_ratio: float = MIN_ITEM_RATIO,
    min_rule_ratio: float = MIN_RULE_RATIO,
    core_dimensions: Iterable[str] = CORE_DIMENSIONS,
) -> Dict[str, Any]:
    baseline_count = _item_count(baseline)
    current_count = _item_count(current)
    baseline_rules = _rule_ids(baseline)
    current_rules = _rule_ids(current)
    baseline_dims = _dimension_counts(baseline)
    current_dims = _dimension_counts(current)
    item_ratio = _ratio(current_count, baseline_count)
    rule_ratio = _ratio(len(current_rules), len(baseline_rules))

    failures: List[Dict[str, Any]] = []
    completion = current.get("completion") or {}
    if completion.get("status") == "partial" or completion.get("failed_workers"):
        failures.append({
            "code": "PARTIAL_REVIEW",
            "message": "current report is partial or has failed workers",
            "failed_workers": completion.get("failed_workers") or [],
        })

    if item_ratio < min_item_ratio:
        failures.append({
            "code": "ITEM_COUNT_DROP",
            "message": f"item count ratio {item_ratio} below threshold {min_item_ratio}",
            "baseline_count": baseline_count,
            "current_count": current_count,
        })

    if rule_ratio < min_rule_ratio:
        failures.append({
            "code": "RULE_COVERAGE_DROP",
            "message": f"rule coverage ratio {rule_ratio} below threshold {min_rule_ratio}",
            "baseline_rule_count": len(baseline_rules),
            "current_rule_count": len(current_rules),
        })

    for dim in core_dimensions:
        if baseline_dims.get(dim, 0) > 0 and current_dims.get(dim, 0) == 0:
            failures.append({
                "code": "DIMENSION_ZERO",
                "message": f"dimension {dim} dropped to zero items",
                "dimension": dim,
                "baseline_count": baseline_dims.get(dim, 0),
                "current_count": 0,
            })

    return {
        "status": "fail" if failures else "pass",
        "failures": failures,
        "metrics": {
            "baseline_count": baseline_count,
            "current_count": current_count,
            "item_ratio": item_ratio,
            "baseline_rule_count": len(baseline_rules),
            "current_rule_count": len(current_rules),
            "rule_ratio": rule_ratio,
            "baseline_dimensions": dict(baseline_dims),
            "current_dimensions": dict(current_dims),
        },
    }


def load_report(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def parse_args(argv: List[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare PRD review output against a baseline report.")
    parser.add_argument("--baseline", required=True, help="Baseline JSON report.")
    parser.add_argument("--current", required=True, help="Current JSON report.")
    parser.add_argument("--min-item-ratio", type=float, default=MIN_ITEM_RATIO)
    parser.add_argument("--min-rule-ratio", type=float, default=MIN_RULE_RATIO)
    parser.add_argument("--output", default=None, help="Optional JSON output path.")
    return parser.parse_args(argv)


def main(argv: List[str] | None = None) -> int:
    args = parse_args(argv)
    result = evaluate_output_regression(
        load_report(Path(args.baseline)),
        load_report(Path(args.current)),
        min_item_ratio=args.min_item_ratio,
        min_rule_ratio=args.min_rule_ratio,
    )
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())

