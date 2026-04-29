#!/usr/bin/env python
"""啄木鸟 manual pre-PR check — 没 self-hosted runner 时的本地 P/R 报告生成器.

用途:
  PM 在提 PR 前本地跑一次 rule_regression, 生成 markdown 格式的报告,
  把报告内容**贴到 PR description**里作为 review 证据.

与 self-hosted CI 的差异:
  - CI: 自动跑, 强制 gate, 失败阻塞 merge
  - 本脚本: 本地手动, 输出报告给 PM 自检 + 贴 PR. 不替代 CI.

用法:
  python scripts/manual_pre_pr_check.py
  python scripts/manual_pre_pr_check.py --output pr_check_report.md
  python scripts/manual_pre_pr_check.py --skip-nli              # 加速(跳 NLI)
  python scripts/manual_pre_pr_check.py --tolerance 0.05        # 跌幅阈值
  python scripts/manual_pre_pr_check.py --rules-yaml CUSTOM.yaml

输出:
  - 默认控制台打印 markdown 报告
  - 加 --output 时写到指定文件
  - exit code: 0 = P/R 全在容忍内, 1 = 有规则跌出阈值 (PM 见到红字, 决定改 prompt 或 update-baseline)
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)


def _safe_print(text: str) -> None:
    """Win GBK 控制台兜底."""
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.encode("gbk", errors="replace").decode("gbk", errors="replace"))


def _git_changed_files() -> list[str]:
    """返回相对仓库根的改动文件列表 (vs upstream / vs HEAD)"""
    try:
        # 优先看 vs upstream
        result = subprocess.run(
            ["git", "diff", "--name-only", "@{u}..HEAD"],
            cwd=_ROOT, capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            return [l.strip() for l in result.stdout.splitlines() if l.strip()]
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    # fallback: vs HEAD (uncommitted 改动)
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "HEAD"],
            cwd=_ROOT, capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            return [l.strip() for l in result.stdout.splitlines() if l.strip()]
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return []


def _detect_trigger_files(changed: list[str]) -> list[str]:
    """从改动列表里筛出会触发 regression 的关键路径."""
    trigger_patterns = (
        "review/prompting.py",
        "review/worker.py",
        "review/learnings_store.py",
        "review/dimensions.py",
        "review-rules/",
        "workspace-sample/review-rules/",
        "review-dimensions.yaml",
        "model_router.py",
        "model_routes.yaml",
        "agent_config.py",
        "scripts/rule_regression.py",
    )
    return [f for f in changed if any(p in f for p in trigger_patterns)]


def _run_regression(rules_yaml: str, baseline: str, output: str,
                    tolerance: float, skip_nli: bool) -> tuple[int, dict]:
    """跑 rule_regression.py, 返回 (exit_code, parsed_results_dict)."""
    cmd = [
        sys.executable,
        os.path.join(_HERE, "rule_regression.py"),
        "--rules-yaml", rules_yaml,
        "--baseline", baseline,
        "--tolerance", str(tolerance),
        "--output", output,
    ]
    if skip_nli:
        cmd.append("--skip-nli")

    _safe_print(f"[manual-check] 跑 rule_regression: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=_ROOT)

    parsed = {}
    if os.path.isfile(output):
        try:
            with open(output, "r", encoding="utf-8") as f:
                parsed = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            _safe_print(f"[manual-check] WARN: 解析 {output} 失败: {e}")

    return result.returncode, parsed


def _render_markdown_report(results: dict, exit_code: int,
                            trigger_files: list[str],
                            tolerance: float, skip_nli: bool) -> str:
    """生成可贴 PR description 的 markdown."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    summary = results.get("summary", {}) if results else {}
    rules = results.get("rules", {}) if results else {}

    lines = []
    lines.append("## Manual Pre-PR Check — Rule Regression Report")
    lines.append("")
    lines.append(f"- **生成时间**: {now}")
    lines.append(f"- **本地命令**: `python scripts/manual_pre_pr_check.py`")
    lines.append(f"- **tolerance**: {tolerance}")
    lines.append(f"- **skip_nli**: {skip_nli}")
    lines.append("")

    # 触发文件
    lines.append("### 改动触发 regression 的文件")
    if trigger_files:
        for f in trigger_files:
            lines.append(f"- `{f}`")
    else:
        lines.append("(无, 改动未触及 prompt / worker / rules 关键路径)")
    lines.append("")

    # 总结
    if summary:
        lines.append("### Macro 指标")
        lines.append("")
        lines.append(f"- **Macro-P**: {summary.get('macro_precision', 'N/A')}")
        lines.append(f"- **Macro-R**: {summary.get('macro_recall', 'N/A')}")
        lines.append(f"- **规则数**: {summary.get('rule_count', 'N/A')}")
        lines.append("")

    # 判定
    lines.append("### 判定")
    lines.append("")
    if exit_code == 0:
        lines.append("✓ **PASS** — 所有规则 P/R 在容忍阈值内, 可安全 push.")
    else:
        lines.append("✗ **FAIL** — 至少一条规则 P/R 跌出 tolerance.")
        lines.append("")
        lines.append("**修复方向**:")
        lines.append("1. 检查 prompt/worker 改动是否合理 (是否引入回归)")
        lines.append("2. 跑 `python scripts/rule_regression.py` 复现, 看哪条 rule 跌了")
        lines.append("3. 如果是预期降幅, 跑 `python scripts/rule_regression.py --update-baseline` 后 commit 新 baseline")
    lines.append("")

    # 规则明细
    if rules:
        lines.append("### 规则明细")
        lines.append("")
        lines.append("| rule_id | dim | P | R | TP | FP | FN | TN |")
        lines.append("|---|---|---|---|---|---|---|---|")
        for rid, d in rules.items():
            lines.append(
                f"| {rid} | {d.get('dimension', '-')} | "
                f"{d.get('precision', '-')} | {d.get('recall', '-')} | "
                f"{d.get('TP', 0)} | {d.get('FP', 0)} | "
                f"{d.get('FN', 0)} | {d.get('TN', 0)} |"
            )
        lines.append("")

    lines.append("---")
    lines.append(f"_本报告由 `scripts/manual_pre_pr_check.py` 在本地生成 — 不替代 self-hosted CI gate, 仅供 PR review 参考._")
    lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="本地跑 P/R 测试 + 输出 markdown 报告供贴 PR description",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--rules-yaml",
        default=os.path.join("workspace-sample", "review-rules", "review-checklist.yaml"),
        help="规则 yaml 路径",
    )
    parser.add_argument(
        "--baseline",
        default=os.path.join("scripts", "fixtures", "regression_baseline.json"),
        help="baseline json 路径",
    )
    parser.add_argument(
        "--results",
        default=os.path.join("scripts", "fixtures", "regression_results.json"),
        help="results json 输出路径 (机器可读)",
    )
    parser.add_argument(
        "--output", "-o",
        help="markdown 报告输出路径 (省略则打印到 stdout)",
    )
    parser.add_argument(
        "--tolerance",
        type=float, default=0.05,
        help="P/R 下降容忍阈值 (默认 0.05)",
    )
    parser.add_argument(
        "--skip-nli",
        action="store_true",
        help="跳过 NLI 二层校验, 加速本地跑",
    )
    parser.add_argument(
        "--no-trigger-check",
        action="store_true",
        help="即使没改触发文件也跑 (默认会先看 git diff, 没动 prompt 就跳过)",
    )
    args = parser.parse_args()

    # 1. 看 git diff 决定是否需要跑
    changed = _git_changed_files()
    triggered = _detect_trigger_files(changed)

    if not triggered and not args.no_trigger_check:
        _safe_print("[manual-check] 没改触发 regression 的文件, 跳过 (改 prompt/worker/rules 才需要跑).")
        _safe_print("[manual-check] 强制跑加 --no-trigger-check.")
        return 0

    # 2. 跑 regression
    exit_code, results = _run_regression(
        rules_yaml=args.rules_yaml,
        baseline=args.baseline,
        output=args.results,
        tolerance=args.tolerance,
        skip_nli=args.skip_nli,
    )

    # 3. 生成 markdown 报告
    report = _render_markdown_report(
        results=results,
        exit_code=exit_code,
        trigger_files=triggered,
        tolerance=args.tolerance,
        skip_nli=args.skip_nli,
    )

    if args.output:
        out_path = os.path.abspath(args.output)
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(report)
        _safe_print(f"[manual-check] 报告写入: {out_path}")
        _safe_print(f"[manual-check] 把 {out_path} 内容贴到 PR description.")
    else:
        _safe_print("\n" + "=" * 60)
        _safe_print("以下报告内容请复制贴到 PR description:")
        _safe_print("=" * 60 + "\n")
        _safe_print(report)

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
