"""R20: 稳定性日常监控脚本

从 event_store session 文件聚合过去 24h 的关键指标,超过阈值时打印告警
(可接 cron / systemd timer / 飞书 webhook)。

用法:
    # 默认扫过去 24h + 所有 workspace
    python -m scripts.stability_daily

    # 指定时间窗 (小时)
    python -m scripts.stability_daily --window 48

    # 超阈值时直接非零退出(适合 CI / shell 脚本判分)
    python -m scripts.stability_daily --exit-on-alert

指标 + 阈值（见 docs/STABILITY_REGRESSION_TESTS.md 第五节）:
  - zero_rate:        zero-items worker_done 占比 > 10% 告警
  - quota_daily:      单日配额错误 > 5 次告警
  - failed_ratio:     review_failed / (failed + completed) > 15% 告警
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List


THRESHOLDS = {
    "zero_rate": 0.10,
    "quota_daily": 5,
    "failed_ratio": 0.15,
}


def _parse_ts(ts: str) -> float:
    """把 ISO 格式 ts 解析为 unix timestamp, 解析失败返回 0.0"""
    try:
        return datetime.fromisoformat(ts).timestamp()
    except (ValueError, TypeError):
        return 0.0


def scan_events(project_root: Path, window_hours: int) -> Dict[str, Any]:
    """聚合过去 window_hours 小时内所有 workspace 的 session events"""
    cutoff = time.time() - window_hours * 3600

    stats = {
        "window_hours": window_hours,
        "workspaces_scanned": 0,
        "worker_done_total": 0,
        "worker_done_zero": 0,
        "worker_done_quota_err": 0,
        "review_started": 0,
        "review_completed": 0,
        "review_failed": 0,
        "review_degraded": 0,
        "per_workspace": {},
    }

    for ws in project_root.iterdir():
        if not ws.is_dir() or not ws.name.startswith("workspace"):
            continue
        sess_dir = ws / "output" / "sessions"
        if not sess_dir.is_dir():
            continue
        stats["workspaces_scanned"] += 1
        ws_stats = {k: 0 for k in
                    ["worker_done_total", "worker_done_zero", "worker_done_quota_err",
                     "review_started", "review_completed", "review_failed", "review_degraded"]}

        for f in sess_dir.glob("*.jsonl"):
            for line in f.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ts = _parse_ts(ev.get("ts", ""))
                if ts < cutoff:
                    continue
                et = ev.get("type", "")
                if et == "worker_done":
                    ws_stats["worker_done_total"] += 1
                    if ev.get("items_count", -1) == 0:
                        ws_stats["worker_done_zero"] += 1
                    err = ev.get("error") or ""
                    if "hit your limit" in err or "配额" in err:
                        ws_stats["worker_done_quota_err"] += 1
                elif et in ws_stats:
                    ws_stats[et] += 1

        if any(ws_stats.values()):
            stats["per_workspace"][ws.name] = ws_stats
            for k, v in ws_stats.items():
                stats[k] = stats.get(k, 0) + v

    return stats


def evaluate_alerts(stats: Dict[str, Any]) -> List[str]:
    """返回触发告警的文字列表,没有告警返回空列表"""
    alerts: List[str] = []
    total = stats.get("worker_done_total", 0)

    if total > 0:
        zero_rate = stats["worker_done_zero"] / total
        if zero_rate > THRESHOLDS["zero_rate"]:
            alerts.append(
                f"⚠ zero-items worker_done 占比 {zero_rate:.0%} > {THRESHOLDS['zero_rate']:.0%} "
                f"({stats['worker_done_zero']}/{total})"
            )

    if stats.get("worker_done_quota_err", 0) > THRESHOLDS["quota_daily"]:
        alerts.append(
            f"⚠ 配额错误 {stats['worker_done_quota_err']} 次 > {THRESHOLDS['quota_daily']} 次/天"
        )

    completed = stats.get("review_completed", 0)
    failed = stats.get("review_failed", 0)
    if completed + failed > 0:
        failed_ratio = failed / (completed + failed)
        if failed_ratio > THRESHOLDS["failed_ratio"]:
            alerts.append(
                f"⚠ review_failed 占比 {failed_ratio:.0%} > {THRESHOLDS['failed_ratio']:.0%} "
                f"({failed}/{completed + failed})"
            )

    return alerts


def print_report(stats: Dict[str, Any], alerts: List[str]):
    import io, sys as _sys
    _sys.stdout = io.TextIOWrapper(_sys.stdout.buffer, encoding="utf-8", errors="replace") \
        if hasattr(_sys.stdout, "buffer") else _sys.stdout

    print(f"\n=== 啄木鸟稳定性日报 (过去 {stats['window_hours']}h) ===")
    print(f"扫描 workspace 数: {stats['workspaces_scanned']}")
    print()
    print(f"  worker_done 总数: {stats['worker_done_total']}")
    print(f"  零 items 次数:    {stats['worker_done_zero']}")
    print(f"  配额错误次数:     {stats['worker_done_quota_err']}")
    print()
    print(f"  review_started:   {stats.get('review_started', 0)}")
    print(f"  review_completed: {stats.get('review_completed', 0)}")
    print(f"  review_failed:    {stats.get('review_failed', 0)}")
    print(f"  review_degraded:  {stats.get('review_degraded', 0)}")

    if stats.get("per_workspace"):
        print("\n--- 按 workspace ---")
        for ws, ws_stats in stats["per_workspace"].items():
            print(f"  {ws}: {ws_stats}")

    print()
    if alerts:
        print("🚨 触发告警:")
        for a in alerts:
            print(f"  {a}")
    else:
        print("✓ 无告警，所有指标在阈值内")


def main():
    parser = argparse.ArgumentParser(description="稳定性日常监控（每天跑一次）")
    parser.add_argument("--window", type=int, default=24, help="时间窗(小时),默认 24")
    parser.add_argument("--exit-on-alert", action="store_true",
                        help="有告警时非零退出,适合 CI/shell 判分")
    parser.add_argument("--json", action="store_true", help="输出 JSON 不打印文本报告")
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parent.parent
    stats = scan_events(project_root, args.window)
    alerts = evaluate_alerts(stats)

    if args.json:
        print(json.dumps({"stats": stats, "alerts": alerts}, ensure_ascii=False, indent=2))
    else:
        print_report(stats, alerts)

    if args.exit_on_alert and alerts:
        sys.exit(2)


if __name__ == "__main__":
    main()
