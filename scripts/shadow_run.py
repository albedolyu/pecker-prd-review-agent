"""
Shadow test runner — 批量跑 run_session.py 采集一致性基线

目标: 连续跑 N 次评审 (默认 50),统计:
- 空 run 比例 (4 worker 全 0 items)
- 每个 worker 的静默率
- items 分布
- 失败类型分布 (quota / JSON / timeout / other)

用法:
    # 先配好一个 workspace (prd/ 里有 .md, wiki/ 有知识库)
    python scripts/shadow_run.py --workspace workspace-对外投资 --runs 50
    python scripts/shadow_run.py --workspace workspace-对外投资 --runs 50 --concurrent 2

结果:
- 原始日志: logs/shadow_<timestamp>/run_XX.log
- 聚合报告: logs/shadow_<timestamp>/report.json + report.md

CI 用法: 每周跑一次,把 report.md 追加到 STATUS.md,失败则 exit 1 阻塞合入。
"""

import argparse
import concurrent.futures
import json
import os
import re
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _glob_sessions_before(workspace: Path):
    """返回 run 前已有的 session 文件集合,用来识别新产生的 session."""
    return set((workspace / "output" / "sessions").glob("*.jsonl")) if (workspace / "output" / "sessions").exists() else set()


def _parse_session_events(jsonl_path: Path) -> dict:
    """从 jsonl 抽取一次 run 的关键指标."""
    try:
        events = [json.loads(l) for l in jsonl_path.read_text(encoding="utf-8",
                                                              errors="replace").strip().split("\n") if l]
    except (json.JSONDecodeError, OSError):
        return {"path": str(jsonl_path), "parse_error": True}

    worker_dones = [e for e in events if e.get("type") == "worker_done"]
    dims = {}
    for w in worker_dones:
        dim = w.get("dim", "?")
        dims[dim] = {"items": w.get("items_count", 0) or 0, "error": w.get("error")}
    total_items = sum(d["items"] for d in dims.values())
    return {
        "path": str(jsonl_path),
        "dims": dims,
        "total_items": total_items,
        "empty": total_items == 0,
    }


def _classify_error(stderr: str) -> str:
    """把 run 失败日志归类."""
    s = stderr.lower()
    if "quotaexhaust" in s or "hit your limit" in s or "usage limit" in s:
        return "quota"
    # Round 15: CLI OAuth token 失效 (常见于多 Claude Code 进程并发时)
    if 'api_error_status":401' in s or "authentication_error" in s \
       or "invalid authentication" in s or "failed to authenticate" in s:
        return "auth_401"
    if "json" in s and ("decode" in s or "parse" in s):
        return "json"
    if "timeout" in s or "agenttimeout" in s:
        return "timeout"
    if "filenotfound" in s or "not found" in s:
        return "missing_binary"
    if stderr.strip() == "":
        return "none"
    return "other"


def run_once(workspace: Path, log_dir: Path, run_idx: int, timeout: int) -> dict:
    """跑一次 run_session.py,非交互模式,采集产生的 session 事件."""
    before = _glob_sessions_before(workspace)
    log_path = log_dir / f"run_{run_idx:03d}.log"

    env = os.environ.copy()
    env["PECKER_NONINTERACTIVE"] = "1"

    started = time.time()
    try:
        with open(log_path, "w", encoding="utf-8") as lf:
            proc = subprocess.run(
                [sys.executable, "run_session.py", f"shadow_{run_idx}",
                 "--workspace", str(workspace), "--non-interactive",
                 "--auto-decide", "reject-all"],
                cwd=ROOT, env=env, stdout=lf, stderr=subprocess.STDOUT,
                timeout=timeout,
            )
        elapsed = time.time() - started
        returncode = proc.returncode
    except subprocess.TimeoutExpired:
        elapsed = time.time() - started
        returncode = -1

    stderr_tail = log_path.read_text(encoding="utf-8", errors="replace")[-2000:] if log_path.exists() else ""

    after = _glob_sessions_before(workspace)
    new_sessions = after - before
    session_info = _parse_session_events(sorted(new_sessions)[0]) if new_sessions else {"no_session": True}

    return {
        "run_idx": run_idx,
        "returncode": returncode,
        "elapsed_s": round(elapsed, 1),
        "error_class": _classify_error(stderr_tail) if returncode != 0 else "none",
        "session": session_info,
    }


