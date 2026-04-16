"""一致性评测分析器

离线读取 eval/results/ 下的多次评审结果 JSON,统计每条 rule_id 的检出频率,
输出一致性报告。

用法:
  python -m eval.consistency_analyzer --results-dir eval/results/ --test-case 劳动仲裁
  python -m eval.consistency_analyzer --results-dir eval/results/  # 分析全部结果

输出:
- 每条规则的发现频率 (N/M 次检出)
- 稳定规则 (>=75%) vs 不稳定规则 (<50%)
- 总体一致性分
"""

import argparse
import json
import os
import sys
from collections import defaultdict
from typing import Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def load_results(results_dir: str, test_case_filter: Optional[str] = None) -> List[dict]:
    """从 results_dir 加载所有 *_raw.json 结果文件"""
    results = []
    if not os.path.isdir(results_dir):
        print(f"[错误] 结果目录不存在: {results_dir}")
        return results

    for fname in sorted(os.listdir(results_dir)):
        if not fname.endswith("_raw.json"):
            continue
        if test_case_filter and test_case_filter not in fname:
            continue
        fpath = os.path.join(results_dir, fname)
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                data = json.load(f)
            results.append(data)
        except (json.JSONDecodeError, OSError) as e:
            print(f"[警告] 跳过无效文件 {fname}: {e}")
    return results


def analyze_rule_frequency(results: List[dict]) -> Dict[str, dict]:
    """统计每条 rule_id 在多次评审中的检出频率

    Returns:
        {rule_id: {count: N, total_runs: M, frequency: N/M, severity_dist: {...}, locations: [...]}}
    """
    # 每个 result 文件里 all_items 是多轮结果列表,每轮是一个 items list
    all_runs_items = []  # 展平为单轮列表
    for result in results:
        runs = result.get("all_items", [])
        for run_items in runs:
            if isinstance(run_items, list):
                all_runs_items.append(run_items)

    total_runs = len(all_runs_items)
    if total_runs == 0:
        return {}

    # 统计每条 rule_id 出现在多少个 run 中
    rule_stats = defaultdict(lambda: {
        "count": 0,
        "total_runs": total_runs,
        "frequency": 0.0,
        "severity_dist": defaultdict(int),
        "locations": set(),
        "dimensions": set(),
    })

    for run_items in all_runs_items:
        # 一个 run 内同一 rule_id 只算一次
        seen_in_run = set()
        for item in run_items:
            if not isinstance(item, dict):
                continue
            rid = (item.get("rule_id") or "").strip()
            if not rid:
                continue

            stats = rule_stats[rid]
            severity = item.get("severity", "unknown")
            stats["severity_dist"][severity] += 1
            loc = (item.get("location") or "").strip()
            if loc:
                stats["locations"].add(loc)
            dim = (item.get("dimension") or "").strip()
            if dim:
                stats["dimensions"].add(dim)

            if rid not in seen_in_run:
                stats["count"] += 1
                seen_in_run.add(rid)

    # 计算频率
    for rid, stats in rule_stats.items():
        stats["frequency"] = round(stats["count"] / total_runs, 3)
        stats["locations"] = sorted(stats["locations"])
        stats["dimensions"] = sorted(stats["dimensions"])
        stats["severity_dist"] = dict(stats["severity_dist"])

    return dict(rule_stats)


def classify_rules(rule_stats: Dict[str, dict]):
    """把规则分为稳定 / 不稳定 / 中间态"""
    stable = []     # >= 75%
    unstable = []   # < 50%
    moderate = []   # 50%-75%

    for rid, stats in sorted(rule_stats.items(), key=lambda x: -x[1]["frequency"]):
        freq = stats["frequency"]
        entry = {
            "rule_id": rid,
            "frequency": freq,
            "count": stats["count"],
            "total_runs": stats["total_runs"],
            "severity_dist": stats["severity_dist"],
            "locations": stats["locations"][:5],  # 只取前 5 个位置
            "dimensions": stats["dimensions"],
        }
        if freq >= 0.75:
            stable.append(entry)
        elif freq < 0.50:
            unstable.append(entry)
        else:
            moderate.append(entry)

    return stable, moderate, unstable


def compute_consistency_score(rule_stats: Dict[str, dict]) -> float:
    """计算总体一致性分: 所有规则的平均检出频率"""
    if not rule_stats:
        return 0.0
    freqs = [s["frequency"] for s in rule_stats.values()]
    return round(sum(freqs) / len(freqs), 3)


