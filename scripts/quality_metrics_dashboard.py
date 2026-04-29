#!/usr/bin/env python
"""啄木鸟规则质量在线 dashboard 生成器.

读 finding_outcomes.db (PM 接受/驳回/改写信号), 生成 HTML dashboard:
  - 规则 accept_rate 横向 bar chart
  - 30 天 trend buckets (周维度)
  - top-10 high-reject 规则 (待优化)
  - top-10 high-accept 规则 (可固化)
  - per-PM accept history

用法:
  python scripts/quality_metrics_dashboard.py                    # 默认输出 web/dashboard.html
  python scripts/quality_metrics_dashboard.py --days 30
  python scripts/quality_metrics_dashboard.py --output dashboard.html
  python scripts/quality_metrics_dashboard.py --export-csv dashboard.csv
  python scripts/quality_metrics_dashboard.py --db-path /path/to/finding_outcomes.db
"""
from __future__ import annotations

import argparse
import csv
import html
import os
import sys
from datetime import datetime
from typing import Any, Dict, List

# 让 scripts/ 目录运行时能 import 项目根
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from review.finding_outcomes_store import (
    get_all_rules_metrics,
    get_high_accept_rules,
    get_low_accept_rules,
    get_pm_accept_summary,
    get_recent_outcomes,
    trend_buckets,
)


def _safe_print(text: str) -> None:
    """Windows GBK 控制台兜底."""
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.encode("gbk", errors="replace").decode("gbk", errors="replace"))


# ============================================================
# 数据收集
# ============================================================


def collect_dashboard_data(days: int, db_path: str = None) -> Dict[str, Any]:
    """聚合 dashboard 需要的所有数据."""
    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "window_days": days,
        "all_rules": get_all_rules_metrics(days=days, db_path=db_path),
        "low_accept": get_low_accept_rules(threshold=0.3, min_count=3, days=days, db_path=db_path),
        "high_accept": get_high_accept_rules(threshold=0.95, min_count=3, days=days, db_path=db_path),
        "pms": get_pm_accept_summary(days=days, db_path=db_path),
        "trend": trend_buckets(days=days, bucket_days=7, db_path=db_path),
        "recent": get_recent_outcomes(limit=20, db_path=db_path),
    }


# ============================================================
# HTML 渲染
# ============================================================


_CSS = """
body { font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif; max-width: 1200px; margin: 24px auto; padding: 0 20px; color: #2c3e50; background: #f8f9fa; }
h1 { color: #1a73e8; border-bottom: 2px solid #1a73e8; padding-bottom: 8px; }
h2 { color: #34495e; margin-top: 32px; border-left: 4px solid #1a73e8; padding-left: 12px; }
.meta { color: #7f8c8d; font-size: 13px; margin-bottom: 24px; }
.kpi-row { display: flex; gap: 16px; margin-bottom: 24px; flex-wrap: wrap; }
.kpi { background: white; border-radius: 8px; padding: 16px 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); flex: 1; min-width: 180px; }
.kpi-label { font-size: 12px; color: #7f8c8d; }
.kpi-value { font-size: 28px; font-weight: 600; color: #1a73e8; margin-top: 4px; }
table { border-collapse: collapse; width: 100%; background: white; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.08); margin-bottom: 24px; }
th { background: #1a73e8; color: white; padding: 10px 14px; text-align: left; font-weight: 500; }
td { padding: 10px 14px; border-bottom: 1px solid #ecf0f1; }
tr:last-child td { border-bottom: none; }
tr:hover { background: #f1f7ff; }
.bar-container { display: flex; align-items: center; gap: 8px; }
.bar { background: linear-gradient(90deg, #4caf50, #1a73e8); height: 18px; border-radius: 4px; }
.bar.low { background: linear-gradient(90deg, #f44336, #ff9800); }
.bar.mid { background: linear-gradient(90deg, #ff9800, #ffc107); }
.bar.high { background: linear-gradient(90deg, #4caf50, #1a73e8); }
.tag { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 500; }
.tag-accept { background: #e8f5e9; color: #2e7d32; }
.tag-reject { background: #ffebee; color: #c62828; }
.tag-edit { background: #fff3e0; color: #e65100; }
.alert-box { background: #fff3cd; border-left: 4px solid #ffc107; padding: 12px 16px; border-radius: 4px; margin: 12px 0; }
.success-box { background: #d4edda; border-left: 4px solid #28a745; padding: 12px 16px; border-radius: 4px; margin: 12px 0; }
.empty { color: #95a5a6; font-style: italic; padding: 12px; }
"""


