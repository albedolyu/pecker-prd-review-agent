"""读 workspace/metrics.db 生成纯静态 dashboard.html (chart.js CDN, 不引 web server).

布局:
  Header: 顶部 KPI 卡片 (近 7 天 review 数 / 错误率 / 累计成本 / 平均时长)
  Row 1:  每日 review 数趋势 (line)
  Row 2:  per-vendor 错误率 (bar) + per-model 调用分布 (donut)
  Row 3:  成本累计 (area) + 最近异常事件表

用法:
    python scripts/render_metrics_dashboard.py \
        --db workspace/metrics.db \
        --out workspace/dashboard.html \
        --days 30
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from typing import Any, Dict, List

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from review.metrics_store import (  # noqa: E402
    aggregate_daily, get_summary, query_events,
)


HTML_TEMPLATE = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>啄木鸟 v2 — Metrics Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
  body{font-family:-apple-system,Segoe UI,Roboto,sans-serif;margin:0;padding:24px;background:#f5f6fa;color:#1f2937}
  h1{margin:0 0 8px;font-size:22px}
  .meta{color:#6b7280;font-size:12px;margin-bottom:24px}
  .kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-bottom:24px}
  .kpi{background:#fff;border-radius:8px;padding:16px;box-shadow:0 1px 3px rgba(0,0,0,.08)}
  .kpi .label{color:#6b7280;font-size:12px;text-transform:uppercase;letter-spacing:.5px}
  .kpi .value{font-size:28px;font-weight:600;margin-top:4px}
  .kpi .subtle{color:#9ca3af;font-size:12px;margin-top:4px}
  .row{display:grid;gap:16px;margin-bottom:24px}
  .row.cols-1{grid-template-columns:1fr}
  .row.cols-2{grid-template-columns:1fr 1fr}
  .card{background:#fff;border-radius:8px;padding:16px;box-shadow:0 1px 3px rgba(0,0,0,.08)}
  .card h3{margin:0 0 12px;font-size:14px;color:#374151}
  table{width:100%;border-collapse:collapse;font-size:13px}
  th,td{text-align:left;padding:8px;border-bottom:1px solid #e5e7eb}
  th{color:#6b7280;font-weight:500;background:#f9fafb}
  .status-success{color:#059669}
  .status-failed{color:#dc2626}
  .status-timeout{color:#d97706}
  .empty{color:#9ca3af;text-align:center;padding:24px}
</style>
</head>
<body>
<h1>啄木鸟 v2 — Metrics Dashboard</h1>
<div class="meta">生成于 __GENERATED_AT__ | 数据范围: 最近 __DAYS__ 天 | DB: __DB_PATH__</div>

<div class="kpis">
  <div class="kpi"><div class="label">7天 Review 完成</div><div class="value">__KPI_REVIEWS__</div><div class="subtle">含 voting + 苍鹰</div></div>
  <div class="kpi"><div class="label">错误数</div><div class="value">__KPI_ERRORS__</div><div class="subtle">status != success</div></div>
  <div class="kpi"><div class="label">累计成本 (USD)</div><div class="value">$__KPI_COST__</div><div class="subtle">含所有 LLM 调用</div></div>
  <div class="kpi"><div class="label">平均 Review 时长</div><div class="value">__KPI_AVG_MS__s</div><div class="subtle">review.completed</div></div>
</div>

<div class="row cols-1">
  <div class="card">
    <h3>每日 Review 数趋势</h3>
    <canvas id="chartDaily" height="80"></canvas>
  </div>
</div>

<div class="row cols-2">
  <div class="card">
    <h3>Per-Vendor 错误率</h3>
    <canvas id="chartVendor" height="120"></canvas>
  </div>
  <div class="card">
    <h3>Per-Model 调用分布</h3>
    <canvas id="chartModel" height="120"></canvas>
  </div>
</div>

<div class="row cols-2">
  <div class="card">
    <h3>累计成本 (USD)</h3>
    <canvas id="chartCost" height="120"></canvas>
  </div>
  <div class="card">
    <h3>最近异常事件 (Top 20)</h3>
    __RECENT_ERROR_TABLE__
  </div>
</div>

<script>
const dailyData = __DAILY_JSON__;
const vendorData = __VENDOR_JSON__;
const modelData = __MODEL_JSON__;
const costData = __COST_JSON__;

if (dailyData.labels.length) {
  new Chart(document.getElementById('chartDaily'), {
    type: 'line',
    data: {labels: dailyData.labels, datasets: [
      {label: 'review.completed', data: dailyData.completed, borderColor: '#2563eb', tension: .25, fill: false},
      {label: 'review.failed',    data: dailyData.failed,    borderColor: '#dc2626', tension: .25, fill: false}
    ]},
    options: {responsive: true, plugins: {legend: {position: 'bottom'}}}
  });
}

if (vendorData.labels.length) {
  new Chart(document.getElementById('chartVendor'), {
    type: 'bar',
    data: {labels: vendorData.labels, datasets: [
      {label: '总调用', data: vendorData.total, backgroundColor: '#60a5fa'},
      {label: '错误',   data: vendorData.errors, backgroundColor: '#f87171'}
    ]},
    options: {responsive: true, plugins: {legend: {position: 'bottom'}}, scales: {y: {beginAtZero: true}}}
  });
}

if (modelData.labels.length) {
  new Chart(document.getElementById('chartModel'), {
    type: 'doughnut',
    data: {labels: modelData.labels, datasets: [
      {data: modelData.values, backgroundColor: ['#2563eb','#10b981','#f59e0b','#8b5cf6','#ef4444','#0ea5e9']}
    ]},
    options: {responsive: true, plugins: {legend: {position: 'bottom'}}}
  });
}

if (costData.labels.length) {
  new Chart(document.getElementById('chartCost'), {
    type: 'line',
    data: {labels: costData.labels, datasets: [
      {label: '累计成本 USD', data: costData.values, borderColor: '#10b981', backgroundColor: 'rgba(16,185,129,.15)', tension: .2, fill: true}
    ]},
    options: {responsive: true, plugins: {legend: {position: 'bottom'}}}
  });
}
</script>
</body>
</html>
"""


