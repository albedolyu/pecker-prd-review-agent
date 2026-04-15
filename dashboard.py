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

    html = _render_html(rule_data, session_data, achievements, prd_name)

    output_dir = os.path.join(workspace, "output")
    os.makedirs(output_dir, exist_ok=True)
    out_path = os.path.join(output_dir, "dashboard.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)

    return os.path.abspath(out_path)


# ============================================================
# 数据加载
# ============================================================

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

def _render_html(rule_data, session_data, achievements, prd_name=None):
    """构建自包含 HTML，内嵌 Chart.js 图表"""
    title = f"啄木鸟质量趋势 — {prd_name}" if prd_name else "啄木鸟质量趋势仪表盘"
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

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
    --bg: #1a1a12;
    --card: #252518;
    --border: #3a3a28;
    --text: #d4cdb0;
    --text-dim: #8a8470;
    --accent: #6b8f3c;
    --accent2: #a67c3d;
    --accent3: #8b5e3c;
    --danger: #a05040;
    --success: #5a8a3a;
  }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: "PingFang SC", "Microsoft YaHei", -apple-system, sans-serif;
    background: var(--bg);
    color: var(--text);
    min-height: 100vh;
    padding: 24px;
  }}
  .header {{
    text-align: center;
    margin-bottom: 32px;
    padding-bottom: 20px;
    border-bottom: 2px solid var(--border);
  }}
  .header h1 {{
    font-size: 28px;
    font-weight: 700;
    color: var(--accent);
    margin-bottom: 6px;
  }}
  .header .subtitle {{
    color: var(--text-dim);
    font-size: 14px;
  }}
  .stats-row {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: 16px;
    margin-bottom: 28px;
  }}
  .stat-card {{
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 18px 20px;
    text-align: center;
  }}
  .stat-card .num {{
    font-size: 32px;
    font-weight: 700;
    color: var(--accent);
  }}
  .stat-card .label {{
    font-size: 13px;
    color: var(--text-dim);
    margin-top: 4px;
  }}
  .chart-grid {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 24px;
    margin-bottom: 28px;
  }}
  .chart-card {{
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 20px;
  }}
  .chart-card.full-width {{
    grid-column: 1 / -1;
  }}
  .chart-card h3 {{
    font-size: 16px;
    font-weight: 600;
    color: var(--text);
    margin-bottom: 14px;
    padding-left: 10px;
    border-left: 3px solid var(--accent);
  }}
  .chart-wrap {{
    position: relative;
    width: 100%;
    max-height: 320px;
  }}
  .no-data {{
    color: var(--text-dim);
    font-style: italic;
    text-align: center;
    padding: 40px 0;
    font-size: 14px;
  }}
  .ach-section {{
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 20px;
    margin-bottom: 24px;
  }}
  .ach-section h3 {{
    font-size: 16px;
    font-weight: 600;
    margin-bottom: 12px;
    padding-left: 10px;
    border-left: 3px solid var(--accent2);
  }}
  .ach-badge {{
    display: inline-block;
    background: var(--accent2);
    color: #fff;
    padding: 4px 12px;
    border-radius: 20px;
    font-size: 13px;
    margin: 4px;
  }}
  .ach-badge small {{
    opacity: 0.7;
  }}
  .footer {{
    text-align: center;
    color: var(--text-dim);
    font-size: 12px;
    padding-top: 16px;
    border-top: 1px solid var(--border);
  }}
  @media (max-width: 768px) {{
    .chart-grid {{ grid-template-columns: 1fr; }}
    .stats-row {{ grid-template-columns: 1fr 1fr; }}
  }}
</style>
</head>
<body>

<div class="header">
  <h1>{title}</h1>
  <div class="subtitle">生成时间: {now}</div>
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
</div>

<div class="ach-section">
  <h3>成就墙</h3>
  {ach_html}
</div>

<div class="footer">
  啄木鸟 PRD 评审系统 &mdash; 质量趋势仪表盘
</div>

<script>
  // 配色
  const COLORS = {{
    green: '#6b8f3c',
    greenLight: 'rgba(107,143,60,0.3)',
    brown: '#a67c3d',
    brownLight: 'rgba(166,124,61,0.3)',
    red: '#a05040',
    redLight: 'rgba(160,80,64,0.3)',
    text: '#d4cdb0',
    grid: 'rgba(58,58,40,0.6)',
  }};

  Chart.defaults.color = COLORS.text;
  Chart.defaults.borderColor = COLORS.grid;

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
          borderColor: COLORS.green,
          backgroundColor: COLORS.greenLight,
          fill: true,
          tension: 0.35,
          pointRadius: 5,
          pointBackgroundColor: COLORS.green,
        }}, {{
          label: '触发次数',
          data: trendTotals,
          borderColor: COLORS.brown,
          backgroundColor: 'transparent',
          borderDash: [5, 5],
          tension: 0.35,
          pointRadius: 3,
          yAxisID: 'y1',
        }}]
      }},
      options: {{
        responsive: true,
        maintainAspectRatio: false,
        plugins: {{
          legend: {{ position: 'top' }},
          tooltip: {{
            callbacks: {{
              label: function(ctx) {{
                if (ctx.datasetIndex === 0) return '啄伤度: ' + ctx.parsed.y + '%';
                return '触发: ' + ctx.parsed.y + ' 次';
              }}
            }}
          }}
        }},
        scales: {{
          y: {{
            beginAtZero: true,
            max: 100,
            title: {{ display: true, text: '啄伤度 (%)' }},
          }},
          y1: {{
            position: 'right',
            beginAtZero: true,
            title: {{ display: true, text: '触发次数' }},
            grid: {{ drawOnChartArea: false }},
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
          backgroundColor: COLORS.green,
          borderRadius: 4,
        }}, {{
          label: '被驳回',
          data: ruleRejected,
          backgroundColor: COLORS.red,
          borderRadius: 4,
        }}]
      }},
      options: {{
        responsive: true,
        maintainAspectRatio: false,
        plugins: {{
          legend: {{ position: 'top' }},
        }},
        scales: {{
          x: {{
            ticks: {{ maxRotation: 45, font: {{ size: 11 }} }},
          }},
          y: {{
            beginAtZero: true,
            title: {{ display: true, text: '次数' }},
          }}
        }}
      }}
    }});
  }}

  // ---- 图3: Reviewer 工作量 ----
  const reviewerLabels = {reviewer_labels};
  const reviewerValues = {reviewer_values};
  if (reviewerLabels.length > 0) {{
    new Chart(document.getElementById('reviewerChart'), {{
      type: 'doughnut',
      data: {{
        labels: reviewerLabels,
        datasets: [{{
          data: reviewerValues,
          backgroundColor: [
            COLORS.green, COLORS.brown, COLORS.red,
            '#5a7a8a', '#8a6a9a', '#6a8a6a', '#9a8a5a',
          ],
          borderColor: '#252518',
          borderWidth: 2,
        }}]
      }},
      options: {{
        responsive: true,
        maintainAspectRatio: false,
        plugins: {{
          legend: {{ position: 'bottom', labels: {{ padding: 16 }} }},
        }}
      }}
    }});
  }}
</script>
</body>
</html>"""
