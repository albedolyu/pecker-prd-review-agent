"""候选 route 准入门槛判定脚本.

模式 1 -- 单 route 候选 vs baseline matrix:
    python scripts/eval_admission.py --route=advisor.goshawk \
        --candidate-vendor=openai --candidate-model=pro \
        --baseline=eval_reports/baseline_matrix_<ts>.md \
        [--runs=3] [--dry-run]

模式 2 -- 两份 baseline 对比 (改造前 vs 改造后):
    python scripts/eval_admission.py --compare baseline_pre.md baseline_post.md

输出: eval_reports/route_admission_<route_id>_<vendor>_<model>_<ts>.md
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any, Dict, List, Optional

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def _load_baseline_json(md_or_json_path: str) -> List[Dict[str, Any]]:
    """从 baseline_matrix_*.md 旁边找同名 .json, 加载 routes list."""
    if md_or_json_path.endswith(".json"):
        json_path = md_or_json_path
    else:
        json_path = md_or_json_path.rsplit(".", 1)[0] + ".json"

    if not os.path.exists(json_path):
        raise FileNotFoundError(
            f"baseline 配套 json 不存在: {json_path} "
            f"(eval_baseline.py 应同时写 md + json)"
        )
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("routes", [])


def _find_baseline_for_route(routes: List[Dict[str, Any]], route_id: str) -> Optional[Dict[str, Any]]:
    for r in routes:
        if r.get("route_id") == route_id:
            return r
    return None


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


def _mode_admit(args) -> int:
    """模式 1: 跑候选 + 加载 baseline + admit + 写报告."""
    from eval.route_eval import admission, runner, report

    print(f"[eval_admission] mode=admit route={args.route} "
          f"candidate={args.candidate_vendor}:{args.candidate_model}")

    baseline_routes = _load_baseline_json(args.baseline)
    baseline = _find_baseline_for_route(baseline_routes, args.route)
    if baseline is None:
        print(f"  [error] baseline 中无 {args.route!r} 的记录, 先跑 eval_baseline.py")
        return 1

    print(f"  baseline: {baseline.get('vendor')}:{baseline.get('model')} "
          f"F1={baseline.get('capability', {}).get('f1', 0):.3f}")

    dataset_name = _auto_dataset(args.route)
    candidate = runner.run_route_eval(
        route_id=args.route,
        vendor=args.candidate_vendor,
        model=args.candidate_model,
        runs=args.runs,
        dataset_name=dataset_name,
        dry_run=args.dry_run,
    )

    decision = admission.admit(
        candidate_metrics=candidate["metrics"],
        baseline_metrics=baseline.get("metrics", baseline),
        route_id=args.route,
    )

    ts = time.strftime("%Y%m%d_%H%M%S")
    safe_rid = args.route.replace(".", "_")
    out_md = f"eval_reports/route_admission_{safe_rid}_{args.candidate_vendor}_{args.candidate_model}_{ts}.md"
    report.write_admission_report(
        admission_result=decision,
        candidate_metrics=candidate,
        baseline_metrics=baseline,
        output_path=out_md,
    )

    verdict = "PASS" if decision["pass"] else "FAIL"
    print(f"\n[eval_admission] {verdict}")
    if decision["fail_reasons"]:
        for r in decision["fail_reasons"]:
            print(f"  - {r}")
    print(f"  报告 -> {out_md}")
    return 0 if decision["pass"] else 2


def _mode_compare(args) -> int:
    """模式 2: pre vs post baseline 对比, 每个 route 跑 admission 形成总览."""
    from eval.route_eval import admission, report

    print(f"[eval_admission] mode=compare {args.compare[0]} vs {args.compare[1]}")
    pre = {r["route_id"]: r for r in _load_baseline_json(args.compare[0])}
    post = {r["route_id"]: r for r in _load_baseline_json(args.compare[1])}

    common = sorted(set(pre.keys()) & set(post.keys()))
    if not common:
        print("  [error] 两份 baseline 无共同 route_id")
        return 1

    print(f"  共 {len(common)} 个 route 共享, 逐个对比...")

    overall_pass = True
    summary_lines = [
        f"# Baseline Compare: {os.path.basename(args.compare[0])} vs {os.path.basename(args.compare[1])}",
        "",
        f"- 生成时间: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 共同 routes: {len(common)}",
        "",
        "| route_id | F1 delta | Recall delta | Overlap delta | p95 ratio | $ ratio | 判定 |",
        "|---|---|---|---|---|---|---|",
    ]

    for rid in common:
        pre_m = pre[rid].get("metrics", pre[rid])
        post_m = post[rid].get("metrics", post[rid])
        decision = admission.admit(
            candidate_metrics=post_m,
            baseline_metrics=pre_m,
            route_id=rid,
        )
        d = decision["deltas"]
        verdict = "PASS" if decision["pass"] else "FAIL"
        if not decision["pass"]:
            overall_pass = False
        summary_lines.append(
            f"| {rid} | {d.get('f1', 0):+.3f} | {d.get('recall', 0):+.3f} | "
            f"{d.get('overlap', 0):+.3f} | {d.get('p95_ratio', 0):.2f} | "
            f"{d.get('cost_ratio', 0):.2f} | {verdict} |"
        )
        if not decision["pass"]:
            summary_lines.append(f"|   *fail*: {'; '.join(decision['fail_reasons'])} | | | | | | |")

    summary_lines.append("")
    summary_lines.append(f"**整体判定**: {'PASS' if overall_pass else 'FAIL'}")
    summary_lines.append("")

    ts = time.strftime("%Y%m%d_%H%M%S")
    out_md = f"eval_reports/baseline_compare_{ts}.md"
    os.makedirs(os.path.dirname(os.path.abspath(out_md)), exist_ok=True)
    with open(out_md, "w", encoding="utf-8") as f:
        f.write("\n".join(summary_lines))

    verdict = "PASS" if overall_pass else "FAIL"
    print(f"\n[eval_admission] compare {verdict}, 报告 -> {out_md}")
    return 0 if overall_pass else 2


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="eval_admission",
        description="候选 route 准入门槛判定 (模式 1: 单 route admit; 模式 2: 两份 baseline 对比).",
    )
    parser.add_argument("--route", help="route_id, e.g. advisor.goshawk (模式 1 必填)")
    parser.add_argument("--candidate-vendor", help="候选 vendor (模式 1 必填)")
    parser.add_argument("--candidate-model", help="候选 model tier (模式 1 必填)")
    parser.add_argument("--baseline", help="baseline matrix md/json 路径 (模式 1 必填)")
    parser.add_argument("--runs", type=int, default=3, help="候选评测轮次 (默认 3)")
    parser.add_argument("--dry-run", action="store_true", help="dry-run 模式")

    parser.add_argument("--compare", nargs=2, metavar=("PRE_MD", "POST_MD"),
                        help="模式 2: 对比两份 baseline matrix")

    args = parser.parse_args(argv)

    if args.compare:
        return _mode_compare(args)

    # 模式 1 校验
    missing = [n for n in ("route", "candidate_vendor", "candidate_model", "baseline")
               if getattr(args, n) is None]
    if missing:
        parser.error(f"模式 1 缺必填参数: {missing}; 或用 --compare PRE POST 走模式 2")

    return _mode_admit(args)


if __name__ == "__main__":
    sys.exit(main())
