"""stability_metrics.py — 扫 workspace-*/output/sessions/*.jsonl 聚合上线稳定性指标.

为什么做 (gate 3 质量证据): 之前 0-items 异常率 / 失败率 / 平均耗时这些指标散落
在各 workspace 的 session 事件里, 没有统一聚合口径. 管理员答不了"这周跑了几次 /
几次失败 / 平均耗时" 的问题.

本脚本是只读工具, 扫 session jsonl 计算:
- total_runs: 总评审数
- completed / failed / degraded: 三类终态
- zero_items_count / rate: 0 items 异常数 + 占比 (gate v2 要求 <2%)
- avg_duration_ms / avg_cost_usd: 平均耗时 + 平均成本
- p50/p95 耗时
- by_reviewer / by_workspace / by_mode: 分组统计

用法:
  python scripts/stability_metrics.py                 # 全 workspace, 全时间
  python scripts/stability_metrics.py --days 7        # 最近 7 天
  python scripts/stability_metrics.py --workspace workspace-sample --format json
  python scripts/stability_metrics.py --json | jq     # CI / dashboard 用

输出默认 text, --format json 给 /api/metrics 端点或运维面板用.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional


PROJECT_ROOT = Path(__file__).parent.parent.resolve()


def _iter_session_files(project_root: Path, workspace: Optional[str] = None) -> Iterator[Path]:
    """遍历所有 workspace-*/output/sessions/*.jsonl 文件。"""
    pattern = workspace if workspace else "workspace-*"
    for ws_dir in sorted(project_root.glob(pattern)):
        if not ws_dir.is_dir():
            continue
        sessions_dir = ws_dir / "output" / "sessions"
        if not sessions_dir.is_dir():
            continue
        yield from sorted(sessions_dir.glob("*.jsonl"))


def _parse_session(path: Path) -> Optional[Dict[str, Any]]:
    """解析单个 session jsonl, 返回聚合后的 run 摘要; 文件坏或无效返回 None."""
    events: List[Dict[str, Any]] = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        return None

    if not events:
        return None

    # 首个 review_started 给元信息; 最后的 review_completed/failed/degraded 给终态
    meta = next((e for e in events if e.get("type") == "review_started"), {})
    final = next(
        (e for e in reversed(events)
         if e.get("type") in ("review_completed", "review_failed", "review_degraded")),
        None,
    )

    ts_start = meta.get("ts", "")
    status = "unknown"
    items_count = 0
    cost_usd = 0.0
    duration_ms = 0

    if final is not None:
        t = final.get("type", "")
        if t == "review_completed":
            status = "completed"
        elif t == "review_failed":
            status = "failed"
        elif t == "review_degraded":
            status = "degraded"
        items_count = int(final.get("items_count", 0) or 0)
        cost_usd = float(final.get("total_cost_usd", 0) or 0)
        duration_ms = int(final.get("duration_ms", 0) or 0)

    # workspace 名从路径推: workspace-foo/output/sessions/*.jsonl → workspace-foo
    ws_name = path.parent.parent.parent.name

    return {
        "session_file": path.name,
        "workspace": ws_name,
        "ts_start": ts_start,
        "reviewer": meta.get("reviewer", "unknown"),
        "mode": meta.get("mode", "standard"),
        "prd_name": meta.get("prd_name", ""),
        "status": status,
        "items_count": items_count,
        "cost_usd": cost_usd,
        "duration_ms": duration_ms,
    }


def _filter_by_days(runs: List[Dict[str, Any]], days: Optional[int]) -> List[Dict[str, Any]]:
    if not days:
        return runs
    cutoff = datetime.now() - timedelta(days=days)
    kept = []
    for r in runs:
        try:
            t = datetime.fromisoformat(r["ts_start"])
            if t >= cutoff:
                kept.append(r)
        except (ValueError, TypeError):
            continue
    return kept


def compute_metrics(runs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """对 run 列表聚合指标."""
    total = len(runs)
    if total == 0:
        return {
            "total_runs": 0,
            "completed": 0, "failed": 0, "degraded": 0, "unknown": 0,
            "zero_items_count": 0, "zero_items_rate": 0.0,
            "avg_duration_ms": 0, "p50_duration_ms": 0, "p95_duration_ms": 0,
            "avg_cost_usd": 0.0, "total_cost_usd": 0.0,
            "by_reviewer": {}, "by_workspace": {}, "by_mode": {},
        }

    status_counts: Dict[str, int] = defaultdict(int)
    for r in runs:
        status_counts[r["status"]] += 1

    completed_runs = [r for r in runs if r["status"] == "completed"]
    zero_items = [r for r in completed_runs if r["items_count"] == 0]
    durations = [r["duration_ms"] for r in runs if r["duration_ms"] > 0]
    costs = [r["cost_usd"] for r in runs if r["cost_usd"] > 0]

    def _by(key: str) -> Dict[str, int]:
        d: Dict[str, int] = defaultdict(int)
        for r in runs:
            d[r.get(key, "unknown")] += 1
        return dict(sorted(d.items(), key=lambda x: -x[1]))

    def _percentile(vals: List[int], pct: float) -> int:
        if not vals:
            return 0
        vals = sorted(vals)
        k = max(0, min(len(vals) - 1, int(len(vals) * pct)))
        return vals[k]

    return {
        "total_runs": total,
        "completed": status_counts["completed"],
        "failed": status_counts["failed"],
        "degraded": status_counts["degraded"],
        "unknown": status_counts["unknown"],
        "zero_items_count": len(zero_items),
        "zero_items_rate": round(len(zero_items) / max(1, len(completed_runs)), 4),
        "avg_duration_ms": int(statistics.mean(durations)) if durations else 0,
        "p50_duration_ms": _percentile(durations, 0.5),
        "p95_duration_ms": _percentile(durations, 0.95),
        "avg_cost_usd": round(statistics.mean(costs), 4) if costs else 0.0,
        "total_cost_usd": round(sum(costs), 4),
        "by_reviewer": _by("reviewer"),
        "by_workspace": _by("workspace"),
        "by_mode": _by("mode"),
    }


def render_text(metrics: Dict[str, Any], days: Optional[int]) -> str:
    scope = f"最近 {days} 天" if days else "全部历史"
    lines = [f"=== 啄木鸟稳定性指标 ({scope}) ==="]
    lines.append(f"总 run: {metrics['total_runs']}")
    lines.append(
        f"  completed={metrics['completed']} / failed={metrics['failed']} / "
        f"degraded={metrics['degraded']} / unknown={metrics['unknown']}"
    )
    zir = metrics["zero_items_rate"]
    gate_status = "✓ <2%" if zir < 0.02 else "⚠ >2%" if zir < 0.1 else "✗ >10%"
    lines.append(f"0-items 异常: {metrics['zero_items_count']} 次, 占完成评审 {zir:.1%} {gate_status}")
    lines.append(
        f"耗时: avg={metrics['avg_duration_ms'] / 1000:.1f}s, "
        f"p50={metrics['p50_duration_ms'] / 1000:.1f}s, "
        f"p95={metrics['p95_duration_ms'] / 1000:.1f}s"
    )
    lines.append(
        f"成本: avg=${metrics['avg_cost_usd']:.3f}, "
        f"total=${metrics['total_cost_usd']:.2f}"
    )
    if metrics["by_workspace"]:
        lines.append(f"Top workspace: {list(metrics['by_workspace'].items())[:5]}")
    if metrics["by_reviewer"]:
        lines.append(f"Top reviewer: {list(metrics['by_reviewer'].items())[:5]}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--workspace", help="只看指定 workspace, 默认 workspace-*")
    parser.add_argument("--days", type=int, help="只看最近 N 天的 run")
    parser.add_argument("--format", choices=["text", "json"], default="text")
    args = parser.parse_args()

    runs: List[Dict[str, Any]] = []
    for path in _iter_session_files(PROJECT_ROOT, args.workspace):
        summary = _parse_session(path)
        if summary:
            runs.append(summary)

    runs = _filter_by_days(runs, args.days)
    metrics = compute_metrics(runs)

    if args.format == "json":
        out = json.dumps(metrics, ensure_ascii=False, indent=2)
    else:
        out = render_text(metrics, args.days)

    try:
        print(out)
    except UnicodeEncodeError:
        sys.stdout.buffer.write(out.encode("utf-8", errors="replace"))
        sys.stdout.buffer.write(b"\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
