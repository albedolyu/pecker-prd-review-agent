"""Run a final-only Goshawk full-vs-compact A/B experiment."""
from __future__ import annotations

import argparse
import asyncio
import copy
import json
import os
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, Mapping, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent_config import MODEL_TIERS
from content_loader import load_prd_content, load_wiki_pages
from review.langfuse_ab_testing import (
    compare_goshawk_ab_runs,
    record_goshawk_ab_scores,
)


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run Pecker's final-only Goshawk A/B test: full wiki vs compact wiki."
    )
    parser.add_argument("--workspace", required=True, help="Workspace directory containing prd/ and wiki/.")
    parser.add_argument("--mode", choices=["final-only"], default="final-only")
    parser.add_argument("--batch-id", default="", help="A/B batch id; defaults to goshawk-ab-YYYYmmdd_HHMMSS")
    parser.add_argument("--output-dir", default="", help="Report directory; defaults to workspace/output/goshawk_ab")
    parser.add_argument("--compact-chars", type=int, default=25000, help="Compact wiki character budget.")
    parser.add_argument(
        "--routes-file",
        default="",
        help="Optional model routes profile, e.g. model_routes.pro_cli.yaml.",
    )
    parser.add_argument(
        "--variant-order",
        default="full,compact",
        help="Execution order for variants: full,compact or compact,full.",
    )
    parser.add_argument("--record-langfuse", action="store_true", help="Write comparison scores to Langfuse.")
    return parser.parse_args(argv)


def variant_env(variant: str, *, compact_chars: int) -> Dict[str, str]:
    compact = "1" if str(variant).strip().lower() == "compact" else "0"
    return {
        "PECKER_GOSHAWK_COMPACT_WIKI": compact,
        "PECKER_GOSHAWK_WIKI_CHARS": str(max(0, int(compact_chars or 0))),
    }


def comparison_trace_id(summary: Mapping[str, Any]) -> str:
    for key in ("candidate", "baseline"):
        run = summary.get(key) if isinstance(summary, Mapping) else None
        trace = run.get("trace") if isinstance(run, Mapping) else None
        trace_id = trace.get("trace_id") if isinstance(trace, Mapping) else ""
        text = str(trace_id or "").strip().lower()
        if len(text) == 32 and all(char in "0123456789abcdef" for char in text):
            return text
    return ""


def normalize_variant_order(value: str) -> list[str]:
    raw = [part.strip().lower() for part in str(value or "").split(",") if part.strip()]
    if not raw:
        return ["full", "compact"]
    if sorted(raw) != ["compact", "full"] or len(raw) != 2:
        raise ValueError("--variant-order must be either full,compact or compact,full")
    return raw


async def run_final_only_goshawk_ab(
    *,
    workspace: Path,
    batch_id: str,
    output_dir: Path,
    compact_chars: int,
    record_langfuse: bool,
    routes_file: str = "",
    variant_order: str = "full,compact",
) -> Dict[str, Any]:
    _configure_routes_file(routes_file)
    _load_dotenv()
    from parallel_review import parallel_review, summarize_verification, verify_evidence

    prd_content, prd_files = load_prd_content(str(workspace))
    if not prd_content:
        raise RuntimeError(f"No PRD markdown found under {workspace / 'prd'}")
    wiki_path = workspace / "wiki"
    wiki_pages = load_wiki_pages(str(wiki_path)) if wiki_path.exists() else {}

    worker_started = time.time()
    worker_result = await parallel_review(
        None,
        prd_content,
        wiki_pages,
        MODEL_TIERS,
        wiki_path=str(wiki_path),
        workspace=str(workspace),
        thread_id=f"{batch_id}:workers",
    )
    worker_elapsed = time.time() - worker_started
    merged_items = worker_result.get("merged_items") or []
    verified_items = verify_evidence(
        merged_items,
        str(workspace),
        client=None,
        wiki_pages=wiki_pages,
        prd_content=prd_content,
    )

    variant_runs: Dict[str, Dict[str, Any]] = {}
    for variant in normalize_variant_order(variant_order):
        variant_runs[variant] = _run_goshawk_variant(
            variant=variant,
            batch_id=batch_id,
            workspace_label=str(workspace),
            prd_content=prd_content,
            wiki_pages=wiki_pages,
            source_items=verified_items,
            compact_chars=compact_chars,
        )
    full = variant_runs["full"]
    compact = variant_runs["compact"]
    summary = compare_goshawk_ab_runs(
        batch_id=batch_id,
        case_id=workspace.name,
        baseline=full,
        candidate=compact,
        source_items_count=len(verified_items),
    )
    payload: Dict[str, Any] = {
        "batch_id": batch_id,
        "workspace": str(workspace),
        "prd_files": prd_files,
        "prd_chars": len(prd_content),
        "wiki_pages_count": len(wiki_pages),
        "worker": {
            "elapsed_s": worker_elapsed,
            "merged_count": len(merged_items),
            "verified_count": len(verified_items),
            "usage": worker_result.get("total_usage") or {},
            "orchestrator": worker_result.get("orchestrator"),
            "observability": worker_result.get("observability") or {},
            "verification_summary": summarize_verification(verified_items),
        },
        "ab": summary,
    }
    if record_langfuse:
        payload["langfuse_scores"] = record_goshawk_ab_scores(
            summary,
            trace_id=comparison_trace_id(summary),
            session_id=batch_id,
        )
    paths = _write_reports(payload, output_dir)
    payload["report_paths"] = {key: str(value) for key, value in paths.items()}
    return payload