def _aggregate(daily_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_date_completed: Dict[str, int] = defaultdict(int)
    by_date_failed: Dict[str, int] = defaultdict(int)
    by_date_cost: Dict[str, float] = defaultdict(float)
    for r in daily_rows:
        d = r["date"]
        if r["event_type"] == "review.completed":
            by_date_completed[d] += int(r["count"])
        if r["event_type"] == "review.failed":
            by_date_failed[d] += int(r["count"])
        by_date_cost[d] += float(r.get("total_cost_usd") or 0)
    dates = sorted(set(by_date_completed) | set(by_date_failed) | set(by_date_cost))
    return {
        "labels": dates,
        "completed": [by_date_completed.get(d, 0) for d in dates],
        "failed": [by_date_failed.get(d, 0) for d in dates],
        "cost_cumulative": _cumsum([by_date_cost.get(d, 0) for d in dates]),
    }


def _cumsum(values: List[float]) -> List[float]:
    out, total = [], 0.0
    for v in values:
        total += v
        out.append(round(total, 4))
    return out


def _vendor_breakdown(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    """从 llm.api_call / oauth.* events 抽 vendor 维度."""
    total: Dict[str, int] = defaultdict(int)
    errors: Dict[str, int] = defaultdict(int)
    for e in events:
        # vendor 优先取 details.vendor, 否则猜 model 前缀
        details = {}
        try:
            details = json.loads(e.get("details_json") or "{}") if e.get("details_json") else {}
        except (json.JSONDecodeError, TypeError):
            details = {}
        vendor = details.get("vendor") or _guess_vendor(e.get("model"))
        if not vendor:
            continue
        total[vendor] += 1
        if e.get("status") and e["status"] != "success":
            errors[vendor] += 1
    labels = sorted(total)
    return {
        "labels": labels,
        "total": [total[v] for v in labels],
        "errors": [errors[v] for v in labels],
    }


def _guess_vendor(model: str | None) -> str | None:
    if not model:
        return None
    m = model.lower()
    if "claude" in m or "anthropic" in m:
        return "claude"
    if "gpt" in m or "openai" in m or "o4" in m or "codex" in m:
        return "openai"
    if "gemini" in m:
        return "google"
    return model


def _model_breakdown(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    counts: Dict[str, int] = defaultdict(int)
    for e in events:
        m = e.get("model")
        if m:
            counts[m] += 1
    items = sorted(counts.items(), key=lambda x: -x[1])[:6]
    return {"labels": [k for k, _ in items], "values": [v for _, v in items]}


def _recent_errors_table(events: List[Dict[str, Any]], limit: int = 20) -> str:
    errors = [e for e in events if e.get("status") and e["status"] != "success"][:limit]
    if not errors:
        return '<div class="empty">最近无异常事件</div>'
    rows = []
    for e in errors:
        cls = f"status-{e.get('status', '')}"
        rows.append(
            f"<tr><td>{e['timestamp']}</td>"
            f"<td>{e['event_type']}</td>"
            f"<td>{e.get('model') or ''}</td>"
            f"<td class='{cls}'>{e.get('status') or ''}</td>"
            f"<td>{(e.get('details_json') or '')[:80]}</td></tr>"
        )
    return (
        '<table><thead><tr><th>时间</th><th>事件</th><th>Model</th>'
        '<th>状态</th><th>Details</th></tr></thead><tbody>'
        + "".join(rows) + '</tbody></table>'
    )


def render(db_path: str, days: int = 30) -> str:
    summary = get_summary(db_path, days=7)
    daily_rows = aggregate_daily(db_path, days_back=days)
    daily = _aggregate(daily_rows)
    events = query_events(db_path, limit=2000)
    vendor = _vendor_breakdown(events)
    model = _model_breakdown(events)

    cost_chart = {"labels": daily["labels"], "values": daily["cost_cumulative"]}
    daily_chart = {
        "labels": daily["labels"],
        "completed": daily["completed"],
        "failed": daily["failed"],
    }

    import datetime
    html = (
        HTML_TEMPLATE
        .replace("__GENERATED_AT__", datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        .replace("__DAYS__", str(days))
        .replace("__DB_PATH__", db_path)
        .replace("__KPI_REVIEWS__", str(summary["reviews"]))
        .replace("__KPI_ERRORS__", str(summary["errors"]))
        .replace("__KPI_COST__", f"{summary['total_cost_usd']:.3f}")
        .replace("__KPI_AVG_MS__", f"{summary['avg_review_ms'] / 1000:.1f}")
        .replace("__DAILY_JSON__", json.dumps(daily_chart, ensure_ascii=False))
        .replace("__VENDOR_JSON__", json.dumps(vendor, ensure_ascii=False))
        .replace("__MODEL_JSON__", json.dumps(model, ensure_ascii=False))
        .replace("__COST_JSON__", json.dumps(cost_chart, ensure_ascii=False))
        .replace("__RECENT_ERROR_TABLE__", _recent_errors_table(events))
    )
    return html


def main() -> int:
    p = argparse.ArgumentParser(description="Render metrics dashboard html")
    p.add_argument("--db", required=True, help="metrics.db 路径")
    p.add_argument("--out", required=True, help="输出 html 路径")
    p.add_argument("--days", type=int, default=30)
    args = p.parse_args()

    if not os.path.isfile(args.db):
        print(f"[ERROR] db 不存在: {args.db}", file=sys.stderr)
        return 1

    html = render(args.db, days=args.days)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[OK] dashboard 已写出: {args.out} ({len(html)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
