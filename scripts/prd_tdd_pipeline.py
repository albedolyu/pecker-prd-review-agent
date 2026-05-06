from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


ReviewRunner = Callable[..., Any]
WeaveRunner = Callable[..., Path]
QualityGateChecker = Callable[..., Any]
GatewayFactory = Callable[[Path], Any]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def build_verdict_payload(
    review_payload: dict[str, Any],
    *,
    prd_id: str,
    prd_path: str | Path,
) -> dict[str, Any]:
    valid_items = _valid_review_items(review_payload)
    failed_workers = list((review_payload.get("completion") or {}).get("failed_workers") or [])
    must_count = sum(1 for item in valid_items if str(item.get("severity") or "").lower() == "must")
    should_count = sum(1 for item in valid_items if str(item.get("severity") or "").lower() == "should")
    retracted_count = _retracted_count(review_payload)
    verdict = "needs_revision" if failed_workers or must_count or retracted_count else "approved"
    return {
        "prd_id": prd_id,
        "prd_version": utc_now()[:10],
        "verdict": verdict,
        "agent": "pecker gpt direct review",
        "timestamp": utc_now(),
        "prd_path": str(Path(prd_path).resolve(strict=False)),
        "failed_workers": failed_workers,
        "must_count": must_count,
        "should_count": should_count,
        "retracted_count": retracted_count,
        "items": valid_items,
        "source_review": {
            "report_paths": review_payload.get("report_paths") or {},
            "completion": review_payload.get("completion") or {},
            "verification_summary": review_payload.get("verification_summary") or {},
        },
    }


def run_pipeline(
    *,
    workspace: str | Path,
    zhique_root: str | Path,
    test_output_root: str | Path,
    knowledge_root: str | Path,
    prd_id: str | None = None,
    output_dir: str | Path | None = None,
    label: str | None = None,
    mode: str = "deep",
    serial_workers: bool = False,
    review_runner: ReviewRunner | None = None,
    weave_runner: WeaveRunner | None = None,
    quality_gate_checker: QualityGateChecker | None = None,
    gateway_factory: GatewayFactory | None = None,
) -> dict[str, Any]:
    workspace = Path(workspace).expanduser().resolve(strict=False)
    zhique_root = Path(zhique_root).expanduser().resolve(strict=False)
    test_output_root = Path(test_output_root).expanduser().resolve(strict=False)
    knowledge_root = Path(knowledge_root).expanduser().resolve(strict=False)
    output_dir = Path(output_dir).expanduser().resolve(strict=False) if output_dir else workspace / "output" / "prd-tdd-pipeline"
    output_dir.mkdir(parents=True, exist_ok=True)

    review_payload = _run_review(
        review_runner=review_runner,
        workspace=workspace,
        output_dir=output_dir / "pecker",
        label=label or prd_id or workspace.name,
        mode=mode,
    )
    prd_path = _resolve_prd_path(workspace, review_payload)
    final_prd_id = prd_id or _default_prd_id(workspace)
    verdict_payload = build_verdict_payload(review_payload, prd_id=final_prd_id, prd_path=prd_path)
    verdict_path = output_dir / "verdict.json"
    _write_json(verdict_path, verdict_payload)

    result: dict[str, Any] = {
        "ok": False,
        "workspace": str(workspace),
        "pecker": {
            "verdict": verdict_payload["verdict"],
            "verdict_path": str(verdict_path),
            "must_count": verdict_payload["must_count"],
            "should_count": verdict_payload["should_count"],
            "failed_workers": verdict_payload["failed_workers"],
        },
        "zhique": None,
        "paths": {
            "pipeline_result": str(output_dir / "pipeline_result.json"),
            "pipeline_report": str(output_dir / "pipeline_report.md"),
        },
    }
    if verdict_payload["verdict"] != "approved":
        _write_pipeline_outputs(output_dir, result)
        return result

    deps = _load_zhique_dependencies(
        zhique_root=zhique_root,
        need_weave=weave_runner is None,
        need_gate=quality_gate_checker is None,
        need_gateway=gateway_factory is None,
    )
    if weave_runner is None:
        weave_runner = deps["weave_runner"]
    if quality_gate_checker is None:
        quality_gate_checker = deps["quality_gate_checker"]
    if gateway_factory is None:
        gateway_factory = deps["gateway_factory"]
    run_log_path = output_dir / "zhique-codex.events.jsonl"
    if run_log_path.exists():
        run_log_path.unlink()
    run_log = deps["run_log_factory"](run_log_path) if deps.get("run_log_factory") else None

    zhique_output_dir = Path(
        weave_runner(
            prd_path=prd_path,
            woodpecker_report_path=verdict_path,
            output_root=test_output_root,
            knowledge_root=knowledge_root,
            model_gateway=gateway_factory(ROOT),
            parallel_workers=not serial_workers,
            run_log=run_log,
        )
    )
    gate_result = quality_gate_checker(zhique_output_dir, run_log_path=run_log_path)
    gate_payload = gate_result.to_dict() if hasattr(gate_result, "to_dict") else dict(gate_result)
    result["ok"] = bool(gate_payload.get("ok"))
    result["zhique"] = {
        "output_dir": str(zhique_output_dir),
        "quality_gate": gate_payload,
        "run_log": str(run_log_path),
    }
    _write_pipeline_outputs(output_dir, result)
    return result