def _run_goshawk_variant(
    *,
    variant: str,
    batch_id: str,
    workspace_label: str,
    prd_content: str,
    wiki_pages: Mapping[str, str],
    source_items: list[Dict[str, Any]],
    compact_chars: int,
) -> Dict[str, Any]:
    from goshawk_advisor import advisor_review_default, apply_advisor_result
    from review.langfuse_observability import start_langgraph_review_trace

    source_copy = copy.deepcopy(source_items)
    compaction = _compaction_preview(
        variant=variant,
        wiki_pages=wiki_pages,
        prd_content=prd_content,
        source_items=source_copy,
        compact_chars=compact_chars,
    )
    trace = start_langgraph_review_trace(
        workspace=workspace_label,
        thread_id=f"{batch_id}:{variant}",
        prd_content=prd_content,
        wiki_pages=dict(wiki_pages),
        voting_rounds=1,
        dimensions=["goshawk_final"],
        trace_name=f"pecker.goshawk_ab.{variant}",
    )
    started = time.time()
    with patched_env(variant_env(variant, compact_chars=compact_chars)):
        with trace:
            with trace.span(
                "pecker.goshawk_ab.final_review",
                input={
                    "variant": variant,
                    "source_items_count": len(source_copy),
                    "wiki_pages_count": len(wiki_pages),
                    "compact_chars": compact_chars,
                },
                metadata={"batch_id": batch_id, "variant": variant},
                as_type="generation",
            ) as observation:
                result = advisor_review_default(None, prd_content, source_copy, dict(wiki_pages))
                final_items = apply_advisor_result(source_copy, result, wiki_pages=dict(wiki_pages), client=None)
                elapsed = time.time() - started
                run_payload = {
                    "variant": variant,
                    "elapsed_s": elapsed,
                    "usage": result.get("usage") or {},
                    "items": final_items,
                    "goshawk_result": result,
                    "compaction": compaction,
                }
                trace.update_observation(
                    observation,
                    output={
                        "elapsed_s": elapsed,
                        "items_count": len(final_items),
                        "usage": result.get("usage") or {},
                        "advisor": {
                            "verdict": result.get("verdict"),
                            "false_positive_count": len(result.get("flagged_as_false_positive") or []),
                            "additional_count": len(result.get("additional_findings") or []),
                            "conflict_count": len(result.get("conflict_resolutions") or []),
                        },
                    },
                    metadata={"compaction": compaction},
                )
            trace.finish(
                status="done",
                output={
                    "variant": variant,
                    "elapsed_s": run_payload["elapsed_s"],
                    "items_count": len(final_items),
                    "input_tokens": (result.get("usage") or {}).get("input_tokens"),
                    "output_tokens": (result.get("usage") or {}).get("output_tokens"),
                },
            )
    run_payload["trace"] = trace.snapshot()
    return run_payload


def _compaction_preview(
    *,
    variant: str,
    wiki_pages: Mapping[str, str],
    prd_content: str,
    source_items: list[Dict[str, Any]],
    compact_chars: int,
) -> Dict[str, Any]:
    from review.goshawk_wiki_compaction import compact_goshawk_wiki_pages

    if str(variant).strip().lower() != "compact":
        return {"enabled": False, "budget_chars": max(0, int(compact_chars or 0))}
    _pages, telemetry = compact_goshawk_wiki_pages(
        dict(wiki_pages),
        prd_content,
        source_items,
        max_chars=max(0, int(compact_chars or 0)),
    )
    return {
        "enabled": True,
        "budget_chars": int(telemetry.get("budget") or compact_chars or 0),
        "selected_count": len(telemetry.get("selected_titles") or []),
        "worker_union_count": int(telemetry.get("worker_union_count") or 0),
    }


