#!/usr/bin/env python
"""啄木鸟质量度量 demo — 注入 100 条 mock outcomes 后跑 dashboard.

不依赖真实评审, 给新接入的人快速看到 dashboard 效果.

用法:
  python scripts/demo_quality_metrics.py
      → 默认在 .tmp-demo/ 下建临时 db, 写 dashboard 到 .tmp-demo/dashboard.html
  python scripts/demo_quality_metrics.py --keep
      → 不清理临时文件 (PM 想看 dashboard 时用)
"""
from __future__ import annotations

import argparse
import os
import random
import shutil
import sys
import tempfile
from datetime import datetime, timedelta

# 让 scripts/ 目录运行时能 import 项目根
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def _safe_print(text: str) -> None:
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.encode("gbk", errors="replace").decode("gbk", errors="replace"))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="啄木鸟质量度量 demo")
    parser.add_argument("--keep", action="store_true", help="保留临时文件 (默认运行后清理)")
    parser.add_argument("--seed", type=int, default=42, help="随机种子 (默认 42 复现)")
    parser.add_argument(
        "--demo-dir",
        default=os.path.join(_ROOT, ".tmp-demo"),
        help="临时 demo 目录 (默认 .tmp-demo/)",
    )
    args = parser.parse_args(argv)

    random.seed(args.seed)

    # 清理 + 重建 demo 目录
    if os.path.exists(args.demo_dir):
        shutil.rmtree(args.demo_dir)
    os.makedirs(args.demo_dir)
    db_path = os.path.join(args.demo_dir, "finding_outcomes.db")

    # 注入 mock data 到独立 db (不污染生产)
    os.environ["PECKER_OUTCOMES_DB"] = db_path

    from review.finding_outcomes_store import (
        get_all_rules_metrics,
        get_high_accept_rules,
        get_low_accept_rules,
        init_store,
        record_outcome,
    )

    init_store(db_path)

    # 100 条 mock: 50 accept / 30 reject / 20 edit
    rules = [
        ("R-001", "structure"),
        ("R-002", "structure"),
        ("R-003", "structure"),
        ("R-004", "data_quality"),
        ("R-005", "data_quality"),
        ("RC-005", "ai_coding"),
        ("RC-006", "ai_coding"),
        ("TM-001", "engineering"),
        ("TM-002", "engineering"),
        ("RV-001", "review"),
    ]
    pms = ["pm_潘驰", "pm_alice", "pm_bob"]
    severities = ["must", "should", "could"]

    # 倾斜分布 — 让 dashboard 数据更接近真实场景
    # R-001/R-002: 高 accept (90%+) → 进 high_accept 列表
    # RC-005/RC-006: 低 accept (<30%) → 进 low_accept 列表
    # 其他: 混合 50-70% accept
    rule_bias = {
        "R-001": 0.95,
        "R-002": 0.92,
        "R-003": 0.65,
        "R-004": 0.55,
        "R-005": 0.6,
        "RC-005": 0.18,
        "RC-006": 0.22,
        "TM-001": 0.7,
        "TM-002": 0.6,
        "RV-001": 0.45,
    }

    outcomes_to_inject = []
    n_target = 100
    for i in range(n_target):
        rid, dim = random.choice(rules)
        bias = rule_bias.get(rid, 0.5)
        roll = random.random()
        if roll < bias:
            outcome = "accept"
        elif roll < bias + 0.1:
            outcome = "edit"
        else:
            outcome = "reject"
        # 时间分布: 30 天内均匀 (用 db timestamp 自填则全是 now, 没办法看 trend)
        # 这里直接 record_outcome 完后手动改 timestamp (走 sqlite raw update)
        outcomes_to_inject.append({
            "finding_id": f"{rid.split('-')[0]}-{1000 + i:04d}",
            "rule_id": rid,
            "outcome": outcome,
            "pm_name": random.choice(pms),
            "reason": f"mock 反馈 #{i}" if outcome != "accept" else None,
            "severity": random.choice(severities),
            "prd_name": f"demo_prd_{(i % 5) + 1}",
            "_offset_days": random.uniform(0, 29.5),
        })

    # 写库 (record_outcome 用 now, 后面手动 update timestamp 模拟历史)
    import sqlite3
    for o in outcomes_to_inject:
        record_outcome(
            finding_id=o["finding_id"],
            outcome=o["outcome"],
            rule_id=o["rule_id"],
            pm_name=o["pm_name"],
            reason=o["reason"],
            severity=o["severity"],
            prd_name=o["prd_name"],
            db_path=db_path,
        )
    # 改 timestamp 让 trend 有内容
    conn = sqlite3.connect(db_path)
    rows = conn.execute("SELECT id FROM finding_outcomes ORDER BY id ASC").fetchall()
    for (row_id,), o in zip(rows, outcomes_to_inject):
        new_ts = (datetime.now() - timedelta(days=o["_offset_days"])).isoformat(timespec="seconds")
        conn.execute("UPDATE finding_outcomes SET timestamp = ? WHERE id = ?", (new_ts, row_id))
    conn.commit()
    conn.close()

    # 跑聚合
    metrics = get_all_rules_metrics(days=30, db_path=db_path)
    low = get_low_accept_rules(threshold=0.3, min_count=3, days=30, db_path=db_path)
    high = get_high_accept_rules(threshold=0.95, min_count=3, days=30, db_path=db_path)

    _safe_print("=" * 60)
    _safe_print("啄木鸟质量度量 demo")
    _safe_print("=" * 60)
    _safe_print(f"\n注入 mock outcomes: {n_target} 条")
    _safe_print(f"db: {db_path}\n")

    _safe_print("按规则聚合 (按 accept_rate 降序):")
    _safe_print(f"  {'rule_id':<10} {'accept':>6} {'edit':>4} {'reject':>6} {'total':>5}  accept_rate")
    for m in sorted(metrics.values(), key=lambda m: -m["accept_rate"]):
        _safe_print(
            f"  {m['rule_id']:<10} {m['accept']:>6} {m['edit']:>4} {m['reject']:>6} "
            f"{m['total']:>5}  {m['accept_rate']:.0%}"
        )

    _safe_print(f"\n待优化规则 (accept_rate < 30%, n >= 3): {len(low)}")
    for m in low:
        _safe_print(f"  - {m['rule_id']}: {m['accept_rate']:.0%} (reject={m['reject']})")

    _safe_print(f"\n可固化规则 (accept_rate >= 95%, n >= 3): {len(high)}")
    for m in high:
        _safe_print(f"  - {m['rule_id']}: {m['accept_rate']:.0%} (accept={m['accept']})")

    # 跑 dashboard
    from scripts.quality_metrics_dashboard import collect_dashboard_data, render_html
    data = collect_dashboard_data(days=30, db_path=db_path)
    html_text = render_html(data)
    dashboard_path = os.path.join(args.demo_dir, "dashboard.html")
    with open(dashboard_path, "w", encoding="utf-8") as f:
        f.write(html_text)
    _safe_print(f"\n[demo] dashboard HTML -> {dashboard_path}")
    _safe_print(f"  浏览器打开: file:///{dashboard_path.replace(os.sep, '/')}")

    # CSV 导出
    from scripts.quality_metrics_dashboard import export_csv
    csv_path = os.path.join(args.demo_dir, "dashboard.csv")
    export_csv(data, csv_path)
    _safe_print(f"[demo] CSV -> {csv_path}")

    if not args.keep:
        _safe_print(f"\n--keep 没设, 但保留 demo 目录方便查看 dashboard.")
        _safe_print(f"完成后手动清理: rm -rf {args.demo_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
