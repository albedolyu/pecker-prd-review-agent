"""Score prompt optimization runs across multiple cases.

Input JSON shape:
{
  "cases": [
    {
      "case_id": "risk-alert",
      "baseline": {"items": [...], "usage": {"input_tokens": 1000}, "elapsed_s": 10},
      "candidate": {"items": [...], "usage": {"input_tokens": 800}, "elapsed_s": 8}
    }
  ]
}
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, List, Mapping, Optional

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from eval.promptopt_global_objective import (  # noqa: E402
    build_langfuse_score_payloads,
    score_promptopt_suite,
)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Score Pecker prompt optimization candidates with a multi-case global objective."
    )
    parser.add_argument("--input", required=True, help="JSON file containing cases or {cases: [...]}")
    parser.add_argument("--prompt-variant", required=True, help="Candidate prompt variant name")
    parser.add_argument("--batch-id", default="", help="Eval batch id; defaults to timestamp")
    parser.add_argument("--output-json", help="Result JSON path")
    parser.add_argument("--output-md", help="Markdown report path")
    parser.add_argument("--scores-json", help="Optional Langfuse score payload JSON path")
    parser.add_argument("--trace-id", help="Optional trace id attached to score payloads")
    parser.add_argument("--session-id", help="Optional session id attached to score payloads")
    parser.add_argument("--record-langfuse", action="store_true", help="Write generated scores to Langfuse")
    args = parser.parse_args(argv)

    batch_id = args.batch_id.strip() or time.strftime("promptopt-global-%Y%m%d_%H%M%S")
    cases = _load_cases(Path(args.input))
    result = score_promptopt_suite(
        cases,
        prompt_variant=args.prompt_variant,
        batch_id=batch_id,
    )
    scores = build_langfuse_score_payloads(
        result,
        trace_id=args.trace_id,
        session_id=args.session_id,
    )

    out_json = Path(args.output_json) if args.output_json else _default_output_path(batch_id, ".json")
    out_md = Path(args.output_md) if args.output_md else out_json.with_suffix(".md")
    _write_json(out_json, result)
    _write_text(out_md, _render_markdown(result))
    if args.scores_json:
        _write_json(Path(args.scores_json), scores)
    if args.record_langfuse:
        _record_langfuse_scores(scores)

    print(
        json.dumps(
            {
                "pass": result["pass"],
                "global_score": result["global_score"],
                "case_count": result["summary"]["case_count"],
                "output_json": str(out_json),
                "output_md": str(out_md),
                "scores": len(scores),
                "fail_reasons": result["fail_reasons"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if result["pass"] else 2


def _load_cases(path: Path) -> List[Mapping[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    cases = payload.get("cases") if isinstance(payload, Mapping) else payload
    if not isinstance(cases, list):
        raise ValueError("input JSON must be a list or an object with a cases list")
    return [case for case in cases if isinstance(case, Mapping)]


def _default_output_path(batch_id: str, suffix: str) -> Path:
    safe_batch = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in batch_id)
    return _REPO_ROOT / "eval_reports" / f"promptopt_global_{safe_batch}{suffix}"


def _render_markdown(result: Mapping[str, Any]) -> str:
    summary = result.get("summary") or {}
    metadata = result.get("metadata") or {}
    lines = [
        "# Prompt Optimization Global Eval",
        "",
        f"- batch_id: `{metadata.get('batch_id', '')}`",
        f"- prompt_variant: `{metadata.get('prompt_variant', '')}`",
        f"- verdict: `{'PASS' if result.get('pass') else 'FAIL'}`",
        f"- global_score: `{result.get('global_score', 0.0):.4f}`",
        f"- case_count: `{summary.get('case_count', 0)}`",
        f"- scenario_count: `{summary.get('scenario_count', 0)}`",
        f"- mean_signature_jaccard: `{summary.get('mean_signature_jaccard', 0.0):.4f}`",
        f"- mean_input_token_savings_ratio: `{summary.get('mean_input_token_savings_ratio', 0.0):.4f}`",
        f"- mean_elapsed_savings_ratio: `{summary.get('mean_elapsed_savings_ratio', 0.0):.4f}`",
        f"- mean_false_positive_rate: `{summary.get('mean_false_positive_rate', 0.0):.4f}`",
        "",
    ]
    fail_reasons = result.get("fail_reasons") or []
    if fail_reasons:
        lines.append("## Fail Reasons")
        lines.append("")
        lines.extend(f"- {reason}" for reason in fail_reasons)
        lines.append("")
    by_scenario = summary.get("by_scenario") or {}
    if by_scenario:
        lines.extend(
            [
                "## Scenarios",
                "",
                "| scenario | cases | mean_signature_jaccard | mean_fp_rate | mean_final_delta |",
                "|---|---:|---:|---:|---:|",
            ]
        )
        for scenario, row in by_scenario.items():
            lines.append(
                f"| {scenario} | {row.get('case_count', 0)} | "
                f"{row.get('mean_signature_jaccard', 0.0):.4f} | "
                f"{row.get('mean_false_positive_rate', 0.0):.4f} | "
                f"{row.get('mean_final_item_delta_ratio', 0.0):.4f} |"
            )
        lines.append("")
    lines.extend(
        [
            "## Cases",
            "",
            "| case_id | signature_jaccard | input_savings | elapsed_savings | fp_count | fp_rate | final_delta |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for case in result.get("cases") or []:
        lines.append(
            f"| {case.get('case_id')} | {case.get('signature_jaccard', 0.0):.4f} | "
            f"{case.get('input_token_savings_ratio', 0.0):.4f} | "
            f"{case.get('elapsed_savings_ratio', 0.0):.4f} | "
            f"{case.get('false_positive_count', 0)} | "
            f"{case.get('false_positive_rate', 0.0):.4f} | "
            f"{case.get('final_item_delta_ratio', 0.0):.4f} |"
        )
    lines.append("")
    return "\n".join(lines)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _record_langfuse_scores(scores: List[Mapping[str, Any]]) -> None:
    _load_project_dotenv()
    from langfuse import get_client
    from review.langfuse_observability import _create_langfuse_scores

    _create_langfuse_scores(get_client(), [dict(score) for score in scores])


def _load_project_dotenv() -> None:
    try:
        from dotenv import load_dotenv
    except Exception:  # noqa: BLE001
        return
    load_dotenv(_REPO_ROOT / ".env", override=False)


if __name__ == "__main__":
    raise SystemExit(main())
