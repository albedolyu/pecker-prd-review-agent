#!/usr/bin/env python
"""信鸽 v2 CLI — PM 自然语言反馈 → 结构化 learning record.

与 v1 (feedback.py / feedback_cmd.py) 共存. v1 看代码 commit 反推, v2 直接接受 PM 反馈.

用法:
  # 添加 learning (核心)
  python scripts/feedback_v2.py add \\
      --workspace workspace-sample \\
      --finding R-001 \\
      --feedback "这条是误报, 分页字段已统一约定为 20" \\
      --reviewer 潘驰 \\
      --scope team_local \\
      --rule-id RC-005 \\
      --dim-key ai_coding

  # 列出
  python scripts/feedback_v2.py list --workspace workspace-sample
  python scripts/feedback_v2.py list --workspace workspace-sample --scope team_local
  python scripts/feedback_v2.py list --workspace workspace-sample --dim-key data_quality

  # 详情
  python scripts/feedback_v2.py show <learning_id> --workspace workspace-sample

  # 删除 (PM 撤回反馈)
  python scripts/feedback_v2.py delete <learning_id> --workspace workspace-sample
"""
from __future__ import annotations

import argparse
import os
import sys

# 让 scripts/ 目录运行时能 import 项目根
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def _safe_print(text: str) -> None:
    """Windows GBK 控制台兜底打印 — 转 GBK 编不了的字符走 ascii fallback."""
    try:
        print(text)
    except UnicodeEncodeError:
        # GBK 编不了的字符替换成 ?
        encoded = text.encode("gbk", errors="replace").decode("gbk", errors="replace")
        print(encoded)


def _parse_natural_feedback(feedback: str) -> tuple:
    """从 PM 自然语言里启发式抽 trigger_pattern + instruction.

    简单规则 (够用):
      - 包含 "误报" / "不要再报" / "这条是" → 整句作为 instruction, trigger 用 "类似场景"
      - 包含 "时" / "的时候" / "如果" → 拆成 trigger + instruction (按这些词分句)
      - 否则: trigger="该场景出现时", instruction=整句

    返回: (trigger_pattern, instruction)
    """
    feedback = (feedback or "").strip()
    if not feedback:
        return "", ""

    # 拆分尝试: 找"时,"或"时:"或"的话"
    for sep in ["时,", "时,", "时:", "时, ", "的话, ", "如果"]:
        if sep in feedback:
            parts = feedback.split(sep, 1)
            if len(parts) == 2 and parts[0].strip() and parts[1].strip():
                trigger = parts[0].strip().lstrip("当") + ("时" if "时" not in parts[0] else "")
                instruction = parts[1].strip().lstrip(",,:")
                return trigger, instruction

    # 误报反馈: 整句作 instruction
    if any(kw in feedback for kw in ("误报", "不要再报", "这条是", "不要报")):
        return "出现类似场景", feedback

    # fallback
    return "该场景出现时", feedback


def cmd_add(args) -> int:
    from review.learnings_store import LearningsStore, SCOPES

    if args.scope and args.scope not in SCOPES:
        _safe_print(f"ERROR: scope 必须是 {SCOPES} 之一")
        return 2

    workspace = os.path.abspath(args.workspace)
    if not os.path.isdir(workspace):
        _safe_print(f"ERROR: workspace 目录不存在: {workspace}")
        return 2

    # 拆 trigger + instruction
    if args.trigger and args.instruction:
        trigger = args.trigger
        instruction = args.instruction
    else:
        trigger, instruction = _parse_natural_feedback(args.feedback or "")
        if not trigger or not instruction:
            _safe_print("ERROR: --feedback 解析不出 trigger+instruction, 请用 --trigger 和 --instruction 显式指定")
            return 2

    related_rules = args.rule_id or []
    dim_keys = args.dim_key or []

    store = LearningsStore(workspace)
    learning = store.add(
        trigger_pattern=trigger,
        instruction=instruction,
        scope=args.scope or "pr_local",
        source_finding_id=args.finding,
        reviewer=args.reviewer or "",
        related_rule_ids=related_rules,
        dim_keys=dim_keys,
    )

    # 显式确认 (CodeRabbit "Learnings Added" 模式)
    _safe_print("=" * 60)
    _safe_print(f"已记录 (Learning Added)")
    _safe_print("=" * 60)
    _safe_print(f"  learning_id: {learning.id}")
    _safe_print(f"  scope:       {learning.scope}")
    _safe_print(f"  reviewer:    {learning.reviewer or '(未填)'}")
    _safe_print(f"  trigger:     {learning.trigger_pattern}")
    _safe_print(f"  instruction: {learning.instruction}")
    if learning.related_rule_ids:
        _safe_print(f"  rules:       {', '.join(learning.related_rule_ids)}")
    if learning.dim_keys:
        _safe_print(f"  dims:        {', '.join(learning.dim_keys)}")
    if learning.source_finding_id:
        _safe_print(f"  source:      finding={learning.source_finding_id}")
    _safe_print(f"")
    _safe_print(f"下次评审时, 当 PRD 出现 trigger 描述的情况, worker 会按 instruction 执行.")
    return 0


