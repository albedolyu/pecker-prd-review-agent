#!/usr/bin/env python
"""信鸽 v2 — Learnings Dashboard.

类似 CodeRabbit 的 Learnings UI: text / usage_count / last_used / created_at.

输出 markdown 表格到 workspace/learnings/dashboard.md (默认), 也可 stdout.
高频 unused learning 标记 stale, 给删除建议.

用法:
    python scripts/learnings_dashboard.py --workspace workspace-sample
    python scripts/learnings_dashboard.py --workspace workspace-sample --stdout
    python scripts/learnings_dashboard.py --workspace workspace-sample --output other.md
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from typing import List

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


# 30 天没被注入 + 创建超 14 天 → 标 stale
STALE_DAYS_NO_USE = 30
STALE_MIN_AGE_DAYS = 14


def _safe_print(text: str) -> None:
    try:
        print(text)
    except UnicodeEncodeError:
        encoded = text.encode("gbk", errors="replace").decode("gbk", errors="replace")
        print(encoded)


def _days_since(iso_str: str) -> int:
    if not iso_str:
        return 99999
    try:
        ts = time.mktime(time.strptime(iso_str.split("T")[0], "%Y-%m-%d"))
        return int((time.time() - ts) / 86400)
    except (ValueError, IndexError):
        return 99999


def _is_stale(learning) -> bool:
    age_days = _days_since(learning.created_at)
    if age_days < STALE_MIN_AGE_DAYS:
        return False
    if learning.usage_count == 0:
        return age_days >= STALE_DAYS_NO_USE
    last_used_days = _days_since(learning.last_used) if learning.last_used else age_days
    return last_used_days >= STALE_DAYS_NO_USE


def render_markdown(learnings: List, workspace: str) -> str:
    lines = []
    lines.append(f"# 信鸽 v2 — Learnings Dashboard")
    lines.append("")
    lines.append(f"workspace: `{workspace}`")
    lines.append(f"生成时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"总数: {len(learnings)}")
    lines.append("")

    # 概览
    by_scope = {"org_global": 0, "team_local": 0, "pr_local": 0}
    stale_count = 0
    total_usage = 0
    for l in learnings:
        by_scope[l.scope] = by_scope.get(l.scope, 0) + 1
        total_usage += l.usage_count
        if _is_stale(l):
            stale_count += 1

    lines.append("## 概览")
    lines.append("")
    lines.append(f"- 组织级 (org_global): {by_scope.get('org_global', 0)}")
    lines.append(f"- 团队级 (team_local): {by_scope.get('team_local', 0)}")
    lines.append(f"- PR 级   (pr_local):  {by_scope.get('pr_local', 0)}")
    lines.append(f"- 累计注入次数: {total_usage}")
    lines.append(f"- 候选 stale (建议删除): {stale_count}")
    lines.append("")

    # 主表
    lines.append("## Learnings 列表")
    lines.append("")
    lines.append("| ID | scope | reviewer | trigger | instruction | usage | last_used | created | stale? |")
    lines.append("|----|-------|----------|---------|-------------|-------|-----------|---------|--------|")
    # 排序: stale 在末尾, 内部按 usage_count desc + created_at desc
    learnings_sorted = sorted(
        learnings,
        key=lambda l: (_is_stale(l), -l.usage_count, l.created_at),
    )
    for l in learnings_sorted:
        trigger = l.trigger_pattern.replace("|", "\\|").replace("\n", " ")
        instruction = l.instruction.replace("|", "\\|").replace("\n", " ")
        if len(trigger) > 40:
            trigger = trigger[:38] + "…"
        if len(instruction) > 60:
            instruction = instruction[:58] + "…"
        last_used = (l.last_used or "-").split("T")[0] if l.last_used else "-"
        created = (l.created_at or "-").split("T")[0]
        stale_mark = "stale" if _is_stale(l) else ""
        reviewer = l.reviewer or "-"
        lines.append(
            f"| `{l.id}` | {l.scope} | {reviewer} | {trigger} | {instruction} | "
            f"{l.usage_count} | {last_used} | {created} | {stale_mark} |"
        )
    lines.append("")

    # stale 提示
    stale_list = [l for l in learnings if _is_stale(l)]
    if stale_list:
        lines.append("## Stale Learnings (建议清理)")
        lines.append("")
        lines.append(
            f"以下 learning 创建超 {STALE_MIN_AGE_DAYS} 天且 {STALE_DAYS_NO_USE} 天未被注入. "
            f"PM 可考虑删除."
        )
        lines.append("")
        for l in stale_list:
            age_days = _days_since(l.created_at)
            lines.append(
                f"- `{l.id}` ({l.scope}, age={age_days}d, usage={l.usage_count}): "
                f"{l.trigger_pattern[:30]}…"
            )
            lines.append(f"  删除命令: `python scripts/feedback_v2.py delete {l.id} --workspace {workspace}`")
        lines.append("")

    # 优先级提示
    lines.append("## Scope 优先级")
    lines.append("")
    lines.append("注入到 worker prompt 时, 优先级顺序: **org_global > team_local > pr_local**.")
    lines.append("当多条 learning 命中同一场景, 高优先级覆盖低优先级.")
    lines.append("")
    return "\n".join(lines)


def main(argv=None) -> int:
    from review.learnings_store import LearningsStore

    parser = argparse.ArgumentParser(description="信鸽 v2 Learnings Dashboard")
    parser.add_argument("--workspace", default="workspace-sample")
    parser.add_argument("--output", default=None, help="markdown 输出 (默认 workspace/learnings/dashboard.md)")
    parser.add_argument("--stdout", action="store_true", help="只打印不写文件")
    args = parser.parse_args(argv)

    workspace = os.path.abspath(args.workspace)
    if not os.path.isdir(workspace):
        _safe_print(f"ERROR: workspace 目录不存在: {workspace}")
        return 2

    store = LearningsStore(workspace)
    learnings = store.list_all()

    md = render_markdown(learnings, workspace)

    if args.stdout:
        _safe_print(md)
        return 0

    out_path = args.output or os.path.join(workspace, "learnings", "dashboard.md")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(md)
    _safe_print(f"dashboard 已写入: {out_path}")
    _safe_print(f"  共 {len(learnings)} 条 learning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
