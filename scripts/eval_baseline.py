"""Baseline matrix 评测 -- 全 route × 当前默认 vendor/model 跑一遍.

用法:
    python scripts/eval_baseline.py [--routes=all|comma-separated] [--runs=3] \
        [--dry-run] [--output=eval_reports/baseline_matrix_<ts>.md]

routes=all 时从 model_router.list_routes() 拉全表; comma-separated 形如
``worker.compliance,advisor.goshawk,verify.nli``.

输出: 单一 baseline matrix md + 对应 json 备份.
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


def _resolve_routes(spec: str):
    """spec=all -> list_routes(); 否则按逗号切分."""
    if spec == "all":
        from model_router import list_routes
        return list_routes()
    return [r.strip() for r in spec.split(",") if r.strip()]


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="eval_baseline",
        description="生成 baseline matrix -- 全 route 当前默认配置 5 维度全表.",
    )
    parser.add_argument("--routes", default="all",
                        help="all 或逗号分隔的 route_id list (默认 all)")
    parser.add_argument("--runs", type=int, default=3, help="每个 route 的评测轮次 (默认 3)")
    parser.add_argument("--dry-run", action="store_true",
                        help="不真发请求, 用 _FakeResponse 跑通 pipeline")
    parser.add_argument("--output", default=None,
                        help="md 输出路径 (默认 eval_reports/baseline_matrix_<ts>.md)")

    args = parser.parse_args(argv)
    ts = time.strftime("%Y%m%d_%H%M%S")
    output = args.output or f"eval_reports/baseline_matrix_{ts}.md"

    routes = _resolve_routes(args.routes)
    print(f"[eval_baseline] 跑 {len(routes)} 个 route × {args.runs} runs (dry_run={args.dry_run})")

    from eval.route_eval import runner, report
    from model_router import get_route_meta

    all_metrics = []
    for rid in routes:
        try:
            meta = get_route_meta(rid)
            vendor = meta["vendor"]
            tier = meta["tier"]
        except Exception as e:
            print(f"  [skip] {rid}: route 无法解析 ({type(e).__name__}: {e})")
            continue

        dataset_name = _auto_dataset(rid)
        print(f"  -> {rid} @ {vendor}:{tier} dataset={dataset_name}")
        try:
            result = runner.run_route_eval(
                route_id=rid,
                vendor=vendor,
                model=tier,
                runs=args.runs,
                dataset_name=dataset_name,
                dry_run=args.dry_run,
            )
            all_metrics.append(result)
        except Exception as e:
            print(f"     [error] {type(e).__name__}: {e}")
            continue

    if not all_metrics:
        print("[eval_baseline] FAIL: 没有任何 route 跑成功")
        return 1

    report.write_baseline_matrix(all_metrics, output)
    print(f"\n[eval_baseline] PASS, {len(all_metrics)} routes 已写入:")
    print(f"  md   -> {output}")
    print(f"  json -> {output.rsplit('.', 1)[0]}.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