def cmd_list(args) -> int:
    from review.learnings_store import LearningsStore

    workspace = os.path.abspath(args.workspace)
    if not os.path.isdir(workspace):
        _safe_print(f"ERROR: workspace 目录不存在: {workspace}")
        return 2

    store = LearningsStore(workspace)
    learnings = store.list_all(
        scope=args.scope,
        dim_key=args.dim_key,
        reviewer=args.reviewer,
    )
    if not learnings:
        _safe_print("(无 learning)")
        return 0

    # 简洁表格输出
    _safe_print(f"{'id':<10} {'scope':<12} {'usage':>5}  {'reviewer':<10}  trigger / instruction")
    _safe_print("-" * 100)
    for l in learnings:
        trigger_short = (l.trigger_pattern[:30]) + ("..." if len(l.trigger_pattern) > 30 else "")
        instr_short = (l.instruction[:40]) + ("..." if len(l.instruction) > 40 else "")
        reviewer_short = (l.reviewer or "-")[:10]
        _safe_print(
            f"{l.id:<10} {l.scope:<12} {l.usage_count:>5}  {reviewer_short:<10}  "
            f"{trigger_short} -> {instr_short}"
        )
    _safe_print("")
    _safe_print(f"共 {len(learnings)} 条")
    return 0


def cmd_show(args) -> int:
    from review.learnings_store import LearningsStore

    workspace = os.path.abspath(args.workspace)
    store = LearningsStore(workspace)
    learning = store.get(args.id)
    if not learning:
        _safe_print(f"ERROR: 找不到 learning id={args.id}")
        return 2

    _safe_print("=" * 60)
    _safe_print(f"Learning {learning.id}")
    _safe_print("=" * 60)
    _safe_print(f"  scope:        {learning.scope}")
    _safe_print(f"  reviewer:     {learning.reviewer}")
    _safe_print(f"  created_at:   {learning.created_at}")
    _safe_print(f"  last_used:    {learning.last_used or '(从未注入)'}")
    _safe_print(f"  usage_count:  {learning.usage_count}")
    _safe_print(f"  source:       {learning.source_finding_id or '(无)'}")
    _safe_print(f"  rules:        {', '.join(learning.related_rule_ids) or '(无)'}")
    _safe_print(f"  dims:         {', '.join(learning.dim_keys) or '(全维度)'}")
    _safe_print(f"")
    _safe_print(f"  trigger:      {learning.trigger_pattern}")
    _safe_print(f"  instruction:  {learning.instruction}")
    return 0


def cmd_delete(args) -> int:
    from review.learnings_store import LearningsStore

    workspace = os.path.abspath(args.workspace)
    store = LearningsStore(workspace)
    if store.delete(args.id):
        _safe_print(f"已删除 learning {args.id}")
        return 0
    _safe_print(f"ERROR: 找不到 learning id={args.id}")
    return 2


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="信鸽 v2 — PM 反馈 → 结构化 learning")
    parser.add_argument("--workspace", default="workspace-sample", help="workspace 路径")

    sub = parser.add_subparsers(dest="cmd", required=True)

    # add
    p_add = sub.add_parser("add", help="添加 learning")
    p_add.add_argument("--finding", help="来源 finding id (可选)")
    p_add.add_argument("--feedback", help="PM 自然语言反馈 (会启发式拆 trigger+instruction)")
    p_add.add_argument("--trigger", help="trigger_pattern (与 --instruction 一起显式指定时优先于 --feedback)")
    p_add.add_argument("--instruction", help="instruction (显式)")
    p_add.add_argument("--reviewer", default="", help="PM 名字")
    p_add.add_argument("--scope", default="pr_local", choices=["pr_local", "team_local", "org_global"])
    p_add.add_argument("--rule-id", action="append", help="关联规则 id (可多次)")
    p_add.add_argument("--dim-key", action="append", help="关联维度 key (可多次, 默认全维度可见)")

    # list
    p_list = sub.add_parser("list", help="列出 learnings")
    p_list.add_argument("--scope", choices=["pr_local", "team_local", "org_global"])
    p_list.add_argument("--dim-key")
    p_list.add_argument("--reviewer")

    # show
    p_show = sub.add_parser("show", help="详情")
    p_show.add_argument("id")

    # delete
    p_del = sub.add_parser("delete", help="删除 learning")
    p_del.add_argument("id")

    args = parser.parse_args(argv)

    if args.cmd == "add":
        return cmd_add(args)
    elif args.cmd == "list":
        return cmd_list(args)
    elif args.cmd == "show":
        return cmd_show(args)
    elif args.cmd == "delete":
        return cmd_delete(args)
    return 1


if __name__ == "__main__":
    sys.exit(main())
