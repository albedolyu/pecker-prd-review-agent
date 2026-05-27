from __future__ import annotations

from pathlib import Path
from typing import Any

from pecker.channel_eval import evaluate_channels, load_channel_config, rank_channels
from pecker.graph import run_review
from pecker.models import ReviewRequest, ReviewResult
from pecker.prompt_quality import evaluate_prompt_quality, load_prompt_variants, rank_prompt_quality


EXPECTED_TRACE = [
    "prepare_context",
    "precheck_assets",
    "fan_out_workers",
    "merge_findings",
    "advisor_cross_check",
    "finalize_report",
]
PROMPT_GATE_MIN_OVERALL = 0.7
PROMPT_GATE_MIN_RATE = 0.5


def run_eval_suite(
    *,
    prd_path: str | Path,
    channel_config: str | Path,
    prompt_config: str | Path,
    dry_run: bool = True,
) -> dict[str, Any]:
    prd = Path(prd_path)
    review = run_review(
        ReviewRequest(
            title=prd.stem,
            content=prd.read_text(encoding="utf-8"),
        )
    )

    channel_scores = evaluate_channels(load_channel_config(channel_config), dry_run=dry_run)
    channel_rankings = rank_channels(channel_scores)
    prompt_scores = evaluate_prompt_quality(load_prompt_variants(prompt_config))
    prompt_rankings = rank_prompt_quality(prompt_scores)

    review_section = _review_section(review)
    channel_section = _channel_section(channel_rankings)
    prompt_section = _prompt_section(prompt_rankings)
    overall_pass = (
        review_section["gate_pass"]
        and channel_section["gate_pass_rate"] == 1.0
        and prompt_section["gate_pass_rate"] >= PROMPT_GATE_MIN_RATE
    )

    return {
        "summary": {
            "overall_pass": overall_pass,
            "what_it_proves": [
                "agent nodes execute in the expected order",
                "worker findings include PM-adoptable how-to-fix guidance",
                "model channels are ranked behind explicit admission gates",
                "prompt variants are compared with measurable quality controls",
            ],
        },
        "review": review_section,
        "channels": channel_section,
        "prompts": prompt_section,
    }


def _review_section(review: ReviewResult) -> dict[str, Any]:
    finding_count = len(review.findings)
    how_to_fix_rate = _field_rate([finding.how_to_fix for finding in review.findings])
    acceptance_rate = _field_rate([finding.acceptance_check for finding in review.findings])
    trace_matches = review.trace == EXPECTED_TRACE
    return {
        "status": review.status,
        "trace_nodes": review.trace,
        "trace_matches_expected": trace_matches,
        "worker_count": len(review.workers),
        "finding_count": finding_count,
        "findings_with_how_to_fix_rate": how_to_fix_rate,
        "findings_with_acceptance_check_rate": acceptance_rate,
        "gate_pass": (
            review.status == "ok"
            and trace_matches
            and len(review.workers) == 4
            and how_to_fix_rate >= 0.95
            and acceptance_rate >= 0.95
        ),
    }


def _channel_section(rankings: list[dict[str, Any]]) -> dict[str, Any]:
    rankings = [_normalise_channel_row(row) for row in rankings]
    pass_count = sum(1 for row in rankings if row["passed_gate"])
    return {
        "top_channel": rankings[0] if rankings else None,
        "gate_pass_rate": _ratio(pass_count, len(rankings)),
        "rankings": rankings,
    }


def _prompt_section(rankings: list[dict[str, Any]]) -> dict[str, Any]:
    pass_count = sum(1 for row in rankings if row["overall"] >= PROMPT_GATE_MIN_OVERALL)
    return {
        "top_prompt": rankings[0] if rankings else None,
        "gate_min_overall": PROMPT_GATE_MIN_OVERALL,
        "gate_pass_rate": _ratio(pass_count, len(rankings)),
        "missing_controls_by_prompt": {
            row["name"]: row["missing_controls"] for row in rankings if row["missing_controls"]
        },
        "rankings": rankings,
    }


def _field_rate(values: list[str]) -> float:
    if not values:
        return 1.0
    return _ratio(sum(1 for value in values if value.strip()), len(values))


def _normalise_channel_row(row: dict[str, Any]) -> dict[str, Any]:
    clean = dict(row)
    clean["p95_latency_ms"] = round(float(clean["p95_latency_ms"]), 2)
    clean["cost_per_run_usd"] = round(float(clean["cost_per_run_usd"]), 6)
    return clean


def _ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 1.0
    return round(numerator / denominator, 4)
