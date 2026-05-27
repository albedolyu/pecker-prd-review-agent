from __future__ import annotations

import argparse
import json
from pathlib import Path

from pecker.channel_eval import evaluate_channels, load_channel_config, rank_channels
from pecker.eval_suite import run_eval_suite
from pecker.graph import run_review
from pecker.models import ReviewRequest
from pecker.prompt_quality import evaluate_prompt_quality, load_prompt_variants, rank_prompt_quality


def review_main() -> None:
    parser = argparse.ArgumentParser(description="Run a public-safe PRD review demo.")
    parser.add_argument("prd", help="Path to a markdown PRD.")
    parser.add_argument("--json", action="store_true", help="Print JSON instead of a text summary.")
    parser.add_argument("--mode", choices=["light", "standard"], default="standard")
    args = parser.parse_args()

    path = Path(args.prd)
    request = ReviewRequest(title=path.stem, content=path.read_text(encoding="utf-8"), mode=args.mode)
    result = run_review(request)
    if args.json:
        print(result.model_dump_json(indent=2))
        return
    print(result.summary)
    for finding in result.findings:
        print(f"- [{finding.id}] {finding.title}: {finding.how_to_fix}")


def channel_eval_main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate model channel candidates.")
    parser.add_argument("--config", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    candidates = load_channel_config(args.config)
    scores = evaluate_channels(candidates, dry_run=args.dry_run)
    print(json.dumps({"rankings": rank_channels(scores)}, ensure_ascii=False, indent=2))


def prompt_quality_main() -> None:
    parser = argparse.ArgumentParser(description="Score prompt variants against measurable quality gates.")
    parser.add_argument("--config", required=True)
    args = parser.parse_args()

    variants = load_prompt_variants(args.config)
    scores = evaluate_prompt_quality(variants)
    print(json.dumps({"rankings": rank_prompt_quality(scores)}, ensure_ascii=False, indent=2))


def eval_suite_main() -> None:
    parser = argparse.ArgumentParser(description="Run the public PRD review, channel, and prompt eval suite.")
    parser.add_argument("--prd", default="examples/sample_prd.md")
    parser.add_argument("--channels", default="config/model_channels.example.yaml")
    parser.add_argument("--prompts", default="config/prompt_quality.example.yaml")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    report = run_eval_suite(
        prd_path=args.prd,
        channel_config=args.channels,
        prompt_config=args.prompts,
        dry_run=args.dry_run,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
