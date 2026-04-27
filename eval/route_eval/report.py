"""md + json 报告生成器 -- 单 route / baseline matrix / admission 三种.

格式严格对齐 plan "评测体系" 第 6 节示例.
"""
from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, List, Optional


def _ensure_parent(path: str):
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)


def _ts() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


# ============================================================
# 1. 单 route 报告
# ============================================================

def write_route_report(
    metrics: Dict[str, Any],
    output_path_md: str,
    output_path_json: str,
) -> None:
    """单 route × 单 vendor × 单 model 报告 (5 维度全列).

    Args:
        metrics: dict 含
            {
                "route_id", "vendor", "model", "dataset", "runs", "dry_run",
                "capability": {p, r, f1, severity_kl, ...},
                "stability": {overlap, n0_var, sampling_cv, ...},
                "cost_latency": {p50_ms, p95_ms, p99_ms, cost_usd_per_run, ...},
                "failure_modes": {quota_rate, json_parse_fail_rate, ...},
                "cross_vendor": {kappa, complementary_recall, disagreement} (可选),
                "hallucination": {tpr, fpr} (verify.nli 才有, 可选),
                "failure_samples": [...] (可选),
            }
    """
    _ensure_parent(output_path_md)
    _ensure_parent(output_path_json)

    route_id = metrics.get("route_id", "unknown")
    vendor = metrics.get("vendor", "unknown")
    model = metrics.get("model", "unknown")
    runs = metrics.get("runs", 0)
    dataset = metrics.get("dataset", "unknown")
    dry_run = metrics.get("dry_run", False)

    cap = metrics.get("capability", {}) or {}
    stab = metrics.get("stability", {}) or {}
    cost = metrics.get("cost_latency", {}) or {}
    fm = metrics.get("failure_modes", {}) or {}
    cv = metrics.get("cross_vendor", {}) or {}
    hal = metrics.get("hallucination", {}) or {}

    lines = [
        f"# Route Eval: {route_id} @ {vendor}:{model}",
        "",
        f"- 数据集: `{dataset}`",
        f"- 评测轮次: {runs}",
        f"- 评测时间: {_ts()}",
        f"- dry_run: {dry_run}",
        "",
        "## 5 维度指标",
        "",
        "### 1) 能力 (Capability)",
        "",
        "| 指标 | 值 |",
        "|---|---|",
        f"| Precision | {cap.get('p', 0):.4f} |",
        f"| Recall | {cap.get('r', 0):.4f} |",
        f"| F1 | {cap.get('f1', 0):.4f} |",
        f"| Severity KL | {cap.get('severity_kl', 0):.4f} |",
        f"| 命中 / 漏报 / 误报 | {cap.get('hits', 0)} / {cap.get('misses', 0)} / {cap.get('fps', 0)} |",
        f"| 总改进项 | {cap.get('total_items', 0)} |",
        "",
        "### 2) 稳定性 (Stability)",
        "",
        "| 指标 | 值 |",
        "|---|---|",
        f"| Overlap (pairwise avg) | {stab.get('overlap', 0):.4f} |",
        f"| N0 方差 | {stab.get('n0_var', 0):.4f} |",
        f"| Sampling CV | {stab.get('sampling_cv', 0):.4f} |",
        f"| 稳定项数 | {stab.get('stable_count', 0)} |",
        f"| 实际跑了 N 轮 | {stab.get('n_runs', 0)} |",
        "",
        "### 3) 成本 / 延迟 (Cost / Latency)",
        "",
        "| 指标 | 值 |",
        "|---|---|",
        f"| p50 latency (ms) | {cost.get('p50_ms', 0):.1f} |",
        f"| p95 latency (ms) | {cost.get('p95_ms', 0):.1f} |",
        f"| p99 latency (ms) | {cost.get('p99_ms', 0):.1f} |",
        f"| 单次成本 (USD) | {cost.get('cost_usd_per_run', 0):.6f} |",
        f"| 总成本 (USD) | {cost.get('cost_usd_total', 0):.6f} |",
        f"| 总 input/output tokens | {cost.get('total_input_tokens', 0)} / {cost.get('total_output_tokens', 0)} |",
        f"| 调用次数 | {cost.get('n_calls', 0)} |",
        "",
        "### 4) 失败模式 (Failure Modes)",
        "",
        "| 指标 | 比率 |",
        "|---|---|",
        f"| 配额耗尽 (quota) | {fm.get('quota_rate', 0):.4f} |",
        f"| JSON parse 失败 | {fm.get('json_parse_fail_rate', 0):.4f} |",
        f"| Tool use 失败 | {fm.get('tool_use_fail_rate', 0):.4f} |",
        f"| Fallback 触发 | {fm.get('fallback_rate', 0):.4f} |",
        f"| Timeout | {fm.get('timeout_rate', 0):.4f} |",
        "",
    ]

    if cv:
        lines += [
            "### 5) 跨 vendor 偏差 (Cross-Vendor Bias)",
            "",
            "| 指标 | 值 |",
            "|---|---|",
            f"| Cohen's κ | {cv.get('kappa', 0):.4f} |",
            f"| 分歧率 | {cv.get('disagreement', 0):.4f} |",
        ]
        cr = cv.get("complementary_recall", {}) or {}
        if cr:
            lines += [
                f"| 联合召回 | {cr.get('joint_recall', 0):.4f} |",
                f"| 互补率 (complementary_pct) | {cr.get('complementary_pct', 0):.4f} |",
            ]
        lines.append("")

    if hal:
        lines += [
            "### Hallucination (verify.nli only)",
            "",
            "| 指标 | 值 |",
            "|---|---|",
            f"| 拦截率 (TPR) | {hal.get('tpr', 0):.4f} |",
            f"| 误杀率 (FPR) | {hal.get('fpr', 0):.4f} |",
            "",
        ]

    failure_samples = metrics.get("failure_samples") or []
    if failure_samples:
        lines += ["## 失败样本（前 5）", ""]
        for s in failure_samples[:5]:
            lines.append(f"- {s}")
        lines.append("")

    with open(output_path_md, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    with open(output_path_json, "w", encoding="utf-8") as f:
        json.dump(metrics, f, ensure_ascii=False, indent=2, default=str)


# ============================================================
# 2. Baseline matrix -- 全 route 一张表
# ============================================================

def write_baseline_matrix(
    all_route_metrics: List[Dict[str, Any]],
    output_path: str,
) -> None:
    """生成 baseline matrix md + 同名 .json 备份.

    Args:
        all_route_metrics: List of (单 route 报告 schema), 每条覆盖一个 route
    """
    _ensure_parent(output_path)

    lines = [
        f"# Baseline Matrix",
        "",
        f"- 生成时间: {_ts()}",
        f"- 路由数: {len(all_route_metrics)}",
        "",
        "## 5 维度全表",
        "",
        "| route_id | vendor | model | F1 | Recall | Overlap | p95 ms | $/run | quota% | parse fail% |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for m in all_route_metrics:
        rid = m.get("route_id", "?")
        v = m.get("vendor", "?")
        mdl = m.get("model", "?")
        cap = m.get("capability", {}) or {}
        stab = m.get("stability", {}) or {}
        cost = m.get("cost_latency", {}) or {}
        fm = m.get("failure_modes", {}) or {}
        lines.append(
            f"| {rid} | {v} | {mdl} | "
            f"{cap.get('f1', 0):.3f} | {cap.get('r', 0):.3f} | "
            f"{stab.get('overlap', 0):.3f} | "
            f"{cost.get('p95_ms', 0):.0f} | "
            f"{cost.get('cost_usd_per_run', 0):.6f} | "
            f"{fm.get('quota_rate', 0):.3f} | "
            f"{fm.get('json_parse_fail_rate', 0):.3f} |"
        )
    lines.append("")

    # 备注
    lines += [
        "## 说明",
        "",
        "- 此表作为后续准入对比的参照基线 (scripts/eval_admission.py --compare)",
        "- 阈值: F1>=baseline-0.05, Recall>=baseline-0.05, Overlap>=baseline-0.05,",
        "  p95<=baseline*1.5, $/run<=baseline*2.0",
        "",
    ]

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    json_path = output_path.rsplit(".", 1)[0] + ".json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(
            {"generated_at": _ts(), "routes": all_route_metrics},
            f, ensure_ascii=False, indent=2, default=str,
        )


# ============================================================
# 3. Admission 对比报告
# ============================================================

def write_admission_report(
    admission_result: Dict[str, Any],
    candidate_metrics: Dict[str, Any],
    baseline_metrics: Dict[str, Any],
    output_path: str,
) -> None:
    """对单 route 候选 vs baseline 出准入对比报告.

    Args:
        admission_result: admission.admit() 输出
        candidate_metrics, baseline_metrics: 单 route 报告 schema
    """
    _ensure_parent(output_path)

    rid = admission_result.get("route_id", "unknown")
    pass_flag = admission_result.get("pass", False)
    deltas = admission_result.get("deltas", {}) or {}
    fails = admission_result.get("fail_reasons", []) or []
    checks = admission_result.get("checks", {}) or {}

    cand_v = candidate_metrics.get("vendor", "?")
    cand_m = candidate_metrics.get("model", "?")
    base_v = baseline_metrics.get("vendor", "?")
    base_m = baseline_metrics.get("model", "?")

    verdict = "PASS" if pass_flag else "FAIL"

    lines = [
        f"# Admission Report: {rid}",
        "",
        f"- 候选: `{cand_v}:{cand_m}`",
        f"- 基线: `{base_v}:{base_m}`",
        f"- 评测时间: {_ts()}",
        f"- **判定: {verdict}**",
        "",
        "## 5 维度 vs baseline",
        "",
        "| 维度 | 候选 | baseline | delta | PASS/FAIL |",
        "|---|---|---|---|---|",
    ]

    for name in ["f1_delta", "recall_delta", "overlap_delta",
                 "p95_latency_ratio", "cost_ratio",
                 "hallucination_tpr", "hallucination_fpr"]:
        if name not in checks:
            continue
        c = checks[name]
        cand_val = c.get("candidate", "-")
        base_val = c.get("baseline", "-")
        val = c.get("value", "-")
        pf = "PASS" if c.get("passed") else "FAIL"
        lines.append(f"| {name} | {cand_val} | {base_val} | {val} | {pf} |")

    lines.append("")

    if fails:
        lines += ["## 失败原因", ""]
        for r in fails:
            lines.append(f"- {r}")
        lines.append("")

    # 决策建议 (简单启发, plan 第 6 节示例那种)
    lines += ["## 决策建议", ""]
    if pass_flag:
        lines.append(f"- 准入通过, 候选 `{cand_v}:{cand_m}` 可合并 `model_routes.yaml` 主线作为 `{rid}`.")
    else:
        cost_ratio = deltas.get("cost_ratio", 0)
        comp_pct = (candidate_metrics.get("cross_vendor", {}) or {}).get(
            "complementary_recall", {}).get("complementary_pct", 0)
        if cost_ratio > 1.5 and comp_pct > 0.15:
            lines.append(
                f"- 不建议主路启用; 可考虑挂 `{rid}.shadow` 跑双苍鹰 (互补率 {comp_pct:.2%} > 15%, "
                f"成本 ×{cost_ratio} 成本不划算做主路)"
            )
        else:
            lines.append("- 不准入. 修复后重跑 `scripts/eval_admission.py`.")

    lines.append("")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
