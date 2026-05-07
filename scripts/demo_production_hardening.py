"""一站式 demo: 跑通 Part 1/2/3, 输出 dashboard.html 样本.

跑法:
    python scripts/demo_production_hardening.py
    # 或指定输出目录:
    python scripts/demo_production_hardening.py --workspace /tmp/hardening-demo

产物:
    <workspace>/learnings.db        — sqlite (50 条 mock learning, 10 thread 并发写)
    <workspace>/metrics.db          — sqlite (5 个 mock review session events)
    <workspace>/dashboard.html      — 静态可视化
    <workspace>/llm_route_health.json — LLM 路由健康检查结果
    <workspace>/demo_report.json    — 整体 demo 摘要

一定 idempotent: 跑多次没副作用 (会清空 workspace 重来).
"""
from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import subprocess
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from review.learnings_store import LearningsStore  # noqa: E402
from review.metrics_store import record_event, get_summary  # noqa: E402


def _print_block(title: str) -> None:
    print(f"\n{'=' * 60}\n  {title}\n{'=' * 60}")


def _step1_concurrent_learnings(workspace: str) -> dict:
    _print_block("Part 1: Learnings 并发安全 (10 thread × 5 add)")
    store = LearningsStore(workspace)
    errors: list[str] = []

    def worker(tid: int):
        try:
            ls = LearningsStore(workspace)
            for i in range(5):
                ls.add(
                    trigger_pattern=f"当 PRD 涉及功能-{tid}-{i} 时",
                    instruction=f"按 v2 规则 {tid}-{i} 处理",
                    scope=random.choice(["pr_local", "team_local", "org_global"]),
                    reviewer=f"pm-{tid}",
                    dim_keys=["rule_check", "consistency"],
                )
        except Exception as e:  # noqa: BLE001
            errors.append(f"{tid}: {e}")

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
    t0 = time.time()
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    elapsed = time.time() - t0

    rows = store.list_all()
    print(f"  并发写完成: {len(rows)}/50 条, 耗时 {elapsed:.2f}s, 错误数 {len(errors)}")
    print(f"  scopes 分布: {[(s, sum(1 for r in rows if r.scope == s)) for s in ['pr_local','team_local','org_global']]}")

    # demo yaml export
    yaml_dir = os.path.join(workspace, "learnings_export")
    n = store.export_yaml(yaml_dir)
    print(f"  yaml 导出: {n} 条 → {yaml_dir}")

    return {
        "rows": len(rows),
        "errors": errors,
        "elapsed_s": round(elapsed, 2),
        "yaml_export_count": n,
    }


def _step2_llm_route_health(workspace: str) -> dict:
    _print_block("Part 2: LLM 路由健康检查 (无副作用)")
    out_path = os.path.join(workspace, "llm_route_health.json")
    from api.main import _validate_llm_runtime  # type: ignore

    errors, warnings, auth = _validate_llm_runtime()
    report = {
        "status": auth.get("status", "unknown"),
        "active_routes": auth.get("active_routes", []),
        "routes_file": auth.get("routes_file", ""),
        "errors": errors,
        "warnings": warnings,
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"  status: {report['status']}")
    print(f"  active_routes: {', '.join(report['active_routes'])}")
    if errors:
        print(f"  errors: {len(errors)}")
    if warnings:
        print(f"  warnings: {len(warnings)}")
    print(f"  报告写出: {out_path}")
    return report


def _step3_metrics_and_dashboard(workspace: str) -> dict:
    _print_block("Part 3: Observability — mock 5 review + 渲染 dashboard")
    db = os.path.join(workspace, "metrics.db")
    os.environ["METRICS_DB_PATH"] = db

    # mock 5 个 review session
    for sid in range(5):
        record_event("review.started", workspace=workspace, reviewer=f"pm-{sid}",
                     details={"voting_rounds": 1}, db_path=db)
        # 4 个 worker
        for dim in ["rule_check", "consistency", "completeness", "implementability"]:
            duration = random.randint(8000, 25000)
            cost = round(random.uniform(0.005, 0.03), 4)
            status = "success" if random.random() > 0.1 else "failed"
            record_event("worker.completed",
                         workspace=workspace, reviewer=f"pm-{sid}",
                         duration_ms=duration,
                         model=random.choice(["gpt-5.5", "gpt-5.5", "gpt-5"]),
                         cost_usd=cost, status=status,
                         details={"dim_key": dim, "items": random.randint(2, 8),
                                 "vendor": "openai"},
                         db_path=db)
        # 苍鹰 + final
        record_event("goshawk.completed", workspace=workspace,
                     duration_ms=random.randint(15000, 40000),
                     model="gpt-5.5",
                     cost_usd=round(random.uniform(0.04, 0.10), 4),
                     status="success",
                     details={"verdict": random.choice(["approved", "needs_revision"]),
                              "confidence": round(random.uniform(0.7, 0.95), 2)},
                     db_path=db)
        review_duration = random.randint(60000, 180000)
        record_event("review.completed", workspace=workspace, reviewer=f"pm-{sid}",
                     duration_ms=review_duration,
                     cost_usd=round(random.uniform(0.15, 0.40), 4),
                     status="success",
                     details={"merged_items": random.randint(5, 15)},
                     db_path=db)
        # 随机一次 LLM 调用
        record_event("llm.api_call", workspace=workspace,
                     model="gpt-5.5-mini",
                     duration_ms=random.randint(800, 2500),
                     cost_usd=round(random.uniform(0.0001, 0.001), 5),
                     status="success",
                     details={"vendor": "openai", "tokens": random.randint(500, 5000)},
                     db_path=db)

    # 注一条 oauth 事件
    record_event("provider.health_check", model="gpt-5.5", status="success",
                 details={"provider": "openai", "checked": True}, db_path=db)

    summary = get_summary(db, days=7)
    print(f"  KPI 7d: reviews={summary['reviews']} errors={summary['errors']} "
          f"cost=${summary['total_cost_usd']:.3f} avg={summary['avg_review_ms']/1000:.1f}s")

    # 渲染 dashboard
    out_html = os.path.join(workspace, "dashboard.html")
    cmd = [
        sys.executable,
        os.path.join(ROOT, "scripts", "render_metrics_dashboard.py"),
        "--db", db,
        "--out", out_html,
        "--days", "30",
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        print(f"  [WARN] dashboard 渲染失败: {r.stderr[:200]}")
    else:
        print(f"  dashboard 渲染成功 ({os.path.getsize(out_html)} bytes) → {out_html}")

    return {
        "db": db,
        "dashboard": out_html,
        "summary": summary,
        "render_rc": r.returncode,
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--workspace", default=None,
                   help="workspace 目录, 默认 ./workspace_hardening_demo")
    p.add_argument("--keep", action="store_true",
                   help="保留旧 workspace (默认会清空)")
    args = p.parse_args()

    workspace = args.workspace or os.path.join(ROOT, "workspace_hardening_demo")
    if not args.keep and os.path.isdir(workspace):
        shutil.rmtree(workspace)
    os.makedirs(workspace, exist_ok=True)

    report = {
        "workspace": workspace,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    report["part1_learnings"] = _step1_concurrent_learnings(workspace)
    report["part2_llm_route"] = _step2_llm_route_health(workspace)
    report["part3_metrics"] = _step3_metrics_and_dashboard(workspace)
    report["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")

    out = os.path.join(workspace, "demo_report.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    _print_block("DEMO 完成")
    print(f"  Workspace : {workspace}")
    print(f"  Dashboard : {report['part3_metrics']['dashboard']}")
    print(f"  Demo Report: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
