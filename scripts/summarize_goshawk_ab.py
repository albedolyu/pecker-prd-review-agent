"""Summarize multiple Goshawk A/B reports into an enablement decision."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from review.langfuse_ab_testing import summarize_goshawk_ab_suite


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize Goshawk final-only A/B reports.")
    parser.add_argument("--input-dir", required=True, help="Directory containing A/B JSON reports.")
    parser.add_argument("--pattern", default="*.json", help="Glob pattern inside input-dir.")
    parser.add_argument("--output-json", default="", help="Summary JSON output path.")
    parser.add_argument("--output-md", default="", help="Summary Markdown output path.")
    parser.add_argument("--min-runs-for-canary", type=int, default=5)
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    input_dir = Path(args.input_dir).expanduser().resolve()
    reports = _load_reports(input_dir, args.pattern)
    result = summarize_goshawk_ab_suite(
        reports,
        min_runs_for_canary=args.min_runs_for_canary,
    )
    output_json = (
        Path(args.output_json).expanduser().resolve()
        if args.output_json
        else input_dir / "goshawk_ab_suite_summary.json"
    )
    output_md = (
        Path(args.output_md).expanduser().resolve()
        if args.output_md
        else input_dir / "goshawk_ab_suite_summary.md"
    )
    _write_json(output_json, result)
    _write_text(output_md, render_markdown(result))
    print(
        json.dumps(
            {
                "recommendation": result["recommendation"],
                "summary": result["summary"],
                "failures": len(result["failures"]),
                "output_json": str(output_json),
                "output_md": str(output_md),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 2 if result["recommendation"]["action"] == "keep_disabled" else 0


def render_markdown(result: Mapping[str, Any]) -> str:
    summary = result.get("summary") or {}
    recommendation = result.get("recommendation") or {}
    lines = [
        "# Goshawk A/B Suite Summary",
        "",
        f"- recommendation: `{recommendation.get('action', '')}`",
        f"- reason: `{recommendation.get('reason', '')}`",
        f"- run_count: `{summary.get('run_count', 0)}`",
        f"- compact_pass_rate: `{float(summary.get('compact_pass_rate') or 0):.4f}`",
        f"- median_input_token_savings_ratio: `{float(summary.get('median_input_token_savings_ratio') or 0):.4f}`",
        f"- median_elapsed_savings_ratio: `{float(summary.get('median_elapsed_savings_ratio') or 0):.4f}`",
        f"- min_final_signature_jaccard: `{float(summary.get('min_final_signature_jaccard') or 0):.4f}`",
        f"- max_false_positive_delta: `{float(summary.get('max_false_positive_delta') or 0):.0f}`",
        "",
    ]
    failures = result.get("failures") or []
    if failures:
        lines.extend(
            [
                "## Failures",
                "",
                "| batch_id | reasons | signature | rule | fp_delta |",
                "|---|---|---:|---:|---:|",
            ]
        )
        for failure in failures:
            metrics = failure.get("metrics") or {}
            lines.append(
                f"| {failure.get('batch_id', '')} | "
                f"{', '.join(failure.get('reasons') or [])} | "
                f"{float(metrics.get('final_signature_jaccard') or 0):.4f} | "
                f"{float(metrics.get('final_rule_jaccard') or 0):.4f} | "
                f"{float(metrics.get('false_positive_delta') or 0):.0f} |"
            )
        lines.append("")
    return "\n".join(lines)


def _load_reports(input_dir: Path, pattern: str) -> list[Mapping[str, Any]]:
    reports = []
    for path in sorted(input_dir.glob(pattern or "*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if isinstance(payload, Mapping) and isinstance(payload.get("ab"), Mapping):
            reports.append(payload)
    return reports


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
