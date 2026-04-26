"""
质量趋势仪表盘 -- 读取评审历史数据，生成可视化 HTML 报告
数据源：rule_performance_history.json / .sessions/*.jsonl / achievements.json
"""

import json
import os
import glob
from datetime import datetime


def generate_dashboard(workspace, prd_name=None):
    """主入口：生成仪表盘 HTML，返回文件绝对路径"""
    rule_data = _load_rule_history(workspace)
    session_data = _load_session_stats(workspace)
    achievements = _load_achievements(workspace)
    impact_timeline = _load_impact_timeline(workspace)

    html = _render_html(rule_data, session_data, achievements, prd_name,
                        impact_timeline=impact_timeline)

    output_dir = os.path.join(workspace, "output")
    os.makedirs(output_dir, exist_ok=True)
    out_path = os.path.join(output_dir, "dashboard.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)

    return os.path.abspath(out_path)


# ============================================================
# 数据加载
# ============================================================

def _load_impact_timeline(workspace, top_n=8):
    """读取 rule_impact_timeline.json,返回 top_n 个 rule 的 (ts, score) 时序.

    只返回最近被调整次数最多的 top_n 条 rule,避免 chart 图线过多。
    数据结构: [{"rule_id": "V-02", "points": [{"ts": "...", "score": 0.5}, ...]}]
    """
    path = os.path.join(workspace, "output", "rule_impact_timeline.json")
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None
    if not data:
        return None

    # 按该 rule 累计调整次数降序,取 top_n
    ranked = sorted(data.items(), key=lambda kv: len(kv[1]), reverse=True)[:top_n]
    return [
        {
            "rule_id": rid,
            "points": [
                {"ts": h["ts"], "score": h["score"]}
                for h in entries
            ],
        }
        for rid, entries in ranked
    ]


def _load_rule_history(workspace):
    """解析 rule_performance_history.json，提取每条规则的统计"""
    path = os.path.join(workspace, "output", "rule_performance_history.json")
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None

    if not data:
        return None

    rules = []
    # 按评审日期聚合啄伤度（confirmed / total）
    date_scores = {}  # date -> {confirmed, total}
    for rule_id, entry in data.items():
        stats = entry.get("stats", {})
        total = stats.get("total", 0)
        confirmed = stats.get("confirmed", 0)
        rejected = stats.get("rejected", 0)
        rules.append({
            "id": rule_id,
            "total": total,
            "confirmed": confirmed,
            "rejected": rejected,
            "rejection_rate": entry.get("rejection_rate", 0),
            "is_noisy": entry.get("is_noisy", False),
        })
        # 按日期汇总
        for h in entry.get("history", []):
            d = h.get("date", "unknown")
            if d not in date_scores:
                date_scores[d] = {"confirmed": 0, "total": 0}
            date_scores[d]["total"] += 1
            if h.get("outcome") in ("effective_catch", "insufficient_fix"):
                date_scores[d]["confirmed"] += 1

    # 排序：按触发总数降序取 top 10
    rules.sort(key=lambda r: r["total"], reverse=True)
    top_rules = rules[:10]

    # 日期排序
    sorted_dates = sorted(date_scores.keys())
    trend = [
        {
            "date": d,
            "score": round(date_scores[d]["confirmed"] / date_scores[d]["total"] * 100, 1) if date_scores[d]["total"] > 0 else 0,
            "total": date_scores[d]["total"],
        }
        for d in sorted_dates
    ]

    return {"top_rules": top_rules, "trend": trend, "all_rules_count": len(rules)}


def _load_session_stats(workspace):
    """扫描 .sessions/*.jsonl，提取日期、reviewer、轮次"""
    sessions_dir = os.path.join(workspace, "output", ".sessions")
    if not os.path.isdir(sessions_dir):
        return None

    pattern = os.path.join(sessions_dir, "*.jsonl")
    files = glob.glob(pattern)
    if not files:
        return None

    sessions = []
    reviewer_counts = {}  # reviewer -> 评审次数

    for fpath in files:
        fname = os.path.basename(fpath)
        # 文件名格式：reviewer_prdname.jsonl
        parts = fname.replace(".jsonl", "").split("_", 1)
        reviewer = parts[0] if parts else "unknown"

        turn_count = 0
        first_ts = None
        last_ts = None
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        turn = json.loads(line)
                        turn_count += 1
                        ts = turn.get("timestamp")
                        if ts:
                            if first_ts is None:
                                first_ts = ts
                            last_ts = ts
                    except json.JSONDecodeError:
                        continue
        except OSError:
            continue

        sessions.append({
            "file": fname,
            "reviewer": reviewer,
            "turns": turn_count,
            "first_ts": first_ts,
            "last_ts": last_ts,
        })
        reviewer_counts[reviewer] = reviewer_counts.get(reviewer, 0) + 1

    return {"sessions": sessions, "reviewer_counts": reviewer_counts}


def _load_achievements(workspace):
    """加载成就数据（从 wiki 目录）"""
    # wiki 目录与 workspace 同级或在其中
    wiki_path = os.path.join(workspace, "wiki")
    ach_path = os.path.join(wiki_path, "achievements.json")
    if not os.path.isfile(ach_path):
        return None
    try:
        with open(ach_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


# ============================================================
# HTML 渲染
# ============================================================

def _render_html(rule_data, session_data, achievements, prd_name=None,
                 impact_timeline=None):
    """构建自包含 HTML，内嵌 Chart.js 图表"""
    title = f"啄木鸟质量趋势 — {prd_name}" if prd_name else "啄木鸟质量趋势仪表盘"
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    # 图4: rule impact_score 时序曲线 (feedback loop 调节轨迹)
    impact_series = "[]"
    has_impact = False
    if impact_timeline:
        has_impact = True
        impact_series = json.dumps([
            {
                "rule_id": s["rule_id"],
                "data": [{"x": p["ts"], "y": p["score"]} for p in s["points"]],
            }
            for s in impact_timeline
        ], ensure_ascii=False)

    # 准备图表数据 JSON
    # 图1: 啄伤度趋势
    if rule_data and rule_data["trend"]:
        trend_labels = json.dumps([t["date"] for t in rule_data["trend"]], ensure_ascii=False)
        trend_scores = json.dumps([t["score"] for t in rule_data["trend"]])
        trend_totals = json.dumps([t["total"] for t in rule_data["trend"]])
    else:
        trend_labels = "[]"
        trend_scores = "[]"
        trend_totals = "[]"

    # 图2: 规则触发频率 top 10
    if rule_data and rule_data["top_rules"]:
        rule_labels = json.dumps([r["id"] for r in rule_data["top_rules"]], ensure_ascii=False)
        rule_confirmed = json.dumps([r["confirmed"] for r in rule_data["top_rules"]])
        rule_rejected = json.dumps([r["rejected"] for r in rule_data["top_rules"]])
    else:
        rule_labels = "[]"
        rule_confirmed = "[]"
        rule_rejected = "[]"

    # 图3: Reviewer 工作量
    if session_data and session_data["reviewer_counts"]:
        rv = session_data["reviewer_counts"]
        reviewer_labels = json.dumps(list(rv.keys()), ensure_ascii=False)
        reviewer_values = json.dumps(list(rv.values()))
    else:
        reviewer_labels = "[]"
        reviewer_values = "[]"

    # 成就列表
    ach_html = ""
    if achievements and achievements.get("unlocked"):
        items = []
        for key, date_str in achievements["unlocked"].items():
            items.append(f'<span class="ach-badge">{key} <small>({date_str})</small></span>')
        ach_html = " ".join(items)
    else:
        ach_html = '<span class="no-data">暂无解锁成就</span>'

    # 统计概览
    total_rules = rule_data["all_rules_count"] if rule_data else 0
    total_sessions = len(session_data["sessions"]) if session_data else 0
    total_reviews_ach = achievements.get("stats", {}).get("total_reviews", 0) if achievements else 0

    has_trend = rule_data and rule_data["trend"]
    has_rules = rule_data and rule_data["top_rules"]
    has_reviewers = session_data and session_data["reviewer_counts"]

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<style>
  :root {{
    /* 现代深色 — 2026-04-26 重设计 */
    --bg-base: #0b1020;
    --bg-radial: radial-gradient(1200px 600px at 20% 0%, rgba(56,189,248,0.08), transparent 60%),
                 radial-gradient(900px 500px at 90% 100%, rgba(167,139,250,0.06), transparent 60%);
    --surface-1: rgba(22, 27, 46, 0.6);
    --surface-2: rgba(28, 34, 56, 0.75);
    --border: rgba(255,255,255,0.08);
    --border-strong: rgba(255,255,255,0.14);
    --text: #e6e8ee;
    --text-dim: #8b93a7;
    --text-faint: #5a6178;

    --primary: #38bdf8;       /* sky */
    --primary-soft: rgba(56,189,248,0.15);
    --secondary: #a78bfa;     /* violet */
    --secondary-soft: rgba(167,139,250,0.15);
    --tertiary: #34d399;      /* emerald */
    --tertiary-soft: rgba(52,211,153,0.15);
    --danger: #f87171;        /* red */
    --danger-soft: rgba(248,113,113,0.15);
    --warning: #fbbf24;       /* amber */
  }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  html {{ scroll-behavior: smooth; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Inter", "PingFang SC", "Microsoft YaHei", sans-serif;
    background: var(--bg-base);
    background-image: var(--bg-radial);
    background-attachment: fixed;
    color: var(--text);
    min-height: 100vh;
    padding: 32px 24px 64px;
    font-feature-settings: "tnum", "ss01";
    -webkit-font-smoothing: antialiased;
  }}
  .container {{
    max-width: 1280px;
    margin: 0 auto;
  }}
  .header {{
    margin-bottom: 40px;
    padding-bottom: 28px;
    border-bottom: 1px solid var(--border);
  }}
  .header .eyebrow {{
    font-size: 12px;
    font-weight: 600;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: var(--primary);
    margin-bottom: 12px;
  }}
  .header h1 {{
    font-size: 30px;
    font-weight: 700;
    letter-spacing: -0.02em;
    background: linear-gradient(135deg, #fff 0%, #c7d2fe 100%);
    -webkit-background-clip: text;
    background-clip: text;
    -webkit-text-fill-color: transparent;
    margin-bottom: 8px;
  }}
  .header .subtitle {{
    color: var(--text-dim);
    font-size: 13px;
    font-weight: 500;
  }}
  .stats-row {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 16px;
    margin-bottom: 32px;
  }}
  .stat-card {{
    position: relative;
    background: var(--surface-1);
    border: 1px solid var(--border);
    border-radius: 14px;
    padding: 20px 22px;
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
    transition: transform 180ms ease, border-color 180ms ease, background 180ms ease;
    overflow: hidden;
  }}
  .stat-card::before {{
    content: "";
    position: absolute;
    inset: 0;
    background: linear-gradient(135deg, transparent 60%, var(--primary-soft) 100%);
    opacity: 0;
    transition: opacity 220ms ease;
    pointer-events: none;
  }}
  .stat-card:hover {{
    transform: translateY(-2px);
    border-color: var(--border-strong);
    background: var(--surface-2);
  }}
  .stat-card:hover::before {{ opacity: 1; }}
  .stat-card .num {{
    font-size: 36px;
    font-weight: 700;
    line-height: 1.1;
    letter-spacing: -0.02em;
    background: linear-gradient(135deg, var(--primary) 0%, #818cf8 100%);
    -webkit-background-clip: text;
    background-clip: text;
    -webkit-text-fill-color: transparent;
  }}
  .stat-card .label {{
    font-size: 12px;
    color: var(--text-dim);
    margin-top: 8px;
    font-weight: 500;
    letter-spacing: 0.02em;
  }}
  .chart-grid {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 20px;
    margin-bottom: 32px;
  }}
  .chart-card {{
    background: var(--surface-1);
    border: 1px solid var(--border);
    border-radius: 16px;
    padding: 24px;
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
    transition: border-color 220ms ease;
  }}
  .chart-card:hover {{ border-color: var(--border-strong); }}
  .chart-card.full-width {{ grid-column: 1 / -1; }}
  .chart-card h3 {{
    font-size: 14px;
    font-weight: 600;
    color: var(--text);
    margin-bottom: 18px;
    letter-spacing: -0.01em;
    display: flex;
    align-items: center;
    gap: 10px;
  }}
  .chart-card h3::before {{
    content: "";
    width: 4px;
    height: 16px;
    background: linear-gradient(180deg, var(--primary), var(--secondary));
    border-radius: 2px;
  }}
  .chart-wrap {{
    position: relative;
    width: 100%;
    height: 300px;
  }}
  .chart-card.full-width .chart-wrap {{ height: 320px; }}
  .no-data {{
    color: var(--text-faint);
    font-style: normal;
    text-align: center;
    padding: 60px 0;
    font-size: 13px;
    letter-spacing: 0.02em;
  }}
  .ach-section {{
    background: var(--surface-1);
    border: 1px solid var(--border);
    border-radius: 16px;
    padding: 24px;
    margin-bottom: 24px;
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
  }}
  .ach-section h3 {{
    font-size: 14px;
    font-weight: 600;
    margin-bottom: 16px;
    display: flex;
    align-items: center;
    gap: 10px;
    letter-spacing: -0.01em;
  }}
  .ach-section h3::before {{
    content: "";
    width: 4px;
    height: 16px;
    background: linear-gradient(180deg, var(--secondary), var(--tertiary));
    border-radius: 2px;
  }}
  .ach-badge {{
    display: inline-flex;
    align-items: center;
    gap: 6px;
    background: var(--secondary-soft);
    color: #ddd6fe;
    padding: 6px 14px;
    border-radius: 999px;
    font-size: 12px;
    font-weight: 500;
    margin: 4px 4px 0 0;
    border: 1px solid rgba(167,139,250,0.25);
    transition: transform 150ms ease;
  }}
  .ach-badge:hover {{
    transform: translateY(-1px);
    border-color: rgba(167,139,250,0.45);
  }}
  .ach-badge small {{
    opacity: 0.6;
    font-weight: 400;
  }}
  .footer {{
    text-align: center;
    color: var(--text-faint);
    font-size: 12px;
    padding-top: 24px;
    border-top: 1px solid var(--border);
    letter-spacing: 0.02em;
  }}
  @media (max-width: 900px) {{
    body {{ padding: 20px 16px 48px; }}
    .chart-grid {{ grid-template-columns: 1fr; gap: 16px; }}
    .stats-row {{ grid-template-columns: repeat(2, 1fr); }}
    .header h1 {{ font-size: 24px; }}
    .stat-card .num {{ font-size: 28px; }}
  }}
  @media (max-width: 480px) {{
    .stats-row {{ grid-template-columns: 1fr; }}
  }}
</style>
</head>
<body>
<div class="container">

<div class="header">
  <div class="eyebrow">啄木鸟 · Quality Dashboard</div>
  <h1>{title}</h1>
  <div class="subtitle">生成时间 {now}</div>
</div>

<div class="stats-row">
  <div class="stat-card">
    <div class="num">{total_rules}</div>
    <div class="label">已跟踪规则数</div>
  </div>
  <div class="stat-card">
    <div class="num">{total_sessions}</div>
    <div class="label">评审会话数</div>
  </div>
  <div class="stat-card">
    <div class="num">{total_reviews_ach}</div>
    <div class="label">累计评审次数</div>
  </div>
  <div class="stat-card">
    <div class="num">{len(achievements.get('unlocked', {})) if achievements else 0}</div>
    <div class="label">已解锁成就</div>
  </div>
</div>

<div class="chart-grid">
  <!-- 图1: 啄伤度趋势 -->
  <div class="chart-card full-width">
    <h3>啄伤度趋势（有效发现率 %）</h3>
    {'<div class="chart-wrap"><canvas id="trendChart"></canvas></div>' if has_trend else '<div class="no-data">暂无数据 — 完成评审后自动生成趋势</div>'}
  </div>

  <!-- 图2: 规则触发频率 -->
  <div class="chart-card">
    <h3>规则触发频率 TOP 10</h3>
    {'<div class="chart-wrap"><canvas id="ruleChart"></canvas></div>' if has_rules else '<div class="no-data">暂无数据</div>'}
  </div>

  <!-- 图3: Reviewer 工作量 -->
  <div class="chart-card">
    <h3>Reviewer 工作量统计</h3>
    {'<div class="chart-wrap"><canvas id="reviewerChart"></canvas></div>' if has_reviewers else '<div class="no-data">暂无数据</div>'}
  </div>

  <!-- 图4: rule impact_score 时序 (feedback loop 调节轨迹) -->
  <div class="chart-card full-width">
    <h3>规则权重调节轨迹 (impact_score 时序)</h3>
    {'<div class="chart-wrap"><canvas id="impactChart"></canvas></div>' if has_impact else '<div class="no-data">暂无 EMA 更新记录 — 跑 feedback.py 后自动生成</div>'}
  </div>
</div>

<div class="ach-section">
  <h3>成就墙</h3>
  {ach_html}
</div>

<div class="footer">
  啄木鸟 PRD 评审系统 · Quality Dashboard
</div>

</div><!-- /container -->

<script>
  // 现代配色 — 2026-04-26 重设计
  const COLORS = {{
    primary: '#38bdf8',     primarySoft: 'rgba(56,189,248,0.15)',
    secondary: '#a78bfa',   secondarySoft: 'rgba(167,139,250,0.15)',
    tertiary: '#34d399',    tertiarySoft: 'rgba(52,211,153,0.15)',
    danger: '#f87171',      dangerSoft: 'rgba(248,113,113,0.15)',
    warning: '#fbbf24',
    text: '#e6e8ee',
    textDim: '#8b93a7',
    grid: 'rgba(255,255,255,0.06)',
    gridStrong: 'rgba(255,255,255,0.10)',
  }};
  // chart 8 色调色板 (柔和不刺眼)
  const PALETTE = [
    '#38bdf8', '#a78bfa', '#34d399', '#fbbf24',
    '#f472b6', '#22d3ee', '#fb923c', '#818cf8',
  ];

  Chart.defaults.color = COLORS.textDim;
  Chart.defaults.borderColor = COLORS.grid;
  Chart.defaults.font.family = "-apple-system,'Inter','PingFang SC',sans-serif";
  Chart.defaults.font.size = 11;
  Chart.defaults.plugins.tooltip = {{
    backgroundColor: 'rgba(11,16,32,0.95)',
    titleColor: COLORS.text,
    bodyColor: COLORS.text,
    borderColor: COLORS.gridStrong,
    borderWidth: 1,
    padding: 12,
    cornerRadius: 8,
    titleFont: {{ size: 12, weight: '600' }},
    bodyFont: {{ size: 12 }},
    boxPadding: 6,
  }};
  Chart.defaults.plugins.legend.labels = {{
    padding: 14,
    usePointStyle: true,
    pointStyle: 'circle',
    font: {{ size: 11, weight: '500' }},
  }};

  // 渐变填充 helper
  function gradientFill(ctx, color1, color2) {{
    const chart = ctx.chart;
    const {{ ctx: c, chartArea }} = chart;
    if (!chartArea) return color1;
    const g = c.createLinearGradient(0, chartArea.top, 0, chartArea.bottom);
    g.addColorStop(0, color1);
    g.addColorStop(1, color2);
    return g;
  }}

  // ---- 图1: 啄伤度趋势折线图 ----
  const trendLabels = {trend_labels};
  const trendScores = {trend_scores};
  const trendTotals = {trend_totals};
  if (trendLabels.length > 0) {{
    new Chart(document.getElementById('trendChart'), {{
      type: 'line',
      data: {{
        labels: trendLabels,
        datasets: [{{
          label: '啄伤度 (%)',
          data: trendScores,
          borderColor: COLORS.primary,
          backgroundColor: (ctx) => gradientFill(ctx, 'rgba(56,189,248,0.30)', 'rgba(56,189,248,0)'),
          fill: true,
          tension: 0.4,
          pointRadius: 0,
          pointHoverRadius: 6,
          pointHoverBackgroundColor: COLORS.primary,
          pointHoverBorderColor: '#fff',
          pointHoverBorderWidth: 2,
          borderWidth: 2.5,
        }}, {{
          label: '触发次数',
          data: trendTotals,
          borderColor: COLORS.secondary,
          backgroundColor: 'transparent',
          borderDash: [4, 4],
          tension: 0.4,
          pointRadius: 0,
          pointHoverRadius: 5,
          pointHoverBackgroundColor: COLORS.secondary,
          borderWidth: 2,
          yAxisID: 'y1',
        }}]
      }},
      options: {{
        responsive: true,
        maintainAspectRatio: false,
        interaction: {{ mode: 'index', intersect: false }},
        plugins: {{
          legend: {{ position: 'top', align: 'end' }},
          tooltip: {{
            callbacks: {{
              label: function(ctx) {{
                if (ctx.datasetIndex === 0) return '  啄伤度  ' + ctx.parsed.y + '%';
                return '  触发  ' + ctx.parsed.y + ' 次';
              }}
            }}
          }}
        }},
        scales: {{
          y: {{
            beginAtZero: true, max: 100,
            title: {{ display: true, text: '啄伤度 %', color: COLORS.textDim, font: {{ size: 11 }} }},
            grid: {{ color: COLORS.grid }},
            ticks: {{ stepSize: 25 }},
          }},
          y1: {{
            position: 'right', beginAtZero: true,
            title: {{ display: true, text: '触发次数', color: COLORS.textDim, font: {{ size: 11 }} }},
            grid: {{ drawOnChartArea: false }},
          }},
          x: {{
            grid: {{ color: COLORS.grid }},
          }}
        }}
      }}
    }});
  }}

  // ---- 图2: 规则触发频率柱状图 ----
  const ruleLabels = {rule_labels};
  const ruleConfirmed = {rule_confirmed};
  const ruleRejected = {rule_rejected};
  if (ruleLabels.length > 0) {{
    new Chart(document.getElementById('ruleChart'), {{
      type: 'bar',
      data: {{
        labels: ruleLabels,
        datasets: [{{
          label: '有效确认',
          data: ruleConfirmed,
          backgroundColor: COLORS.tertiary,
          hoverBackgroundColor: '#10b981',
          borderRadius: 6,
          borderSkipped: false,
        }}, {{
          label: '被驳回',
          data: ruleRejected,
          backgroundColor: COLORS.danger,
          hoverBackgroundColor: '#ef4444',
          borderRadius: 6,
          borderSkipped: false,
        }}]
      }},
      options: {{
        responsive: true,
        maintainAspectRatio: false,
        plugins: {{ legend: {{ position: 'top', align: 'end' }} }},
        scales: {{
          x: {{
            grid: {{ display: false }},
            ticks: {{ maxRotation: 45, font: {{ size: 10 }} }},
          }},
          y: {{
            beginAtZero: true,
            grid: {{ color: COLORS.grid }},
            title: {{ display: true, text: '次数', color: COLORS.textDim, font: {{ size: 11 }} }},
          }}
        }}
      }}
    }});
  }}

  // ---- 图3: Reviewer 工作量 (现代环图) ----
  const reviewerLabels = {reviewer_labels};
  const reviewerValues = {reviewer_values};
  if (reviewerLabels.length > 0) {{
    new Chart(document.getElementById('reviewerChart'), {{
      type: 'doughnut',
      data: {{
        labels: reviewerLabels,
        datasets: [{{
          data: reviewerValues,
          backgroundColor: PALETTE,
          borderColor: 'rgba(11,16,32,0.9)',
          borderWidth: 3,
          hoverOffset: 8,
        }}]
      }},
      options: {{
        responsive: true,
        maintainAspectRatio: false,
        cutout: '62%',
        plugins: {{
          legend: {{ position: 'bottom', labels: {{ padding: 14, boxWidth: 8, boxHeight: 8 }} }},
        }}
      }}
    }});
  }}

  // ---- 图4: rule impact_score 时序 (feedback loop 调节轨迹) ----
  const impactSeries = {impact_series};
  if (impactSeries.length > 0) {{
    new Chart(document.getElementById('impactChart'), {{
      type: 'line',
      data: {{
        datasets: impactSeries.map((s, i) => {{
          const color = PALETTE[i % PALETTE.length];
          return {{
            label: s.rule_id,
            data: s.data,
            borderColor: color,
            backgroundColor: color + '20',
            tension: 0.3,
            pointRadius: 0,
            pointHoverRadius: 5,
            pointHoverBackgroundColor: color,
            pointHoverBorderColor: '#fff',
            pointHoverBorderWidth: 2,
            borderWidth: 2,
          }};
        }}),
      }},
      options: {{
        responsive: true,
        maintainAspectRatio: false,
        interaction: {{ mode: 'nearest', intersect: false }},
        plugins: {{ legend: {{ position: 'top', align: 'end' }} }},
        scales: {{
          x: {{
            type: 'timeseries',
            grid: {{ color: COLORS.grid }},
            ticks: {{ maxRotation: 45, font: {{ size: 10 }} }},
          }},
          y: {{
            min: 0, max: 1,
            grid: {{ color: COLORS.grid }},
            title: {{ display: true, text: 'impact_score (0=弱 → 1=强)', color: COLORS.textDim, font: {{ size: 11 }} }},
          }}
        }}
      }}
    }});
  }}
</script>
</body>
</html>"""
