"""T5 Real PRD Calibration runner — 对比 pecker 输出 vs ground truth (2026-04-24).

spec: docs/sprint-real-prd-calibration-evidence-governance.md 主线 A

计算:
  - precision / recall (按 rule_id + location + issue 文本相似度匹配)
  - TP / FP / FN 分类明细
  - 按 severity / dimension / reject_reason 切分布
  - 多轮 overlap (若 --outputs 指定多个 review_items_*.json)
  - accept+edit rate (从 ground truth 的 action 字段算)

用法:
  # 单轮对比 (最常用)
  python scripts/calibration_runner.py \
      --ground-truth eval/ground_truth/infringement_software_template_albedolyu_1777011594.json \
      --output workspace-侵权软件/output/review_items_20260424_default.json

  # 多轮 overlap
  python scripts/calibration_runner.py \
      --ground-truth eval/ground_truth/xxx.json \
      --outputs run1.json run2.json run3.json

本 script 不跑 pecker (省钱 + 省时), 读 已有的 review_items JSON 和 ground truth 对账.
要跑多轮新 pecker, 先手动跑 `run_session.py --non-interactive` N 次, 再把 output 传给本 script.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from eval.consistency_eval import calculate_overlap, items_similar, normalize_item


def _load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _extract_items(data):
    """支持两种 JSON 结构: {items: [...]} (pecker 输出) 或者 [...] 裸数组."""
    if isinstance(data, list):
        return data
    return data.get("items", [])


def _match_pecker_to_gt(pecker_items, gt_items):
    """对每条 pecker item 找 GT 中最佳匹配, 返回 [(pecker_item, gt_item or None), ...].

    GT 使用 "is_true_positive" 字段标真/假阳性:
      - GT item is_true_positive=True + matched → TP (pecker 找对了 + 手工也认)
      - GT item is_true_positive=False + matched → FP (pecker 找了但手工认为误报)
      - 未匹配 → FP (pecker 找了但 GT 没这条)
    """
    gt_normalized = [normalize_item(gi) for gi in gt_items]
    pairs = []
    matched_gt_indexes = set()
    for pi in pecker_items:
        p_norm = normalize_item(pi)
        best = None
        for gi_idx, g_norm in enumerate(gt_normalized):
            if gi_idx in matched_gt_indexes:
                continue
            if items_similar(p_norm, g_norm):
                best = gi_idx
                break
        if best is not None:
            matched_gt_indexes.add(best)
            pairs.append((pi, gt_items[best]))
        else:
            pairs.append((pi, None))
    return pairs, matched_gt_indexes


def classify(pairs, gt_items, matched_gt_indexes):
    """把 pairs + 未匹配的 GT 分到 TP / FP / FN."""
    tp, fp, fn = [], [], []
    for pi, gi in pairs:
        if gi is None:
            fp.append({"pecker": pi, "reason": "no match in GT"})
        elif gi.get("is_true_positive", True):
            tp.append({"pecker": pi, "gt": gi})
        else:
            fp.append({"pecker": pi, "gt": gi, "reason": "GT 标注为误报"})

    for gi_idx, gi in enumerate(gt_items):
        if gi_idx in matched_gt_indexes:
            continue
        # 只算 is_true_positive=True 的 GT item 为 FN (pecker 漏了真问题)
        # GT is_true_positive=False 不该被 pecker 找到, 未匹配反而是对的, 跳过
        if gi.get("is_true_positive", True):
            fn.append({"gt": gi, "reason": "pecker 没发现"})
    return tp, fp, fn


def compute_metrics(tp, fp, fn):
    tp_n = len(tp)
    fp_n = len(fp)
    fn_n = len(fn)
    precision = tp_n / (tp_n + fp_n) if (tp_n + fp_n) > 0 else 0.0
    recall = tp_n / (tp_n + fn_n) if (tp_n + fn_n) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
    return {
        "tp": tp_n, "fp": fp_n, "fn": fn_n,
        "precision": round(precision, 3),
        "recall": round(recall, 3),
        "f1": round(f1, 3),
    }


def compute_action_distribution(gt_items):
    """从 GT item.action 字段算 accept / edit / reject 分布 + reject 原因."""
    actions: Counter[str] = Counter()
    reject_reasons: Counter[str] = Counter()
    for gi in gt_items:
        a = gi.get("action", "")
        if a:
            actions[a] += 1
        if a == "reject":
            reject_reasons[gi.get("reason_category", "uncategorized")] += 1
    total = sum(actions.values())
    ae_rate = (actions.get("accept", 0) + actions.get("edit", 0)) / total if total > 0 else 0.0
    reject_rate = actions.get("reject", 0) / total if total > 0 else 0.0
    return {
        "actions": dict(actions),
        "reject_reasons": dict(reject_reasons),
        "accept_edit_rate": round(ae_rate, 3),
        "reject_rate": round(reject_rate, 3),
    }


def compute_severity_dimension_slice(tp, fp, fn):
    """按 severity / dimension 切 TP/FP/FN. 保证 3 个 bucket key (tp/fp/fn) 恒存在."""
    severity_slice: dict[str, Counter[str]] = {"tp": Counter(), "fp": Counter(), "fn": Counter()}
    dimension_slice: dict[str, Counter[str]] = {"tp": Counter(), "fp": Counter(), "fn": Counter()}

    for bucket_name, items in [("tp", tp), ("fp", fp), ("fn", fn)]:
        for entry in items:
            it = entry.get("pecker") or entry.get("gt", {})
            severity_slice[bucket_name][it.get("severity", "unknown")] += 1
            dimension_slice[bucket_name][it.get("dimension", "unknown")] += 1

    return {
        "by_severity": {k: dict(v) for k, v in severity_slice.items()},
        "by_dimension": {k: dict(v) for k, v in dimension_slice.items()},
    }


def build_report(gt_data, outputs, metrics, action_dist, slices, overlap):
    lines = [
        "# Pecker Calibration Report",
        "",
        f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"**Ground truth**: `{gt_data.get('prd', gt_data.get('workspace', 'unknown'))}` "
        f"({len(gt_data.get('items', []))} 条)",
        f"**Pecker outputs**: {len(outputs)} 个文件",
        "",
        "## 核心指标",
        "",
        "| 指标 | 值 |",
        "|---|---:|",
        f"| Precision | {metrics['precision']} |",
        f"| Recall | {metrics['recall']} |",
        f"| F1 | {metrics['f1']} |",
        f"| TP | {metrics['tp']} |",
        f"| FP | {metrics['fp']} |",
        f"| FN | {metrics['fn']} |",
        f"| accept+edit rate (GT 侧) | {action_dist['accept_edit_rate']} |",
        f"| reject rate (GT 侧) | {action_dist['reject_rate']} |",
        "",
    ]

    # 成功标准检查 (sprint 第二节主线 A)
    lines.append("## 成功标准 (sprint 主线 A)")
    lines.append("")
    checks = [
        ("accept+edit >= 30%", action_dist["accept_edit_rate"] >= 0.30),
        ("reject <= 40%", action_dist["reject_rate"] <= 0.40),
        ("有价值项 >= 2-5 条 (TP >= 2)", metrics["tp"] >= 2),
    ]
    for name, passed in checks:
        icon = "✓" if passed else "✗"
        lines.append(f"- {icon} {name}")
    lines.append("")

    # Action distribution
    lines.append("## PM 决策分布 (来自 GT)")
    lines.append("")
    lines.append("| action | count |")
    lines.append("|---|---:|")
    for a, n in sorted(action_dist["actions"].items()):
        lines.append(f"| {a} | {n} |")
    lines.append("")

    # Reject reasons (T2 新增)
    if action_dist["reject_reasons"]:
        lines.append("## Reject 原因分布 (T2 reason_category)")
        lines.append("")
        lines.append("| reason_category | count | 下游动作 |")
        lines.append("|---|---:|---|")
        action_map = {
            "false_positive": "规则降级 / rule slimming",
            "rule_too_strict": "规则改写 + scope 收窄",
            "wiki_missing": "补 canonical wiki 页",
            "impl_detail": "规则 scope 限 PRD 级",
            "model_noise": "worker prompt 迭代",
            "known_tradeoff": "加 workspace ignore",
            "good_issue": "(无动作, PM 手滑)",
            "uncategorized": "(GT 没打 reason_category)",
        }
        for r, n in sorted(action_dist["reject_reasons"].items(), key=lambda kv: -kv[1]):
            lines.append(f"| {r} | {n} | {action_map.get(r, '?')} |")
        lines.append("")

    # Severity × bucket
    lines.append("## 按 severity 切 TP/FP/FN")
    lines.append("")
    sevs = sorted({s for bucket in slices["by_severity"].values() for s in bucket})
    lines.append("| severity | TP | FP | FN |")
    lines.append("|---|---:|---:|---:|")
    for sev in sevs:
        tp_n = slices["by_severity"]["tp"].get(sev, 0)
        fp_n = slices["by_severity"]["fp"].get(sev, 0)
        fn_n = slices["by_severity"]["fn"].get(sev, 0)
        lines.append(f"| {sev} | {tp_n} | {fp_n} | {fn_n} |")
    lines.append("")

    # Multi-run overlap (如果 >= 2 output)
    if overlap:
        lines.append("## 多轮 overlap (稳定性)")
        lines.append("")
        lines.append(f"**稳定项** (>=67% 轮次出现): {overlap.get('stable_count', 0)} 条")
        lines.append("")
        lines.append("| run_a | run_b | overlap |")
        lines.append("|---|---|---:|")
        for p in overlap.get("pairwise", []):
            lines.append(f"| {p['run_a']} | {p['run_b']} | {p['overlap']:.1%} |")
        lines.append("")

    lines.append("## 下一步")
    lines.append("")
    if metrics["recall"] < 0.5:
        lines.append("- **recall 偏低** (<50%), 看 FN 列表, 可能 worker sampling noise 漏问题 (sprint P0-2)")
    if metrics["precision"] < 0.6:
        lines.append("- **precision 偏低** (<60%), 看 FP 列表 + reject_reasons 分布, 针对高占比 reason 修对应层")
    if action_dist["reject_reasons"].get("wiki_missing", 0) >= 2:
        lines.append("- **wiki_missing 驳回 ≥ 2**, 补 canonical wiki (T4 migrate)")
    if action_dist["reject_reasons"].get("rule_too_strict", 0) >= 2:
        lines.append("- **rule_too_strict 驳回 ≥ 2**, 检查 review-dimensions.yaml rule, 考虑降级 experimental")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Pecker calibration runner (offline, 不跑 pecker)")
    parser.add_argument("--ground-truth", required=True, help="ground truth JSON 路径")
    parser.add_argument("--output", help="单个 review_items_*.json (单轮模式)")
    parser.add_argument("--outputs", nargs="+", help="多个 review_items_*.json (多轮 overlap)")
    parser.add_argument("--out-file", help="写 markdown 报告到文件 (默认 stdout)")
    args = parser.parse_args()

    if not args.output and not args.outputs:
        print("ERROR: 至少指定 --output 或 --outputs 之一")
        return 1

    gt_data = _load_json(args.ground_truth)
    gt_items = _extract_items(gt_data)

    output_paths = [args.output] if args.output else list(args.outputs)
    outputs = [_load_json(p) for p in output_paths]

    # 第一份 output 做 TP/FP/FN 指标 (经典对账)
    pecker_items = _extract_items(outputs[0])
    pairs, matched_idx = _match_pecker_to_gt(pecker_items, gt_items)
    tp, fp, fn = classify(pairs, gt_items, matched_idx)
    metrics = compute_metrics(tp, fp, fn)
    action_dist = compute_action_distribution(gt_items)
    slices = compute_severity_dimension_slice(tp, fp, fn)

    # 若 >= 2 份 output, 跑 overlap
    overlap = None
    if len(outputs) >= 2:
        runs_items = [_extract_items(o) for o in outputs]
        pairwise, stable, _freq = calculate_overlap(runs_items)
        overlap = {
            "pairwise": pairwise,
            "stable_count": len(stable),
        }

    report = build_report(gt_data, output_paths, metrics, action_dist, slices, overlap)
    if args.out_file:
        with open(args.out_file, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"[calibration] 报告写入 {args.out_file}")
    else:
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except (AttributeError, OSError):
            pass
        try:
            print(report)
        except UnicodeEncodeError:
            print(report.encode("ascii", errors="replace").decode("ascii"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
