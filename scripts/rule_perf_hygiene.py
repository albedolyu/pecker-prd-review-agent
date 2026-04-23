"""rule_perf_hygiene.py — 对账 rule_performance_history.json 和 checklist 定义.

为什么做 (2026-04-23 #5a+5c 优化):
- 现有 Kakapo 扫 wiki 断链 / 孤立页, 但扫不到 `rule_performance_history.json`
  里的孤立规则 (checklist 里没有 / wiki 已经删了 / rename 了但历史数据还在)
- 也扫不到反向: wiki checklist 有但 rule_perf 从未记录过的 "冷启动"规则

本脚本对账两边:
- 僵尸规则 (zombies): rule_perf 有数据但 checklist 里找不到 rule_id
  风险 — 下次评审时这些规则仍可能影响 EMA 但没人维护
- 冷启动规则 (cold): checklist 定义了但 rule_perf 里没数据
  信号 — 从未触发过, 可能 prompt 里没引导到, 或覆盖率漏了

用法:
  python scripts/rule_perf_hygiene.py                            # 扫全部 workspace-*
  python scripts/rule_perf_hygiene.py --workspace workspace-foo
  python scripts/rule_perf_hygiene.py --format json              # 给 CI / dashboard 用
  python scripts/rule_perf_hygiene.py --strict                   # 有僵尸时 exit 1

退出码:
  0: 健康
  1: strict 模式 + 发现问题
  2: 脚本错误
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Iterator, List, Set, Tuple

PROJECT_ROOT = Path(__file__).parent.parent.resolve()

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from review.dimensions import get_review_dimensions  # noqa: E402
from rule_perf_store import RulePerformanceHistoryStore, _META_KEY  # noqa: E402


def collect_checklist_rule_ids() -> Set[str]:
    rule_ids: Set[str] = set()
    dims = get_review_dimensions()
    for dim_key, dim_cfg in dims.items():
        for item in dim_cfg.get("checklist", []):
            rid = (item.get("rule_id") or "").strip()
            if rid:
                rule_ids.add(rid)
    return rule_ids


def iter_workspace_stores(project_root: Path, workspace: str = "") -> Iterator[Tuple[str, RulePerformanceHistoryStore]]:
    pattern = workspace if workspace else "workspace-*"
    for ws_dir in sorted(project_root.glob(pattern)):
        if not ws_dir.is_dir():
            continue
        if not (ws_dir / "output").is_dir():
            continue
        store = RulePerformanceHistoryStore(ws_dir)
        if not store.path.is_file():
            continue
        yield ws_dir.name, store


def audit_workspace(
    store: RulePerformanceHistoryStore,
    valid_rule_ids: Set[str],
) -> Dict[str, Any]:
    history = store.load()
    tracked_rule_ids = {rid for rid in history.keys() if rid != _META_KEY}

    zombies = sorted(tracked_rule_ids - valid_rule_ids)
    cold = sorted(valid_rule_ids - tracked_rule_ids)

    return {
        "path": str(store.path),
        "schema_version": history.get(_META_KEY, {}).get("schema_version", 0),
        "total_valid_rules": len(valid_rule_ids),
        "total_tracked_rules": len(tracked_rule_ids),
        "zombies": zombies,
        "cold_rules": cold,
    }


def render_text(results: List[Tuple[str, Dict[str, Any]]]) -> str:
    lines = ["=== rule_perf_hygiene: rule_performance_history vs checklist 对账 ==="]
    if not results:
        lines.append("(无 workspace 含 rule_performance_history.json)")
        return "\n".join(lines)

    for ws_name, audit in results:
        lines.append(f"\n[{ws_name}]  (schema v{audit['schema_version']})")
        lines.append(f"  checklist 定义 {audit['total_valid_rules']} 条, 历史追踪 {audit['total_tracked_rules']} 条")
        zombies = audit["zombies"]
        cold = audit["cold_rules"]
        if zombies:
            lines.append(f"  [warn] 僵尸规则 ({len(zombies)}): 历史有数据但 checklist 已无")
            for rid in zombies:
                lines.append(f"      - {rid}")
        if cold:
            lines.append(f"  [info] 冷启动规则 ({len(cold)}): checklist 定义了但未触发过 EMA")
            for rid in cold[:10]:
                lines.append(f"      - {rid}")
            if len(cold) > 10:
                lines.append(f"      ... +{len(cold) - 10} 条")
        if not zombies and not cold:
            lines.append("  [OK] 健康")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--workspace", default="", help="只扫指定 workspace, 默认全部")
    parser.add_argument("--format", choices=["text", "json"], default="text")
    parser.add_argument("--strict", action="store_true",
                        help="有僵尸规则就 exit 1 (CI gate 模式, 冷启动不触发)")
    args = parser.parse_args()

    valid_ids = collect_checklist_rule_ids()
    results: List[Tuple[str, Dict[str, Any]]] = []

    for ws_name, store in iter_workspace_stores(PROJECT_ROOT, args.workspace):
        results.append((ws_name, audit_workspace(store, valid_ids)))

    if args.format == "json":
        out = json.dumps(
            {"workspaces": [{"name": n, **a} for n, a in results]},
            ensure_ascii=False, indent=2,
        )
    else:
        out = render_text(results)

    try:
        print(out)
    except UnicodeEncodeError:
        sys.stdout.buffer.write(out.encode("utf-8", errors="replace"))
        sys.stdout.buffer.write(b"\n")

    if args.strict:
        for _, audit in results:
            if audit["zombies"]:
                return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