def print_report(
    stable: list,
    moderate: list,
    unstable: list,
    consistency_score: float,
    total_runs: int,
    test_case_filter: Optional[str],
):
    """输出一致性分析报告到 stdout"""
    print("=" * 60)
    print("  啄木鸟一致性评测分析报告")
    print("=" * 60)
    if test_case_filter:
        print(f"  筛选条件: {test_case_filter}")
    print(f"  分析运行总数: {total_runs}")
    print(f"  总体一致性分: {consistency_score:.1%}")
    print()

    # 评级
    if consistency_score >= 0.8:
        grade = "A (高一致性)"
    elif consistency_score >= 0.6:
        grade = "B (中等一致性)"
    elif consistency_score >= 0.4:
        grade = "C (较低一致性)"
    else:
        grade = "D (低一致性,需改进规则)"
    print(f"  评级: {grade}")
    print()

    # 稳定规则
    print(f"--- 稳定规则 (>=75% 检出率): {len(stable)} 条 ---")
    for r in stable:
        sev = "/".join(f"{k}:{v}" for k, v in r["severity_dist"].items())
        print(f"  {r['rule_id']:10s}  {r['frequency']:5.0%}  ({r['count']}/{r['total_runs']})  severity=[{sev}]")
    print()

    # 中间态
    print(f"--- 中间态规则 (50%-75%): {len(moderate)} 条 ---")
    for r in moderate:
        sev = "/".join(f"{k}:{v}" for k, v in r["severity_dist"].items())
        print(f"  {r['rule_id']:10s}  {r['frequency']:5.0%}  ({r['count']}/{r['total_runs']})  severity=[{sev}]")
    print()

    # 不稳定规则
    print(f"--- 不稳定规则 (<50% 检出率): {len(unstable)} 条 ---")
    for r in unstable:
        sev = "/".join(f"{k}:{v}" for k, v in r["severity_dist"].items())
        print(f"  {r['rule_id']:10s}  {r['frequency']:5.0%}  ({r['count']}/{r['total_runs']})  severity=[{sev}]")
    print()
    print("=" * 60)


def save_report_json(
    stable: list,
    moderate: list,
    unstable: list,
    consistency_score: float,
    total_runs: int,
    output_path: str,
):
    """保存结构化报告到 JSON"""
    report = {
        "consistency_score": consistency_score,
        "total_runs": total_runs,
        "grade": (
            "A" if consistency_score >= 0.8 else
            "B" if consistency_score >= 0.6 else
            "C" if consistency_score >= 0.4 else "D"
        ),
        "stable_rules": stable,
        "moderate_rules": moderate,
        "unstable_rules": unstable,
    }
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"  报告已保存: {output_path}")


def main():
    parser = argparse.ArgumentParser(description="一致性评测分析器: 统计规则检出频率")
    parser.add_argument("--results-dir", default="eval/results/", help="评测结果目录 (默认 eval/results/)")
    parser.add_argument("--test-case", default=None, help="按测试用例名筛选 (如 '劳动仲裁')")
    parser.add_argument("--output", default=None, help="JSON 报告输出路径")
    args = parser.parse_args()

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    results_dir = os.path.join(base_dir, args.results_dir) if not os.path.isabs(args.results_dir) else args.results_dir

    results = load_results(results_dir, args.test_case)
    if not results:
        print(f"[提示] 未找到结果文件。请先运行一致性评测:")
        print(f"  python eval/consistency_eval.py <prd_file> --runs 3")
        sys.exit(1)

    print(f"[加载] 找到 {len(results)} 个结果文件")

    rule_stats = analyze_rule_frequency(results)
    if not rule_stats:
        print("[提示] 结果中无有效的 rule_id 数据")
        sys.exit(1)

    stable, moderate, unstable = classify_rules(rule_stats)
    total_runs = next(iter(rule_stats.values()))["total_runs"] if rule_stats else 0
    consistency_score = compute_consistency_score(rule_stats)

    print_report(stable, moderate, unstable, consistency_score, total_runs, args.test_case)

    if args.output:
        output_path = os.path.join(base_dir, args.output) if not os.path.isabs(args.output) else args.output
        save_report_json(stable, moderate, unstable, consistency_score, total_runs, output_path)


if __name__ == "__main__":
    main()