def aggregate(results: list) -> dict:
    total = len(results)
    passed = sum(1 for r in results if r["returncode"] == 0)
    empty_runs = sum(1 for r in results if r.get("session", {}).get("empty"))
    error_classes = Counter(r["error_class"] for r in results if r["returncode"] != 0)

    dim_total = Counter()
    dim_silent = Counter()
    items_distribution = []
    for r in results:
        sess = r.get("session", {})
        if sess.get("no_session") or sess.get("parse_error"):
            continue
        items_distribution.append(sess["total_items"])
        for dim, info in sess.get("dims", {}).items():
            dim_total[dim] += 1
            if info["items"] == 0 and not info["error"]:
                dim_silent[dim] += 1

    silent_rate = {dim: round(dim_silent[dim] / dim_total[dim], 3)
                   for dim in dim_total if dim_total[dim]}

    items_sorted = sorted(items_distribution)
    median = items_sorted[len(items_sorted) // 2] if items_sorted else 0
    p90 = items_sorted[int(len(items_sorted) * 0.9)] if items_sorted else 0

    return {
        "total_runs": total,
        "passed": passed,
        "pass_rate": round(passed / total, 3) if total else 0,
        "empty_runs": empty_runs,
        "consistency": round(1 - empty_runs / total, 3) if total else 0,
        "error_classes": dict(error_classes),
        "worker_silent_rate": silent_rate,
        "items_median": median,
        "items_p90": p90,
    }


def format_report(agg: dict, results: list) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        "# Shadow Run 报告",
        "",
        f"> 生成时间: {now}",
        f"> 总 run 数: {agg['total_runs']}",
        "",
        "## 总览",
        "",
        f"- 成功率: **{agg['pass_rate']:.1%}** ({agg['passed']}/{agg['total_runs']})",
        f"- 一致性: **{agg['consistency']:.1%}** (非空 run 比例)",
        f"- 空 run: {agg['empty_runs']}",
        f"- items 中位数 / P90: {agg['items_median']} / {agg['items_p90']}",
        "",
        "## 失败分类",
        "",
    ]
    if not agg["error_classes"]:
        lines.append("- 无失败")
    else:
        lines += ["| 错误类型 | 计数 |", "|----------|------|"]
        for cls, count in sorted(agg["error_classes"].items(), key=lambda x: -x[1]):
            lines.append(f"| {cls} | {count} |")

    lines += [
        "",
        "## Worker 静默率",
        "",
        "| dimension | silent_rate |",
        "|-----------|-------------|",
    ]
    for dim, rate in sorted(agg["worker_silent_rate"].items()):
        lines.append(f"| {dim} | {rate:.1%} |")

    lines += [
        "",
        "## 门禁判定",
        "",
    ]
    if agg["consistency"] >= 0.6:
        lines.append(f"- [PASS] 一致性 {agg['consistency']:.1%} ≥ 60%")
    else:
        lines.append(f"- [FAIL] 一致性 {agg['consistency']:.1%} < 60% — 不允许合入主干")
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description="啄木鸟 shadow run harness")
    parser.add_argument("--workspace", required=True, help="用哪个 workspace 跑")
    parser.add_argument("--runs", type=int, default=50, help="跑多少次 (默认 50)")
    parser.add_argument("--concurrent", type=int, default=1,
                        help="并发数 (默认 1 串行; >1 会加压 CLI 配额)")
    parser.add_argument("--timeout", type=int, default=900, help="单次 run 超时秒 (默认 900s)")
    parser.add_argument("--fail-under", type=float, default=0.0,
                        help="一致性低于该值退出码 1 (CI 门禁用)")
    args = parser.parse_args()

    workspace = Path(args.workspace).resolve()
    if not workspace.is_dir():
        print(f"[error] workspace 不存在: {workspace}")
        sys.exit(2)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_dir = ROOT / "logs" / f"shadow_{ts}"
    log_dir.mkdir(parents=True, exist_ok=True)
    print(f"[shadow] workspace={workspace}")
    print(f"[shadow] runs={args.runs} concurrent={args.concurrent} timeout={args.timeout}s")
    print(f"[shadow] log_dir={log_dir}")

    results = []
    if args.concurrent <= 1:
        for i in range(args.runs):
            print(f"[shadow] run {i+1}/{args.runs}...")
            r = run_once(workspace, log_dir, i, args.timeout)
            print(f"         rc={r['returncode']} {r['elapsed_s']}s "
                  f"items={r.get('session', {}).get('total_items', '?')}")
            results.append(r)
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrent) as pool:
            futures = [pool.submit(run_once, workspace, log_dir, i, args.timeout)
                       for i in range(args.runs)]
            for fut in concurrent.futures.as_completed(futures):
                r = fut.result()
                print(f"[shadow] run {r['run_idx']} rc={r['returncode']} {r['elapsed_s']}s "
                      f"items={r.get('session', {}).get('total_items', '?')}")
                results.append(r)

    agg = aggregate(results)
    (log_dir / "report.json").write_text(
        json.dumps({"aggregate": agg, "runs": results}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    report_md = format_report(agg, results)
    (log_dir / "report.md").write_text(report_md, encoding="utf-8")

    print("\n" + report_md)
    print(f"[shadow] 报告: {log_dir}/report.md")

    if args.fail_under > 0 and agg["consistency"] < args.fail_under:
        print(f"[shadow] 一致性 {agg['consistency']:.1%} < 门禁 {args.fail_under:.1%},退出码 1")
        sys.exit(1)


if __name__ == "__main__":
    main()