@contextmanager
def patched_env(values: Mapping[str, str]) -> Iterator[None]:
    previous = {key: os.environ.get(key) for key in values}
    try:
        for key, value in values.items():
            os.environ[key] = str(value)
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _write_reports(payload: Mapping[str, Any], output_dir: Path) -> Dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    batch_id = _safe_file_stem(str(payload.get("batch_id") or "goshawk_ab"))
    json_path = output_dir / f"{batch_id}.json"
    md_path = output_dir / f"{batch_id}.summary.md"
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    md_path.write_text(_render_markdown(payload), encoding="utf-8")
    return {"json": json_path, "markdown": md_path}


def _render_markdown(payload: Mapping[str, Any]) -> str:
    ab = payload.get("ab") or {}
    metrics = ab.get("metrics") or {}
    worker = payload.get("worker") or {}
    baseline = ab.get("baseline") or {}
    candidate = ab.get("candidate") or {}
    lines = [
        "# Goshawk Final-Only A/B",
        "",
        f"- batch_id: `{payload.get('batch_id', '')}`",
        f"- workspace: `{payload.get('workspace', '')}`",
        f"- worker_verified_count: `{worker.get('verified_count', 0)}`",
        f"- worker_elapsed_s: `{float(worker.get('elapsed_s') or 0):.3f}`",
        f"- final_rule_jaccard: `{float(metrics.get('final_rule_jaccard') or 0):.4f}`",
        f"- final_signature_jaccard: `{float(metrics.get('final_signature_jaccard') or 0):.4f}`",
        f"- advisor_fp_jaccard: `{float(metrics.get('advisor_fp_jaccard') or 0):.4f}`",
        f"- false_positive_delta: `{float(metrics.get('false_positive_delta') or 0):.0f}`",
        f"- input_token_savings_ratio: `{float(metrics.get('input_token_savings_ratio') or 0):.4f}`",
        f"- elapsed_savings_ratio: `{float(metrics.get('elapsed_savings_ratio') or 0):.4f}`",
        f"- compact_pass: `{bool(metrics.get('compact_pass'))}`",
        "",
        "| variant | elapsed_s | input_tokens | output_tokens | items | fp | add | conflict |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in (baseline, candidate):
        usage = row.get("usage") or {}
        advisor = row.get("advisor") or {}
        lines.append(
            f"| {row.get('variant', '')} | {float(row.get('elapsed_s') or 0):.3f} | "
            f"{usage.get('input_tokens', 0)} | {usage.get('output_tokens', 0)} | "
            f"{row.get('items_count', 0)} | {advisor.get('false_positive_count', 0)} | "
            f"{advisor.get('additional_count', 0)} | {advisor.get('conflict_count', 0)} |"
        )
    lines.append("")
    return "\n".join(lines)


def _safe_file_stem(value: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in value.strip())
    return safe or "goshawk_ab"


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
    except Exception:  # noqa: BLE001
        return
    load_dotenv(ROOT / ".env", override=False)


def _configure_routes_file(routes_file: str) -> None:
    raw = str(routes_file or "").strip()
    if not raw:
        return
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = ROOT / path
    os.environ["PECKER_ROUTES_FILE"] = str(path)
    try:
        from model_router import reset_config_cache

        reset_config_cache()
    except Exception:  # noqa: BLE001
        return


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    workspace = Path(args.workspace).expanduser().resolve()
    batch_id = args.batch_id.strip() or time.strftime("goshawk-ab-%Y%m%d_%H%M%S")
    output_dir = (
        Path(args.output_dir).expanduser().resolve()
        if args.output_dir
        else workspace / "output" / "goshawk_ab"
    )
    try:
        payload = asyncio.run(
            run_final_only_goshawk_ab(
                workspace=workspace,
                batch_id=batch_id,
                output_dir=output_dir,
                compact_chars=args.compact_chars,
                record_langfuse=args.record_langfuse,
                routes_file=args.routes_file,
                variant_order=args.variant_order,
            )
        )
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    print(
        json.dumps(
            {
                "ok": True,
                "batch_id": payload["batch_id"],
                "metrics": (payload.get("ab") or {}).get("metrics") or {},
                "report_paths": payload.get("report_paths") or {},
                "langfuse_scores": payload.get("langfuse_scores"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
