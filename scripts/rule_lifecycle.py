"""Week 2 — 规则生命周期周度 slim 报告 (2026-04-24).

spec: docs/sprint-real-prd-calibration-evidence-governance.md 主线 C

读所有 workspace-*/output/rule_performance_history.json, 结合 T2 的
reject_by_reason 数据, 产"本周 rule slimming 建议"报告. **不自动改 yaml**,
仅输出建议 (PM review 后手工改 review-dimensions.yaml).

Slim 决策矩阵:
  total=total_decisions, precision=(confirmed)/(total), reject_rate
  - total < 3 → 数据不足, keep + 标待积累
  - precision >= 0.7 → active, keep (健康)
  - precision < 0.5 + reject_rate > 0.5 + 主导 reason:
    * false_positive / rule_too_strict → 建议降级到 experimental
    * wiki_missing                      → 不降级, flag 知识库补 canonical
    * impl_detail                        → 建议规则 scope 收窄到 PRD 级
    * model_noise                        → worker prompt 迭代候选
  - precision 0.5-0.7 → keep but monitor
  - impact_score < 0.3 + total >= 10  → deprecate 候选

用法:
  python scripts/rule_lifecycle.py                          # 全 workspace
  python scripts/rule_lifecycle.py --workspace workspace-对外投资
  python scripts/rule_lifecycle.py --out-file docs/rule-slim-2026-WW17.md
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from collections import Counter
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _load_rule_perf(workspace_path):
    """读一个 workspace 的 rule_performance_history.json, 跳过 __meta__."""
    path = os.path.join(workspace_path, "output", "rule_performance_history.json")
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    # 过滤 __meta__
    return {k: v for k, v in data.items() if k != "__meta__" and isinstance(v, dict)}


def _dominant_reject_reason(stats):
    """从 stats.reject_by_reason (T2) 算主导 reason, 无数据返回 None."""
    rbr = stats.get("reject_by_reason", {})
    if not rbr:
        return None
    top_reason, top_count = max(rbr.items(), key=lambda kv: kv[1])
    total_rejects = sum(rbr.values())
    ratio = top_count / total_rejects if total_rejects else 0.0
    return {"reason": top_reason, "count": top_count, "ratio": round(ratio, 3)}


def _classify_rule(rule_id, entry):
    """按决策矩阵给出 (status_suggestion, action, reason)."""
    stats = entry.get("stats", {}) or {}
    total = stats.get("total", 0) or 0
    confirmed = stats.get("confirmed", 0) or 0
    rejected = stats.get("rejected", 0) or 0
    impact_score = entry.get("impact_score", 0.5)
    reject_rate = rejected / total if total else 0.0
    precision = confirmed / total if total else 0.0

    dominant = _dominant_reject_reason(stats)

    # 不足样本
    if total < 3:
        return {
            "status": "insufficient_data",
            "action": "keep + 累积更多决策",
            "reason": f"样本 total={total} < 3, 数据不足下结论",
            "total": total, "precision": round(precision, 3),
            "reject_rate": round(reject_rate, 3), "impact_score": round(impact_score, 3),
            "dominant": dominant,
        }

    # 健康
    if precision >= 0.7:
        return {
            "status": "healthy",
            "action": "keep active",
            "reason": f"precision {round(precision, 3)} >= 0.7",
            "total": total, "precision": round(precision, 3),
            "reject_rate": round(reject_rate, 3), "impact_score": round(impact_score, 3),
            "dominant": dominant,
        }

    # 低 impact 候选 deprecate
    if impact_score < 0.3 and total >= 10:
        return {
            "status": "deprecate_candidate",
            "action": "建议标 deprecated 或归档",
            "reason": f"impact_score {round(impact_score, 3)} < 0.3 且 total {total} >= 10, EMA 衰减长期低价值",
            "total": total, "precision": round(precision, 3),
            "reject_rate": round(reject_rate, 3), "impact_score": round(impact_score, 3),
            "dominant": dominant,
        }

    # 高驳回率 + 主导 reason 分流
    if precision < 0.5 and reject_rate > 0.5:
        if dominant:
            dr = dominant["reason"]
            if dr == "false_positive":
                return {
                    "status": "rule_problem_demote",
                    "action": "建议降级到 experimental + review 规则精度",
                    "reason": f"precision {round(precision, 3)}, 主导 reject={dr} ({dominant['ratio']}) — 规则误报多",
                    "total": total, "precision": round(precision, 3),
                    "reject_rate": round(reject_rate, 3), "impact_score": round(impact_score, 3),
                    "dominant": dominant,
                }
            if dr == "rule_too_strict":
                return {
                    "status": "rule_rewrite",
                    "action": "建议改写规则 + scope 收窄",
                    "reason": f"precision {round(precision, 3)}, 主导 reject={dr} ({dominant['ratio']}) — scope 问题",
                    "total": total, "precision": round(precision, 3),
                    "reject_rate": round(reject_rate, 3), "impact_score": round(impact_score, 3),
                    "dominant": dominant,
                }
            if dr == "wiki_missing":
                return {
                    "status": "wiki_gap",
                    "action": "不降规则 — 补 canonical wiki 页",
                    "reason": f"precision {round(precision, 3)}, 主导 reject={dr} ({dominant['ratio']}) — 知识库空洞不是规则问题",
                    "total": total, "precision": round(precision, 3),
                    "reject_rate": round(reject_rate, 3), "impact_score": round(impact_score, 3),
                    "dominant": dominant,
                }
            if dr == "impl_detail":
                return {
                    "status": "scope_narrow",
                    "action": "规则 scope 收窄到 PRD 级别",
                    "reason": f"precision {round(precision, 3)}, 主导 reject={dr} ({dominant['ratio']}) — 规则过度关注实现",
                    "total": total, "precision": round(precision, 3),
                    "reject_rate": round(reject_rate, 3), "impact_score": round(impact_score, 3),
                    "dominant": dominant,
                }
            if dr == "model_noise":
                return {
                    "status": "prompt_iteration",
                    "action": "worker prompt 迭代候选",
                    "reason": f"precision {round(precision, 3)}, 主导 reject={dr} ({dominant['ratio']}) — 模型问题不是规则",
                    "total": total, "precision": round(precision, 3),
                    "reject_rate": round(reject_rate, 3), "impact_score": round(impact_score, 3),
                    "dominant": dominant,
                }
        # 没 T2 reason 数据 → 降级保守建议
        return {
            "status": "noisy_needs_investigation",
            "action": "建议人工 review 近 7 天驳回样本定性",
            "reason": f"precision {round(precision, 3)} < 0.5 但无 T2 reason 数据区分 — 可能规则问题或 wiki 问题, 待查",
            "total": total, "precision": round(precision, 3),
            "reject_rate": round(reject_rate, 3), "impact_score": round(impact_score, 3),
            "dominant": None,
        }

    # 中等区间
    return {
        "status": "monitor",
        "action": "keep + 观察下周",
        "reason": f"precision {round(precision, 3)} 在 0.5-0.7 之间, 中等, 下周再看",
        "total": total, "precision": round(precision, 3),
        "reject_rate": round(reject_rate, 3), "impact_score": round(impact_score, 3),
        "dominant": dominant,
    }


def slim_workspace(ws_path):
    """对一个 workspace 做 slim 分析, 返回 [(rule_id, classification), ...] 按优先级排."""
    perf = _load_rule_perf(ws_path)
    if not perf:
        return []

    rules = [(rid, _classify_rule(rid, entry)) for rid, entry in perf.items()]

    # 排序优先级: 规则问题优先 > wiki gap > scope > monitor > healthy > insufficient
    priority = {
        "rule_problem_demote": 0,
        "rule_rewrite": 1,
        "deprecate_candidate": 2,
        "scope_narrow": 3,
        "wiki_gap": 4,
        "prompt_iteration": 5,
        "noisy_needs_investigation": 6,
        "monitor": 7,
        "healthy": 8,
        "insufficient_data": 9,
    }
    rules.sort(key=lambda kv: (priority.get(kv[1]["status"], 99), -kv[1]["total"]))
    return rules


# ============================================================
# Markdown report
# ============================================================

_STATUS_EMOJI = {
    "rule_problem_demote": "🔻",
    "rule_rewrite": "✏️",
    "deprecate_candidate": "🗑",
    "scope_narrow": "🎯",
    "wiki_gap": "📚",
    "prompt_iteration": "🎛",
    "noisy_needs_investigation": "🔍",
    "monitor": "👀",
    "healthy": "✓",
    "insufficient_data": "—",
}


def build_report(all_results, week_str):
    total_rules = sum(len(rs) for rs in all_results.values())
    lines = [
        f"# 规则生命周期周度 slim 报告 · {week_str}",
        "",
        f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"**覆盖**: {len(all_results)} 个 workspace, {total_rules} 条规则",
        "",
        "## 建议动作汇总 (跨 workspace)",
        "",
    ]

    # 按 status 汇总
    status_count: Counter[str] = Counter()
    for rules in all_results.values():
        for _rid, cl in rules:
            status_count[cl["status"]] += 1

    lines.append("| 状态 | 数量 | 动作 |")
    lines.append("|---|---:|---|")
    action_desc = {
        "rule_problem_demote": "建议降级 experimental + review 规则精度",
        "rule_rewrite": "建议改写规则 + scope 收窄",
        "deprecate_candidate": "建议标 deprecated 或归档",
        "scope_narrow": "规则 scope 收窄到 PRD 级",
        "wiki_gap": "补 canonical wiki, 不动规则",
        "prompt_iteration": "worker prompt 迭代候选",
        "noisy_needs_investigation": "人工 review 驳回样本",
        "monitor": "keep + 下周观察",
        "healthy": "keep active",
        "insufficient_data": "keep + 累积更多决策",
    }
    for status in sorted(status_count.keys(), key=lambda s: {
        "rule_problem_demote": 0, "rule_rewrite": 1, "deprecate_candidate": 2,
        "scope_narrow": 3, "wiki_gap": 4, "prompt_iteration": 5,
        "noisy_needs_investigation": 6, "monitor": 7, "healthy": 8,
        "insufficient_data": 9,
    }.get(s, 99)):
        emoji = _STATUS_EMOJI.get(status, "·")
        lines.append(f"| {emoji} {status} | {status_count[status]} | {action_desc.get(status, '?')} |")
    lines.append("")

    # 每 workspace 详情
    for ws, rules in sorted(all_results.items()):
        if not rules:
            continue
        lines.append(f"## {ws}")
        lines.append("")
        lines.append("| rule_id | status | total | precision | reject_rate | impact | 主导 reject reason | 建议 |")
        lines.append("|---|---|---:|---:|---:|---:|---|---|")
        for rid, cl in rules:
            emoji = _STATUS_EMOJI.get(cl["status"], "·")
            dom = cl.get("dominant")
            dom_str = f"{dom['reason']} ({dom['ratio']})" if dom else "-"
            lines.append(
                f"| `{rid}` | {emoji} {cl['status']} "
                f"| {cl['total']} | {cl['precision']} | {cl['reject_rate']} | {cl['impact_score']} "
                f"| {dom_str} | {cl['action']} |"
            )
        lines.append("")

        # 详细 reason per-rule
        problem_rules = [r for r in rules if r[1]["status"] not in ("healthy", "insufficient_data")]
        if problem_rules:
            lines.append(f"### {ws} · 待动作规则详情")
            lines.append("")
            for rid, cl in problem_rules:
                lines.append(f"- **`{rid}`** ({cl['status']}): {cl['reason']}")
            lines.append("")

    # 使用说明
    lines.append("## 使用说明")
    lines.append("")
    lines.append("1. PM review 本报告, 对 **rule_problem_demote** / **rule_rewrite** / **deprecate_candidate** 状态的规则手工改 `review-dimensions.yaml` 的 `status` 字段")
    lines.append("2. **wiki_gap** 状态不改规则, 改去补 `workspace-*/wiki/` 的 canonical 页 (用 `scripts/wiki_migrate_v2.py --apply` 落地 authority)")
    lines.append("3. **prompt_iteration** 状态收集到 worker prompt 迭代队列")
    lines.append("4. 本 script 只读不改 YAML, 历史见 git log")
    return "\n".join(lines)


# ============================================================
# Main
# ============================================================

def _iso_week(dt=None):
    dt = dt or datetime.now()
    year, week, _ = dt.isocalendar()
    return f"{year}-W{week:02d}"


def _find_workspaces(root, specific=None):
    if specific:
        p = os.path.join(root, specific)
        return [p] if os.path.isdir(p) else []
    return sorted(
        p for p in glob.glob(os.path.join(root, "workspace-*"))
        if os.path.isdir(p)
    )


def main():
    parser = argparse.ArgumentParser(description="规则生命周期 weekly slim 报告 (只读)")
    parser.add_argument("--workspace", help="指定 workspace")
    parser.add_argument("--root", default=".")
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    parser.add_argument("--out-file", help="写 markdown 到文件")
    args = parser.parse_args()

    root = os.path.abspath(args.root)
    ws_paths = _find_workspaces(root, args.workspace)
    if not ws_paths:
        print(f"[rule_lifecycle] 没找到 workspace in {root}")
        return 0

    all_results = {os.path.basename(ws): slim_workspace(ws) for ws in ws_paths}
    # 去掉没规则数据的 workspace
    all_results = {ws: rs for ws, rs in all_results.items() if rs}

    if not all_results:
        print("[rule_lifecycle] 没 workspace 有 rule_performance_history.json 数据 (需要跑过 Phase 3 confirm)")
        return 0

    if args.format == "json":
        out = {
            ws: [{"rule_id": rid, **cl} for rid, cl in rules]
            for ws, rules in all_results.items()
        }
        text = json.dumps(out, ensure_ascii=False, indent=2)
    else:
        text = build_report(all_results, _iso_week())

    if args.out_file:
        with open(args.out_file, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"[rule_lifecycle] 报告写入 {args.out_file}")
    else:
        # Windows cp936 不能打印 emoji → 强刷 UTF-8 stdout, 失败则 ASCII safe fallback
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except (AttributeError, OSError):
            pass
        try:
            print(text)
        except UnicodeEncodeError:
            # 兜底: 剥掉非 ASCII emoji
            safe = text.encode("ascii", errors="replace").decode("ascii")
            print(safe)
            print("[rule_lifecycle] 注: stdout 不支持 UTF-8, emoji 已剥掉. 用 --out-file 拿完整版")
    return 0


if __name__ == "__main__":
    sys.exit(main())