def _run_review(
    *,
    review_runner: ReviewRunner | None,
    workspace: Path,
    output_dir: Path,
    label: str,
    mode: str,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    runner = review_runner or _default_review_runner
    result = runner(workspace=workspace, label=label, output_dir=output_dir, verify=True, mode=mode)
    if inspect.isawaitable(result):
        result = asyncio.run(result)
    if not isinstance(result, dict):
        raise TypeError("review_runner must return a dict payload")
    return result


async def _default_review_runner(**kwargs: Any) -> dict[str, Any]:
    from scripts.run_review_case import run_case

    return await run_case(**kwargs)


def _load_zhique_dependencies(
    *,
    zhique_root: Path,
    need_weave: bool,
    need_gate: bool,
    need_gateway: bool,
) -> dict[str, Any]:
    if str(zhique_root) not in sys.path:
        sys.path.insert(0, str(zhique_root))
    deps: dict[str, Any] = {}
    if need_weave:
        from zhique.agent.orchestrator import weave_test_cases

        deps["weave_runner"] = weave_test_cases
    if need_gate:
        from zhique.eval.quality_gate import check_quality_gate

        deps["quality_gate_checker"] = check_quality_gate
    if need_gateway:
        from zhique.agent.pecker_codex_gateway import CodexPeckerGateway

        deps["gateway_factory"] = lambda pecker_root: CodexPeckerGateway(pecker_root=pecker_root)
    try:
        from zhique.runtime.run_log import RunEventLog

        deps["run_log_factory"] = RunEventLog
    except Exception:
        deps["run_log_factory"] = None
    return deps


def _resolve_prd_path(workspace: Path, review_payload: dict[str, Any]) -> Path:
    prd_files = review_payload.get("prd_files") or []
    if prd_files:
        candidate = workspace / "prd" / str(prd_files[0])
        if candidate.exists():
            return candidate
    candidates = sorted((workspace / "prd").glob("*.md"))
    if not candidates:
        raise RuntimeError(f"No PRD markdown found under {workspace / 'prd'}")
    return candidates[0]


def _default_prd_id(workspace: Path) -> str:
    raw = workspace.name.upper().replace("_", "-")
    safe = "".join(ch if ch.isalnum() or ch == "-" else "-" for ch in raw)
    while "--" in safe:
        safe = safe.replace("--", "-")
    return safe.strip("-") or "PRD-CODEX"


def _valid_review_items(review_payload: dict[str, Any]) -> list[dict[str, Any]]:
    items = review_payload.get("verified_items") or review_payload.get("items") or []
    return [
        item
        for item in items
        if isinstance(item, dict) and str(item.get("status") or "").upper() != "RETRACTED"
    ]


def _retracted_count(review_payload: dict[str, Any]) -> int:
    items = review_payload.get("verified_items") or []
    explicit = sum(
        1
        for item in items
        if isinstance(item, dict) and str(item.get("status") or "").upper() == "RETRACTED"
    )
    summary = review_payload.get("verification_summary") or {}
    try:
        return max(explicit, int(summary.get("retracted", 0) or 0))
    except (TypeError, ValueError):
        return explicit


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _write_pipeline_outputs(output_dir: Path, result: dict[str, Any]) -> None:
    _write_json(output_dir / "pipeline_result.json", result)
    (output_dir / "pipeline_report.md").write_text(_render_pipeline_report(result), encoding="utf-8")


def _render_pipeline_report(result: dict[str, Any]) -> str:
    lines = [
        "# Pecker PRD TDD Pipeline",
        "",
        f"- Overall ok: {str(result.get('ok')).lower()}",
        f"- Pecker verdict: {result.get('pecker', {}).get('verdict')}",
    ]
    zhique = result.get("zhique")
    if zhique:
        gate = zhique.get("quality_gate") or {}
        lines.extend(
            [
                f"- Zhique output: {zhique.get('output_dir')}",
                f"- Zhique quality gate: {str(gate.get('ok')).lower()}",
            ]
        )
    else:
        lines.append("- Zhique output: skipped")
    lines.append("")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Pecker GPT review, then Zhique TDD case generation.")
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--zhique-root", type=Path, default=Path.home() / "Desktop" / "\u4ee3\u7801\u9879\u76ee" / "zhique")
    parser.add_argument("--test-output-root", type=Path, default=Path.home() / "Desktop" / "\u4ee3\u7801\u9879\u76ee" / "test-cases")
    parser.add_argument("--knowledge-root", type=Path, default=Path.home() / "Desktop" / "\u4ee3\u7801\u9879\u76ee" / "fengniao-knowledge")
    parser.add_argument("--prd-id", default=None)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--label", default=None)
    parser.add_argument("--mode", choices=["deep", "light"], default="deep")
    parser.add_argument("--serial-workers", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = run_pipeline(
        workspace=args.workspace,
        zhique_root=args.zhique_root,
        test_output_root=args.test_output_root,
        knowledge_root=args.knowledge_root,
        prd_id=args.prd_id,
        output_dir=args.output_dir,
        label=args.label,
        mode=args.mode,
        serial_workers=args.serial_workers,
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(result["paths"]["pipeline_result"])
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
