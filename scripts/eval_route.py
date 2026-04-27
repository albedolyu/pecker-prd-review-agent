"""单 route 评测脚本.

用法:
    python scripts/eval_route.py <route_id> --vendor=anthropic --model=sonnet \
        --runs=3 [--dataset=auto] [--dry-run] [--output=eval_reports/]

dataset=auto 时按 route_id 自动选数据集:
    worker.*       -> business_prd_gt
    advisor.*      -> advisor_conflicts
    verify.nli     -> hallucination
    router.intent  -> intent
    其他           -> business_prd_gt (兜底)

输出:
    <output>/<route_id>_<vendor>_<model>_<ts>.json
    <output>/<route_id>_<vendor>_<model>_<ts>.md
"""
from __future__ import annotations

import argparse
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def _auto_dataset(route_id: str) -> str:
    if route_id.startswith("worker."):
        return "business_prd_gt"
    if route_id.startswith("advisor."):
        return "advisor_conflicts"
    if route_id == "verify.nli":
        return "hallucination"
    if route_id == "router.intent":
        return "intent"
    return "business_prd_gt"


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="eval_route",
        description="单 route 5 维度评测 (capability/stability/cost/failures + 可选 cross_vendor).",
    )
    parser.add_argument("route_id", help="route_id, e.g. advisor.goshawk / worker.compliance")
    parser.add_argument("--vendor", default="anthropic", help="vendor 名 (默认 anthropic)")
    parser.add_argument("--model", default="sonnet", help="model tier (默认 sonnet)")
    parser.add_argument("--runs", type=int, default=3, help="评测轮次 (默认 3)")
    parser.add_argument("--dataset", default="auto",
                        help="数据集名: auto/business_prd_gt/template_prd/advisor_conflicts/hallucination/intent")
    parser.add_argument("--dry-run", action="store_true",
                        help="不真发请求, 用 _FakeResponse 跑通 pipeline")
    parser.add_argument("--output", default="eval_reports",
                        help="报告输出目录 (默认 eval_reports/)")

    args = parser.parse_args(argv)

    dataset_name = _auto_dataset(args.route_id) if args.dataset == "auto" else args.dataset
    print(f"[eval_route] route_id={args.route_id} vendor={args.vendor} model={args.model} "
          f"runs={args.runs} dataset={dataset_name} dry_run={args.dry_run}")

    from eval.route_eval import runner, report

    result = runner.run_route_eval(
        route_id=args.route_id,
        vendor=args.vendor,
        model=args.model,
        runs=args.runs,
        dataset_name=dataset_name,
        dry_run=args.dry_run,
    )

    ts = time.strftime("%Y%m%d_%H%M%S")
    safe_rid = args.route_id.replace(".", "_").replace("/", "_")
    base = f"{safe_rid}_{args.vendor}_{args.model}_{ts}"
    md_path = os.path.join(args.output, f"{base}.md")
    json_path = os.path.join(args.output, f"{base}.json")

    report.write_route_report(result, md_path, json_path)
    print(f"[eval_route] PASS")
    print(f"  md   -> {md_path}")
    print(f"  json -> {json_path}")
    print(f"  capability: P={result['capability']['p']:.3f} R={result['capability']['r']:.3f} "
          f"F1={result['capability']['f1']:.3f}")
    print(f"  stability: overlap={result['stability']['overlap']:.3f} "
          f"sampling_cv={result['stability']['sampling_cv']:.3f}")
    print(f"  cost: ${result['cost_latency']['cost_usd_per_run']:.6f}/run "
          f"p95={result['cost_latency']['p95_ms']:.0f}ms")
    return 0


if __name__ == "__main__":
    sys.exit(main())
