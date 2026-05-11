"""Golden-set plan for rule impact A/B evaluation.

This module only builds a bounded execution plan. It does not call models by
default, so weekly planning can be reviewed before spend is incurred.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


DEFAULT_MANIFEST = (
    Path("eval")
    / "route_eval"
    / "datasets"
    / "data"
    / "business_prd_gt"
    / "manifest.json"
)


def build_golden_plan(project_root: str | Path = ".", *, limit: int = 10) -> dict[str, Any]:
    root = Path(project_root)
    manifest_path = root / DEFAULT_MANIFEST
    records = _load_manifest_records(manifest_path)
    cases = []
    for record in records[: max(1, min(limit, 10))]:
        ground_truth = record.get("ground_truth") or record.get("inline_ground_truth") or []
        if not isinstance(ground_truth, list):
            ground_truth = []
        ground_truth_count = len(ground_truth)
        if ground_truth_count == 0 and record.get("gt_path"):
            ground_truth_count = _ground_truth_file_count(root / str(record.get("gt_path")))
        cases.append(
            {
                "id": str(record.get("id") or record.get("workspace") or f"case-{len(cases)+1}"),
                "workspace": str(record.get("workspace") or ""),
                "prd_path": str(record.get("prd_path") or ""),
                "ground_truth_count": ground_truth_count,
            }
        )
    return {
        "name": "rule_impact_golden",
        "source": str(manifest_path),
        "run_modes": ["current_impact_score", "neutral_baseline_0_5"],
        "cases": cases,
        "estimated_worker_calls": len(cases) * 4 * 2,
        "note": "Run current impact_score and neutral baseline separately; compare item count, P/R, and PM accept rate.",
    }


def _load_manifest_records(path: Path) -> list[dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return []
    if isinstance(payload, dict):
        for key in ("records", "entries", "cases", "items"):
            records = payload.get(key)
            if isinstance(records, list):
                return [row for row in records if isinstance(row, dict)]
        if all(isinstance(value, dict) for value in payload.values()):
            return [value for value in payload.values() if isinstance(value, dict)]
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    return []


def _ground_truth_file_count(path: Path) -> int:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return 0
    if isinstance(payload, list):
        return len(payload)
    if isinstance(payload, dict):
        for key in ("ground_truth", "planted_bugs", "items", "cases"):
            value = payload.get(key)
            if isinstance(value, list):
                return len(value)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build rule impact golden-set plan")
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--output", default="")
    args = parser.parse_args(argv)
    plan = build_golden_plan(args.project_root, limit=args.limit)
    text = json.dumps(plan, ensure_ascii=False, indent=2)
    if args.output:
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
