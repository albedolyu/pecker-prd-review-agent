"""
质量趋势仪表盘 -- 读取评审历史数据，生成可视化 HTML 报告
数据源：rule_performance_history.json / .sessions/*.jsonl / achievements.json
        + output/sessions/*.jsonl (funnel telemetry, authority_distribution, DAR retention)

step 3 frontend sync (2026-04-28):
- rule list 从 SchemaRegistry.get(workspace).all_rule_ids() 取 (单点 SoT)
- history.json 只补"性能数据" (total/confirmed/rejected/...)
- zombie (history 有 / registry 没) → drop
- 缺规则 (registry 有 / history 没) → 展示 + status_label='尚未触发'
- 顺手 #4 #5: 从 sessions/*.jsonl 累加 authority_distribution + DAR retention_kind
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
    funnel_extras = _load_funnel_extras(workspace)

    html = _render_html(rule_data, session_data, achievements, prd_name,
                        impact_timeline=impact_timeline,
                        funnel_extras=funnel_extras)

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
    """解析 rule_performance_history.json + 与 SchemaRegistry 对账, 输出三类规则.

    数据源混合策略 (step 3 frontend sync, 2026-04-28):
    - registry (SchemaRegistry.get) — 单点 SoT, 决定"应展示哪些 rule_id"
    - history.json — 只补充"性能数据" (total/confirmed/rejected/...)

    输出三类:
      1. zombie (history 有 / registry 没): drop, 不展示
      2. registry-only (registry 有 / history 没): 展示 + status_label='尚未触发', total=0
      3. 双方都有: 展示 + 性能数据 + status_label=registry status (active/experimental/...)
    """
    # registry 是 SoT, 即使没 history.json 也能列规则
    registry_rules = _get_registry_rules(workspace)

    # history.json 加载 (可选)
    path = os.path.join(workspace, "output", "rule_performance_history.json")
    history_data = {}
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                history_data = json.load(f) or {}
        except (json.JSONDecodeError, OSError):
            history_data = {}

    # registry 全空 (yaml 缺失 fallback) + history 全空 → 真没数据
    if not registry_rules and not history_data:
        return None

    # 按评审日期聚合啄伤度 (只用 registry-known rule 的 history)
    date_scores = {}

    # 双方对账
    registry_ids = set(registry_rules.keys())
    history_ids = set(history_data.keys())
    zombie_ids = history_ids - registry_ids       # history 有 / registry 没

    if zombie_ids:
        # registry-out-of-sync warn (在 stdout, dashboard 是离线工具不依赖 logger)
        print(f"[dashboard] 发现 {len(zombie_ids)} 条 zombie 规则被 drop: {sorted(zombie_ids)}")

    all_rules = []
    for rule_id, rule_def in registry_rules.items():
        entry = history_data.get(rule_id)
        if entry:
            stats = entry.get("stats", {})
            total = stats.get("total", 0)
            confirmed = stats.get("confirmed", 0)
            rejected = stats.get("rejected", 0)
            rejection_rate = entry.get("rejection_rate", 0)
            is_noisy = entry.get("is_noisy", False)
            # status_label: 走 registry status (active/experimental/noisy/deprecated)
            status_label = rule_def.get("status", "active")
            # 按日期汇总 (zombie 不入 trend)
            for h in entry.get("history", []):
                d = h.get("date", "unknown")
                if d not in date_scores:
                    date_scores[d] = {"confirmed": 0, "total": 0}
                date_scores[d]["total"] += 1
                if h.get("outcome") in ("effective_catch", "insufficient_fix"):
                    date_scores[d]["confirmed"] += 1
        else:
            # registry-only: 缺数据
            total = 0
            confirmed = 0
            rejected = 0
            rejection_rate = 0
            is_noisy = False
            status_label = "尚未触发"

        all_rules.append({
            "id": rule_id,
            "name": rule_def.get("name", rule_id),
            "dimension": rule_def.get("dimension", ""),
            "total": total,
            "confirmed": confirmed,
            "rejected": rejected,
            "rejection_rate": rejection_rate,
            "is_noisy": is_noisy,
            "status_label": status_label,
        })

    # top_rules: 按触发数降序取 top 10 (含 0 触发也行, 让 PM 看到 registry-only)
    sorted_rules = sorted(all_rules, key=lambda r: r["total"], reverse=True)
    top_rules = sorted_rules[:10]

    # trend: 按日期排序
    sorted_dates = sorted(date_scores.keys())
    trend = [
        {
            "date": d,
            "score": round(date_scores[d]["confirmed"] / date_scores[d]["total"] * 100, 1) if date_scores[d]["total"] > 0 else 0,
            "total": date_scores[d]["total"],
        }
        for d in sorted_dates
    ]

    return {
        "top_rules": top_rules,
        "trend": trend,
        "all_rules": all_rules,                  # registry 全集 + 性能数据
        "all_rules_count": len(all_rules),       # 与 registry 对齐, 不再含 zombie
        "zombie_dropped_count": len(zombie_ids),
        "registry_only_count": sum(1 for r in all_rules if r["status_label"] == "尚未触发"),
    }


def _get_registry_rules(workspace):
    """从 SchemaRegistry 拉规则字典: rule_id -> {name, dimension, status}.

    fail-soft: registry 加载失败 (yaml 缺失等) 返回 {} 让 dashboard 走 history-only 模式.
    """
    try:
        from review.schema_registry import SchemaRegistry
        reg = SchemaRegistry.get(workspace=workspace)
        ids = reg.all_rule_ids()
        result = {}
        for rid in ids:
            rd = reg.get_rule(rid)
            result[rid] = {
                "name": rd.name,
                "dimension": rd.dimension,
                "status": rd.status,
            }
        return result
    except Exception as exc:
        # registry 失败 fail-soft, dashboard 不阻塞
        print(f"[dashboard] SchemaRegistry 加载失败, 走 history-only: {exc}")
        return {}


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


def _load_funnel_extras(workspace):
    """扫 output/sessions/*.jsonl, 累加 authority_distribution + DAR retention_kind.

    数据来源 (audit #4 #5, 2026-04-28):
    - funnel_stage_after_evidence_verify event: authority_distribution / wiki_mode
    - final_reviewer_done event: retention_kind_dist / minority_kept

    返回 dict: {
        authority_distribution: {canonical: int, contextual: int, generated: int},
        wiki_mode_dist: {sparse: int, rich: int},
        retention_kind_dist: {unanimous: int, majority: int, minority: int},
        minority_kept_total: int,
        sample_count: int (扫到的 final_reviewer_done event 数),
    }
    None 表 sessions/ 目录不存在或全空.
    """
    sessions_dir = os.path.join(workspace, "output", "sessions")
    if not os.path.isdir(sessions_dir):
        return None

    pattern = os.path.join(sessions_dir, "*.jsonl")
    files = glob.glob(pattern)
    if not files:
        return None

    authority_dist = {}
    wiki_mode_dist = {}
    retention_dist = {}
    minority_kept_total = 0
    sample_count = 0
    has_any = False

    for fpath in files:
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    t = obj.get("type", "")
                    if t == "funnel_stage_after_evidence_verify":
                        has_any = True
                        ad = obj.get("authority_distribution") or {}
                        for k, v in ad.items():
                            try:
                                authority_dist[k] = authority_dist.get(k, 0) + int(v)
                            except (TypeError, ValueError):
                                continue
                        wm = obj.get("wiki_mode")
                        if wm:
                            wiki_mode_dist[wm] = wiki_mode_dist.get(wm, 0) + 1
                    elif t == "final_reviewer_done":
                        has_any = True
                        sample_count += 1
                        rkd = obj.get("retention_kind_dist") or {}
                        for k, v in rkd.items():
                            try:
                                retention_dist[k] = retention_dist.get(k, 0) + int(v)
                            except (TypeError, ValueError):
                                continue
                        mk = obj.get("minority_kept", 0)
                        try:
                            minority_kept_total += int(mk)
                        except (TypeError, ValueError):
                            pass
        except OSError:
            continue

    if not has_any:
        return None

    return {
        "authority_distribution": authority_dist,
        "wiki_mode_dist": wiki_mode_dist,
        "retention_kind_dist": retention_dist,
        "minority_kept_total": minority_kept_total,
        "sample_count": sample_count,
    }


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

def _render_rules_table(rule_data):
    """渲染 registry 全集规则表格 (含 status_label).

    show 字段: rule_id / dimension / total / confirmed / rejection_rate / status_label.
    "尚未触发" 标签让 PM 看到 EV-/FN- 已上线但未命中.
    """
    rows = rule_data.get("all_rules") or []
    if not rows:
        return '<div class="no-data">暂无规则</div>'

    def _status_chip(label):
        # 按 label 给样式 (active 绿 / experimental 紫 / 尚未触发 灰)
        if label == "尚未触发":
            cls = "chip-pending"
        elif label == "experimental":
            cls = "chip-exp"
        elif label == "noisy":
            cls = "chip-noisy"
        elif label == "deprecated":
            cls = "chip-dep"
        else:
            cls = "chip-active"
        return f'<span class="rule-chip {cls}">{label}</span>'

    body = []
    for r in rows:
        rate = f'{round((r.get("rejection_rate") or 0) * 100, 1)}%' if r["total"] else "-"
        body.append(
            "<tr>"
            f'<td><code>{r["id"]}</code></td>'
            f'<td>{r.get("dimension","")}</td>'
            f'<td>{r.get("name","")}</td>'
            f'<td>{r["total"]}</td>'
            f'<td>{r["confirmed"]}</td>'
            f'<td>{rate}</td>'
            f'<td>{_status_chip(r["status_label"])}</td>'
            "</tr>"
        )
    return (
        '<table class="rules-table">'
        '<thead><tr><th>rule_id</th><th>维度</th><th>名称</th>'
        '<th>触发数</th><th>有效</th><th>驳回率</th><th>状态</th></tr></thead>'
        '<tbody>' + "".join(body) + '</tbody></table>'
    )


def _render_html(rule_data, session_data, achievements, prd_name=None,
                 impact_timeline=None, funnel_extras=None):
    """构建自包含 HTML，内嵌 Chart.js 图表"""
    title = f"啄木鸟质量趋势 — {prd_name}" if prd_name else "啄木鸟质量趋势仪表盘"
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    # 图5/6: funnel extras (audit #4 #5)
    has_authority = bool(funnel_extras and funnel_extras.get("authority_distribution"))
    if has_authority:
        ad = funnel_extras["authority_distribution"]
        authority_labels = json.dumps(list(ad.keys()), ensure_ascii=False)
        authority_values = json.dumps(list(ad.values()))
    else:
        authority_labels = "[]"
        authority_values = "[]"

    has_dar = bool(funnel_extras and funnel_extras.get("retention_kind_dist"))
    if has_dar:
        rkd = funnel_extras["retention_kind_dist"]
        # 固定顺序便于堆叠柱图比较
        dar_order = ["unanimous", "majority", "minority"]
        dar_labels = json.dumps([k for k in dar_order if k in rkd], ensure_ascii=False)
        dar_values = json.dumps([rkd.get(k, 0) for k in dar_order if k in rkd])
    else:
        dar_labels = "[]"
        dar_values = "[]"

    minority_kept = funnel_extras.get("minority_kept_total", 0) if funnel_extras else 0
    dar_sample = funnel_extras.get("sample_count", 0) if funnel_extras else 0

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

    # 规则全表 (registry SoT, 含 status_label 让 PM 看到 "尚未触发")
    rules_table_html = _render_rules_table(rule_data) if rule_data else \
        '<div class="no-data">暂无规则数据 — registry 未加载</div>'

    # registry sync 横幅 (zombie / registry-only 计数)
    sync_banner_html = ""
    if rule_data:
        zombie_n = rule_data.get("zombie_dropped_count", 0)
        only_n = rule_data.get("registry_only_count", 0)
        if zombie_n or only_n:
            parts = []
            if zombie_n:
                parts.append(f'<span class="banner-warn">已 drop {zombie_n} 条 zombie 规则 (history 有但 registry 已删)</span>')
            if only_n:
                parts.append(f'<span class="banner-info">{only_n} 条 registry 规则尚未触发</span>')
            sync_banner_html = '<div class="sync-banner">' + " · ".join(parts) + '</div>'

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
  /* registry sync banner (zombie / 尚未触发 提示) */
  .sync-banner {{
    background: var(--surface-1);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 12px 18px;
    margin-bottom: 24px;
    font-size: 12px;
    color: var(--text-dim);
  }}
  .sync-banner .banner-warn {{
    color: var(--warning);
    font-weight: 500;
  }}
  .sync-banner .banner-info {{
    color: var(--primary);
    font-weight: 500;
  }}
  /* registry 全集规则表 */
  .rules-table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 12px;
  }}
  .rules-table th {{
    text-align: left;
    color: var(--text-dim);
    font-weight: 500;
    padding: 10px 12px;
    border-bottom: 1px solid var(--border);
    background: rgba(255,255,255,0.02);
  }}
  .rules-table td {{
    padding: 8px 12px;
    border-bottom: 1px solid var(--border);
    color: var(--text);
  }}
  .rules-table code {{
    font-family: ui-monospace, SFMono-Regular, "SF Mono", monospace;
    color: var(--primary);
    font-size: 11px;
  }}
  .rule-chip {{
    display: inline-block;
    padding: 2px 8px;
    border-radius: 999px;
    font-size: 10.5px;
    font-weight: 500;
    letter-spacing: 0.02em;
  }}
  .chip-active   {{ background: var(--tertiary-soft); color: var(--tertiary); border: 1px solid rgba(52,211,153,0.25); }}
  .chip-exp      {{ background: var(--secondary-soft); color: var(--secondary); border: 1px solid rgba(167,139,250,0.25); }}
  .chip-noisy    {{ background: var(--danger-soft); color: var(--danger); border: 1px solid rgba(248,113,113,0.25); }}
  .chip-pending  {{ background: rgba(139,147,167,0.15); color: var(--text-dim); border: 1px solid rgba(139,147,167,0.30); }}
  .chip-dep      {{ background: rgba(91,98,121,0.15); color: var(--text-faint); border: 1px solid rgba(91,98,121,0.25); text-decoration: line-through; }}
  /* DAR / authority 双 panel */
  .extras-grid {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 20px;
    margin-bottom: 32px;
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

<!-- 图5/6: wiki authority + DAR retention (audit #4 #5) -->
<div class="extras-grid">
  <div class="chart-card">
    <h3>wiki 权威性分布 (canonical / contextual / generated)</h3>
    {'<div class="chart-wrap"><canvas id="authorityChart"></canvas></div>' if has_authority else '<div class="no-data">暂无 funnel telemetry — 跑过评审后自动出</div>'}
  </div>
  <div class="chart-card">
    <h3>苍鹰 DAR 保留分布 ({minority_kept} 条少数派保留 / {dar_sample} sample)</h3>
    {'<div class="chart-wrap"><canvas id="darChart"></canvas></div>' if has_dar else '<div class="no-data">暂无 DAR retention_kind_dist — 苍鹰多 sample 模式触发后自动出</div>'}
  </div>
</div>

<!-- registry 全集规则表 (Day5 SoT, 含 status_label) -->
<div class="ach-section">
  <h3>规则全集 (registry SoT)</h3>
  {sync_banner_html}
  {rules_table_html}
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

  // ---- 图5: wiki authority distribution (audit #4) ----
  const authorityLabels = {authority_labels};
  const authorityValues = {authority_values};
  if (authorityLabels.length > 0) {{
    new Chart(document.getElementById('authorityChart'), {{
      type: 'doughnut',
      data: {{
        labels: authorityLabels,
        datasets: [{{
          data: authorityValues,
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

  // ---- 图6: DAR retention_kind 堆叠柱图 (audit #5) ----
  const darLabels = {dar_labels};
  const darValues = {dar_values};
  if (darLabels.length > 0) {{
    new Chart(document.getElementById('darChart'), {{
      type: 'bar',
      data: {{
        labels: darLabels,
        datasets: [{{
          label: 'item 数',
          data: darValues,
          backgroundColor: [COLORS.tertiary, COLORS.primary, COLORS.secondary],
          borderRadius: 6,
          borderSkipped: false,
        }}]
      }},
      options: {{
        responsive: true,
        maintainAspectRatio: false,
        plugins: {{ legend: {{ display: false }} }},
        scales: {{
          x: {{ grid: {{ display: false }} }},
          y: {{ beginAtZero: true, grid: {{ color: COLORS.grid }} }}
        }}
      }}
    }});
  }}
</script>
</body>
</html>"""
