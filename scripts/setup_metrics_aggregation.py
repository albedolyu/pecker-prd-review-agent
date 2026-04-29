"""metrics 每日维护: prune 90 天前 events + 物化 daily_aggregate.

cron 模板 (Linux):
    0 3 * * * cd /repo && python scripts/setup_metrics_aggregation.py \
        --db workspace/metrics.db --keep-days 90

Windows Task Scheduler 等同设置即可.

幂等; 跑多次没副作用.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from review.metrics_store import (  # noqa: E402
    materialize_daily_aggregate, prune_old_events,
)


def main() -> int:
    p = argparse.ArgumentParser(description="metrics 每日聚合 + prune")
    p.add_argument("--db", required=True)
    p.add_argument("--keep-days", type=int, default=90, help="保留多少天的原始 events")
    p.add_argument("--dry-run", action="store_true", help="只打报告不动数据")
    args = p.parse_args()

    if not os.path.isfile(args.db):
        print(f"[ERROR] db 不存在: {args.db}", file=sys.stderr)
        return 1

    if args.dry_run:
        print(f"[DRY] 跳过 prune, 跳过 aggregate (db={args.db})")
        return 0

    aggregated = materialize_daily_aggregate(args.db)
    pruned = prune_old_events(args.db, keep_days=args.keep_days)
    report = {
        "db": args.db,
        "keep_days": args.keep_days,
        "aggregated_rows": aggregated,
        "pruned_events": pruned,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
