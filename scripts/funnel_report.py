"""T3 闭环 — Pecker 评审漏斗聚合报告 (2026-04-24).

spec: docs/review-funnel-schema.md 第三节

消费 T3 (commit 0a90d3b) 写入 workspace-*/output/sessions/rev_*.jsonl 的 funnel_stage_*
和 funnel_summary 事件, 聚合最近 N 次跑出趋势表.

向后兼容: 对 T3 之前的老 session 降级处理 — 从 worker_done / checkpoint /
final_reviewer_done / review_completed 拼出能算的部分 (N2 丢失, N4 丢失).

用法:
  python scripts/funnel_report.py                          # 全部 workspace, 最近 10 次
  python scripts/funnel_report.py --workspace workspace-侵权软件 --last 5
  python scripts/funnel_report.py --format json            # 机器消费
  python scripts/funnel_report.py --out-file docs/funnel-report-YYYY-MM-DD.md
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from collections import defaultdict
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ============================================================
# JSONL 读取 + stage 事件提取
# ============================================================

def _read_jsonl(path):
    """读 jsonl, 每行 json, 容错: 解析失败的行跳过."""
    events = []
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
        pass
    return events


def extract_funnel_from_session(jsonl_path):
    """从一个 session jsonl 提取 funnel 信息. 返回 dict, 缺失的 stage 值为 None.

    优先用 T3 (2026-04-24 后) 的 funnel_stage_* / funnel_summary 事件,
    降级到老字段 (worker_done / checkpoint / review_completed) 拼 N0/N1/N3.

    Returns: {
        "session_id": str,  # 从文件名推
        "ts_start": str,
        "prd_files": [str],
        "mode": str,
        "N0": int | None, "N1": int | None, "N2": int | None, "N3": int | None, "N4": int | None,
        "retracted": int | None,
        "downgraded": int | None,
        "wiki_mode": str | None,
        "authority_distribution": dict,
        "delta_breakdown": dict | None,
        "rejected_by_reason": dict,
        "suspicious_flags": [str],
        "review_completed": bool,
    }
    """
    events = _read_jsonl(jsonl_path)
    session_id = os.path.basename(jsonl_path).replace(".jsonl", "")

    info = {
        "session_id": session_id,
        "ts_start": "",
        "prd_files": [],
        "mode": "",
        "N0": None, "N1": None, "N2": None, "N3": None, "N4": None,
        "retracted": None,
        "downgraded": None,
        "wiki_mode": None,
        "authority_distribution": {},
        "delta_breakdown": None,
        "rejected_by_reason": {},
        "suspicious_flags": [],
        "review_completed": False,
        "source_events": [],  # T3 = native, legacy = 降级
    }

    # 先扫 review_started / mode / prd
    worker_done_sum = 0
    for e in events:
        t = e.get("type", "")
        if t == "review_started":
            info["ts_start"] = e.get("ts", "")
            info["prd_files"] = e.get("prd_files", []) or [e.get("prd_name", "")] or []
            info["mode"] = e.get("mode", "")
        elif t == "worker_done":
            worker_done_sum += e.get("items_count", 0) or 0
        elif t == "checkpoint":
            # 老 checkpoint 的 items_count 是 merge 后 (N1 近似)
            if info["N1"] is None:
                info["N1"] = e.get("items_count")
        elif t == "review_completed":
            info["review_completed"] = True
            # review_completed 的 items_count 是最终 (含 goshawk, N3 近似)
            if info["N3"] is None and "items_count" in e:
                info["N3"] = e.get("items_count")

        # T3 native events
        elif t == "funnel_stage_worker_raw":
            info["N0"] = e.get("count")
            info["source_events"].append("T3_N0")
        elif t == "funnel_stage_after_dedup":
            info["N1"] = e.get("count")
            info["source_events"].append("T3_N1")
        elif t == "funnel_stage_after_evidence_verify":
            info["N2"] = e.get("count")
            info["retracted"] = e.get("retracted_count")
            info["downgraded"] = e.get("downgraded_count")
            info["wiki_mode"] = e.get("wiki_mode")
            info["authority_distribution"] = e.get("authority_distribution", {})
            info["source_events"].append("T3_N2")
        elif t == "funnel_stage_after_goshawk":
            info["N3"] = e.get("count")
            info["delta_breakdown"] = e.get("delta_breakdown")
            info["source_events"].append("T3_N3")
        elif t == "funnel_stage_after_pm_decision":
            info["N4"] = e.get("total_items")
            # 按 reason 分布只看 reject 的
            info["rejected_by_reason"] = e.get("rejected_by_reason", {})
            info["source_events"].append("T3_N4")
        elif t == "funnel_summary":
            info["suspicious_flags"] = e.get("suspicious_flags", [])
            info["source_events"].append("T3_summary")

    # 降级兜底: N0 从 worker_done 累加
    if info["N0"] is None and worker_done_sum > 0:
        info["N0"] = worker_done_sum

    return info


# ============================================================
# 聚合
# ============================================================

def _session_sort_key(path):
    """按 jsonl 文件修改时间 (mtime) 倒序 — 最新在前."""
    try:
        return -os.path.getmtime(path)
    except OSError:
        return 0


def collect_sessions(workspace_path, last_n=10):
    """从一个 workspace 的 output/sessions/ 收集最近 N 个 jsonl."""
    sessions_dir = os.path.join(workspace_path, "output", "sessions")
    if not os.path.isdir(sessions_dir):
        return []

    jsonls = sorted(
        glob.glob(os.path.join(sessions_dir, "rev_*.jsonl")),
        key=_session_sort_key,
    )[:last_n]
    return [extract_funnel_from_session(p) for p in jsonls]


def _retention(n_top, n_bottom):
    """N_top / N_bottom, 安全除法."""
    if n_top is None or n_bottom is None or n_bottom == 0:
        return None
    return round(n_top / n_bottom, 3)


def compute_trend(sessions):
    """最近 N 次跑的趋势: 每阶段 retention 的 min / mean / max."""
    if not sessions:
        return {}

    retentions: dict[str, list[float]] = defaultdict(list)
    for s in sessions:
        for name, top, bot in [
            ("dedup", s["N1"], s["N0"]),
            ("evidence_verify", s["N2"], s["N1"]),
            ("goshawk", s["N3"], s["N2"]),
            ("pm", s["N4"], s["N3"]),
        ]:
            r = _retention(top, bot)
            if r is not None:
                retentions[name].append(r)

    trend = {}
    for name, vals in retentions.items():
        if not vals:
            continue
        trend[name] = {
            "min": round(min(vals), 3),
            "max": round(max(vals), 3),
            "mean": round(sum(vals) / len(vals), 3),
            "samples": len(vals),
        }
    return trend


# ============================================================
# 输出 markdown
# ============================================================

def build_markdown(workspace_name, sessions, trend):
    lines = [
        f"# Pecker 评审漏斗 · {workspace_name} · 最近 {len(sessions)} 次",
        "",
        f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        "## 每次跑 stage count",
        "",
        "| session | PRD | mode | N0 raw | N1 dedup | N2 ev_verify | N3 goshawk | N4 PM | flags |",
        "|---|---|---|---:|---:|---:|---:|---:|---|",
    ]
    for s in sessions:
        session_short = s["session_id"][:20]
        prd = (s["prd_files"][0] if s["prd_files"] else "?")[:30]
        mode = s.get("mode", "-")
        flags = ",".join(s.get("suspicious_flags", [])) or "-"
        lines.append(
            f"| {session_short} | {prd} | {mode} "
            f"| {s['N0'] if s['N0'] is not None else '-'}"
            f" | {s['N1'] if s['N1'] is not None else '-'}"
            f" | {s['N2'] if s['N2'] is not None else '-'}"
            f" | {s['N3'] if s['N3'] is not None else '-'}"
            f" | {s['N4'] if s['N4'] is not None else '-'}"
            f" | {flags} |"
        )
    lines.append("")

    # 趋势
    if trend:
        lines.append("## 趋势 (最近 N 次)")
        lines.append("")
        lines.append("| stage | retention min | mean | max | 样本数 |")
        lines.append("|---|---:|---:|---:|---:|")
        for stage_name in ("dedup", "evidence_verify", "goshawk", "pm"):
            t = trend.get(stage_name)
            if t:
                lines.append(
                    f"| {stage_name} | {t['min']} | {t['mean']} | {t['max']} | {t['samples']} |"
                )
        lines.append("")

        # 自动观察
        observations = []
        if "dedup" in trend and trend["dedup"]["mean"] < 0.6:
            observations.append(
                f"- **dedup retention 均值 {trend['dedup']['mean']}** (<0.6), "
                f"建议排查 merge_reviews 是否吞 facet"
            )
        if "evidence_verify" in trend and trend["evidence_verify"]["mean"] < 0.6:
            observations.append(
                f"- **evidence_verify retention 均值 {trend['evidence_verify']['mean']}** (<0.6), "
                f"wiki sparse 未触发 / authority 全 generated 嫌疑"
            )
        if "goshawk" in trend and trend["goshawk"]["mean"] < 0.7:
            observations.append(
                f"- **goshawk retention 均值 {trend['goshawk']['mean']}** (<0.7), "
                f"苍鹰合并偏多, 看 merged_to_facet (P0-1 后应少)"
            )
        if "pm" in trend and trend["pm"]["mean"] < 0.3:
            observations.append(
                f"- **PM retention 均值 {trend['pm']['mean']}** (<0.3), "
                f"看 rejected_by_reason, 针对高占比 reason 修对应层"
            )
        if observations:
            lines.append("## 自动观察")
            lines.append("")
            lines.extend(observations)
            lines.append("")

    # 汇总 reject reason (如果有多次 pm decision)
    reject_totals: dict[str, int] = defaultdict(int)
    for s in sessions:
        for r, n in s.get("rejected_by_reason", {}).items():
            reject_totals[r] += n
    if reject_totals:
        lines.append("## 汇总 Reject 原因分布 (跨所有 session)")
        lines.append("")
        lines.append("| reason | count |")
        lines.append("|---|---:|")
        for r, n in sorted(reject_totals.items(), key=lambda kv: -kv[1]):
            lines.append(f"| {r} | {n} |")
        lines.append("")

    # 数据源标注
    lines.append("## 数据源")
    lines.append("")
    t3_count = sum(1 for s in sessions if any(ev.startswith("T3_") for ev in s.get("source_events", [])))
    legacy = len(sessions) - t3_count
    lines.append(f"- T3 原生 funnel_stage_* 事件: **{t3_count}** session")
    lines.append(f"- 降级从老字段 (worker_done/checkpoint/review_completed) 拼: **{legacy}** session "
                 f"(N2/N4 不可用)")
    return "\n".join(lines)


# ============================================================
# Main
# ============================================================

def _find_workspaces(root, specific=None):
    if specific:
        p = os.path.join(root, specific)
        return [p] if os.path.isdir(p) else []
    return sorted(
        p for p in glob.glob(os.path.join(root, "workspace-*"))
        if os.path.isdir(p)
    )


def main():
    parser = argparse.ArgumentParser(description="Pecker 评审漏斗聚合报告 (T3 消费者)")
    parser.add_argument("--workspace", help="指定 workspace")
    parser.add_argument("--last", type=int, default=10, help="每 workspace 最近 N 次 (默认 10)")
    parser.add_argument("--root", default=".")
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    parser.add_argument("--out-file", help="写 markdown 到文件")
    args = parser.parse_args()

    root = os.path.abspath(args.root)
    ws_paths = _find_workspaces(root, args.workspace)
    if not ws_paths:
        print(f"[funnel_report] 没找到 workspace in {root}")
        return 0

    all_reports = []
    json_payload = {}
    for ws in ws_paths:
        sessions = collect_sessions(ws, last_n=args.last)
        if not sessions:
            continue
        trend = compute_trend(sessions)
        if args.format == "markdown":
            all_reports.append(build_markdown(os.path.basename(ws), sessions, trend))
        else:
            json_payload[os.path.basename(ws)] = {
                "sessions": sessions,
                "trend": trend,
            }

    if args.format == "json":
        out_text = json.dumps(json_payload, ensure_ascii=False, indent=2, default=str)
    else:
        out_text = "\n\n---\n\n".join(all_reports) if all_reports else "(no sessions found)"

    if args.out_file:
        with open(args.out_file, "w", encoding="utf-8") as f:
            f.write(out_text)
        print(f"[funnel_report] 报告写入 {args.out_file}")
    else:
        print(out_text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