def _bar_class(rate: float) -> str:
    if rate >= 0.7:
        return "high"
    if rate >= 0.4:
        return "mid"
    return "low"


def _bar_row(label: str, rate: float, total: int) -> str:
    """单条 bar (规则 / PM 一行)."""
    pct = max(0, min(100, rate * 100))
    safe_label = html.escape(str(label))
    return (
        f'<div class="bar-container">'
        f'<div style="width: 120px; font-family: monospace;">{safe_label}</div>'
        f'<div class="bar {_bar_class(rate)}" style="width: {pct * 4}px;"></div>'
        f'<div style="font-size: 12px; color: #7f8c8d;">{rate:.0%} (n={total})</div>'
        f'</div>'
    )


def render_html(data: Dict[str, Any]) -> str:
    """生成 dashboard HTML."""
    rules = data["all_rules"]
    low = data["low_accept"]
    high = data["high_accept"]
    pms = data["pms"]
    trend = data["trend"]
    recent = data["recent"]

    total_outcomes = sum(m["total"] for m in rules.values())
    avg_accept_rate = (
        sum(m["accept_rate"] * m["total"] for m in rules.values()) / total_outcomes
        if total_outcomes else 0.0
    )

    # KPI 卡片
    kpi_html = (
        '<div class="kpi-row">'
        f'<div class="kpi"><div class="kpi-label">规则总数 (有反馈)</div><div class="kpi-value">{len(rules)}</div></div>'
        f'<div class="kpi"><div class="kpi-label">反馈总数</div><div class="kpi-value">{total_outcomes}</div></div>'
        f'<div class="kpi"><div class="kpi-label">加权 accept_rate</div><div class="kpi-value">{avg_accept_rate:.0%}</div></div>'
        f'<div class="kpi"><div class="kpi-label">PM 数</div><div class="kpi-value">{len(pms)}</div></div>'
        f'<div class="kpi"><div class="kpi-label">待优化规则</div><div class="kpi-value" style="color: #c62828;">{len(low)}</div></div>'
        f'<div class="kpi"><div class="kpi-label">可固化规则</div><div class="kpi-value" style="color: #2e7d32;">{len(high)}</div></div>'
        '</div>'
    )

    # 规则 accept_rate 横向 bar chart (按 accept_rate 降序)
    sorted_rules = sorted(rules.values(), key=lambda m: -m["accept_rate"])
    rules_table = "<h2>规则 accept_rate (按窗口期)</h2><table>"
    rules_table += "<tr><th>rule_id</th><th>accept_rate</th><th>accept</th><th>edit</th><th>reject</th><th>total</th></tr>"
    if not sorted_rules:
        rules_table += '<tr><td colspan="6" class="empty">暂无数据 — PM 反馈累计 3 条以上才会显示</td></tr>'
    for m in sorted_rules:
        bar_html = _bar_row(m["rule_id"], m["accept_rate"], m["total"])
        rules_table += (
            f'<tr><td>{html.escape(m["rule_id"])}</td>'
            f'<td>{bar_html}</td>'
            f'<td><span class="tag tag-accept">{m["accept"]}</span></td>'
            f'<td><span class="tag tag-edit">{m["edit"]}</span></td>'
            f'<td><span class="tag tag-reject">{m["reject"]}</span></td>'
            f'<td>{m["total"]}</td></tr>'
        )
    rules_table += "</table>"

    # 待优化规则 (low_accept)
    low_html = "<h2>待优化规则 (accept_rate &lt; 30%, 至少 3 条反馈)</h2>"
    if low:
        low_html += '<div class="alert-box">这些规则被 PM 大量驳回, 建议:<br>'
        low_html += '1. 看 reason 找共性, 调 prompt fire_when 收紧触发条件<br>'
        low_html += '2. 给规则加 negative_example 防误报<br>'
        low_html += '3. 信鸽 v2 加 learning record 标 "X 场景下不要报"</div>'
        low_html += "<table><tr><th>rule_id</th><th>accept_rate</th><th>reject</th><th>total</th></tr>"
        for m in low:
            low_html += (
                f'<tr><td><strong>{html.escape(m["rule_id"])}</strong></td>'
                f'<td style="color: #c62828;">{m["accept_rate"]:.0%}</td>'
                f'<td>{m["reject"]}</td><td>{m["total"]}</td></tr>'
            )
        low_html += "</table>"
    else:
        low_html += '<div class="empty">没有待优化规则 — 规则质量很好</div>'

    # 可固化规则 (high_accept)
    high_html = "<h2>可固化规则 (accept_rate &gt; 95%, 至少 3 条反馈)</h2>"
    if high:
        high_html += '<div class="success-box">这些规则 PM 几乎全接受, 可考虑:<br>'
        high_html += '1. 提升 severity (could → should → must)<br>'
        high_html += '2. 苍鹰交叉校验时给该 rule_id 加权重<br>'
        high_html += '3. 写进 README 作为 "已稳定的规则"</div>'
        high_html += "<table><tr><th>rule_id</th><th>accept_rate</th><th>accept</th><th>total</th></tr>"
        for m in high:
            high_html += (
                f'<tr><td><strong>{html.escape(m["rule_id"])}</strong></td>'
                f'<td style="color: #2e7d32;">{m["accept_rate"]:.0%}</td>'
                f'<td>{m["accept"]}</td><td>{m["total"]}</td></tr>'
            )
        high_html += "</table>"
    else:
        high_html += '<div class="empty">还没有规则达到 95% accept_rate</div>'

    # PM 个人 dashboard
    pms_html = "<h2>PM 个人 accept_rate (差异化分析)</h2><table>"
    pms_html += "<tr><th>PM</th><th>accept_rate</th><th>accept</th><th>edit</th><th>reject</th><th>total</th></tr>"
    if pms:
        sorted_pms = sorted(pms.values(), key=lambda m: -m["total"])
        for m in sorted_pms:
            bar_html = _bar_row(m["pm_name"], m["accept_rate"], m["total"])
            pms_html += (
                f'<tr><td>{html.escape(m["pm_name"])}</td>'
                f'<td>{bar_html}</td>'
                f'<td><span class="tag tag-accept">{m["accept"]}</span></td>'
                f'<td><span class="tag tag-edit">{m["edit"]}</span></td>'
                f'<td><span class="tag tag-reject">{m["reject"]}</span></td>'
                f'<td>{m["total"]}</td></tr>'
            )
    else:
        pms_html += '<tr><td colspan="6" class="empty">暂无 PM 反馈数据</td></tr>'
    pms_html += "</table>"

    # 30 天 trend
    trend_html = "<h2>30 天反馈趋势 (周维度)</h2><table>"
    trend_html += "<tr><th>周</th><th>accept_rate</th><th>accept</th><th>edit</th><th>reject</th><th>total</th></tr>"
    if trend and any(b["total"] for b in trend):
        for b in trend:
            week_label = f"{b['bucket_start']} ~ {b['bucket_end']}"
            bar_html = _bar_row("", b["accept_rate"], b["total"])
            trend_html += (
                f'<tr><td>{week_label}</td>'
                f'<td>{bar_html}</td>'
                f'<td><span class="tag tag-accept">{b["accept"]}</span></td>'
                f'<td><span class="tag tag-edit">{b["edit"]}</span></td>'
                f'<td><span class="tag tag-reject">{b["reject"]}</span></td>'
                f'<td>{b["total"]}</td></tr>'
            )
    else:
        trend_html += '<tr><td colspan="6" class="empty">暂无 trend 数据</td></tr>'
    trend_html += "</table>"

    # 最近反馈流
    recent_html = "<h2>最近 20 条反馈</h2><table>"
    recent_html += "<tr><th>时间</th><th>finding</th><th>rule</th><th>outcome</th><th>PM</th><th>reason</th></tr>"
    if recent:
        for r in recent:
            tag_cls = {"accept": "tag-accept", "reject": "tag-reject", "edit": "tag-edit"}.get(r["outcome"], "")
            reason = (r.get("reason") or "")[:80]
            recent_html += (
                f'<tr><td>{html.escape(r.get("timestamp") or "")[:19]}</td>'
                f'<td>{html.escape(r.get("finding_id") or "")}</td>'
                f'<td>{html.escape(r.get("rule_id") or "")}</td>'
                f'<td><span class="tag {tag_cls}">{html.escape(r.get("outcome") or "")}</span></td>'
                f'<td>{html.escape(r.get("pm_name") or "")}</td>'
                f'<td>{html.escape(reason)}</td></tr>'
            )
    else:
        recent_html += '<tr><td colspan="6" class="empty">暂无反馈</td></tr>'
    recent_html += "</table>"

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>啄木鸟规则质量 Dashboard</title>
<style>{_CSS}</style>
</head>
<body>
<h1>啄木鸟规则质量 Dashboard</h1>
<div class="meta">生成时间: {data["generated_at"]} · 窗口期: {data["window_days"]} 天</div>
{kpi_html}
{rules_table}
{low_html}
{high_html}
{pms_html}
{trend_html}
{recent_html}
<div class="meta" style="margin-top: 32px;">数据来源: review/finding_outcomes.db · API: /api/feedback/metrics</div>
</body>
</html>
"""


# ============================================================
# CSV 导出
# ============================================================


def export_csv(data: Dict[str, Any], path: str) -> None:
    """规则 metrics 导 CSV (PM 看趋势用)."""
    rows: List[Dict[str, Any]] = []
    for m in data["all_rules"].values():
        rows.append({
            "rule_id": m["rule_id"],
            "accept": m["accept"],
            "edit": m["edit"],
            "reject": m["reject"],
            "total": m["total"],
            "accept_rate": m["accept_rate"],
            "category": (
                "low_accept" if m["accept_rate"] < 0.3 and m["total"] >= 3
                else "high_accept" if m["accept_rate"] >= 0.95 and m["total"] >= 3
                else "normal"
            ),
        })
    rows.sort(key=lambda r: -r["total"])
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        if rows:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        else:
            f.write("rule_id,accept,edit,reject,total,accept_rate,category\n")


# ============================================================
# CLI
# ============================================================


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="啄木鸟规则质量 dashboard 生成器")
    parser.add_argument("--days", type=int, default=30, help="窗口期 (默认 30 天)")
    parser.add_argument(
        "--output",
        default=os.path.join(_ROOT, "web", "dashboard.html"),
        help="HTML 输出路径 (默认 web/dashboard.html)",
    )
    parser.add_argument("--export-csv", help="额外导出 CSV 路径", default=None)
    parser.add_argument("--db-path", default=None, help="finding_outcomes.db 路径 (默认 review/finding_outcomes.db)")
    args = parser.parse_args(argv)

    data = collect_dashboard_data(days=args.days, db_path=args.db_path)
    html_text = render_html(data)

    out_dir = os.path.dirname(args.output)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(html_text)
    _safe_print(f"[dashboard] HTML -> {args.output}")
    _safe_print(
        f"  规则数: {len(data['all_rules'])} · "
        f"反馈数: {sum(m['total'] for m in data['all_rules'].values())} · "
        f"PM 数: {len(data['pms'])}"
    )
    _safe_print(f"  待优化: {len(data['low_accept'])} · 可固化: {len(data['high_accept'])}")

    if args.export_csv:
        export_csv(data, args.export_csv)
        _safe_print(f"[dashboard] CSV -> {args.export_csv}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
