"""T4 Wiki frontmatter v2 migrate — 冷启动默认映射 (2026-04-24).

spec: docs/wiki-frontmatter-v2.md 第六节 (Phase 2)

本阶段只支持 --dry-run, 不真改文件. 输出 "会改多少个文件, 新分布长啥样".
--apply 目前 error out (等 Phase 2 审完 dry-run 统计后才开).

用法:
  python scripts/wiki_migrate_v2.py --dry-run               # 默认, 贴分布
  python scripts/wiki_migrate_v2.py --dry-run --workspace workspace-侵权软件
  python scripts/wiki_migrate_v2.py --apply                 # 本 Phase 禁用, exit 1
"""
from __future__ import annotations

import argparse
import glob
import os
import sys
from collections import Counter
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from review.evidence_verify import (
    _META_WIKI_FILENAMES,
    _parse_wiki_frontmatter,
    _wiki_authority_tier,
)


def propose_frontmatter_delta(path, owner_default="pecker-auto"):
    """返回 (current_tier, proposed_tier, new_fields) 三元组.

    new_fields 是"会追加/改动"的 frontmatter 字段 dict. 不真改, 只说明.
    """
    fm = _parse_wiki_frontmatter(path)
    current_tier = _wiki_authority_tier(path)

    new_fields = {}
    if "authority" not in fm:
        # 按当前 tier 显式声明 (冷启动固化)
        new_fields["authority"] = current_tier
    if "owner" not in fm:
        # generated 归 pecker-auto, 其他默认 albedolyu 待 PM 手工改
        new_fields["owner"] = owner_default if current_tier == "generated" else "albedolyu"
    if "last_verified" not in fm and current_tier in ("canonical", "trusted"):
        new_fields["last_verified"] = datetime.now().strftime("%Y-%m-%d")
    # sources 字段不动 — 本 migrate 不伪造 sources 数

    # proposed_tier 跟 current_tier 一致 (冷启动不升级, 只固化)
    return current_tier, current_tier, new_fields


def scan_workspace(ws_path):
    """扫一个 workspace, 返回 (files_to_change_count, dist_before, dist_after, changes_list)."""
    wiki_dir = os.path.join(ws_path, "wiki")
    if not os.path.isdir(wiki_dir):
        return 0, Counter(), Counter(), []

    dist_before: Counter[str] = Counter()
    dist_after: Counter[str] = Counter()
    changes: list[dict] = []

    for p in glob.glob(os.path.join(wiki_dir, "*.md")):
        if os.path.basename(p) in _META_WIKI_FILENAMES:
            continue
        current, proposed, new_fields = propose_frontmatter_delta(p)
        dist_before[current] += 1
        dist_after[proposed] += 1
        if new_fields:
            changes.append({
                "file": os.path.relpath(p),
                "current_tier": current,
                "proposed_tier": proposed,
                "new_fields": new_fields,
            })

    return len(changes), dist_before, dist_after, changes


def find_workspaces(root, specific=None):
    if specific:
        p = os.path.join(root, specific)
        return [p] if os.path.isdir(p) else []
    return sorted(
        p for p in glob.glob(os.path.join(root, "workspace-*"))
        if os.path.isdir(p)
    )


def build_report(all_results):
    lines = ["# Wiki frontmatter v2 migrate — dry-run 预演报告", "",
             f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M')}", "",
             "**说明**: 冷启动不升级 tier (current == proposed), 只固化 authority/owner/last_verified 字段.",
             "实际 tier 分布不变 — 因为 `_wiki_authority_tier` 的推导逻辑本就以默认映射读取.",
             "",
             "## 按 workspace 统计", "",
             "| workspace | 待改文件数 | canonical | trusted | contextual | generated |",
             "|---|---:|---:|---:|---:|---:|"]

    total_changes = 0
    total_dist: Counter[str] = Counter()
    for ws, (count, _, dist_after, _) in sorted(all_results.items()):
        tiers = [dist_after.get(t, 0) for t in ("canonical", "trusted", "contextual", "generated")]
        lines.append(f"| {os.path.basename(ws)} | {count} | {tiers[0]} | {tiers[1]} | {tiers[2]} | {tiers[3]} |")
        total_changes += count
        for t in ("canonical", "trusted", "contextual", "generated"):
            total_dist[t] += dist_after.get(t, 0)

    lines.append(f"| **合计** | {total_changes} | {total_dist['canonical']} | {total_dist['trusted']} | "
                 f"{total_dist['contextual']} | {total_dist['generated']} |")
    lines.append("")

    # 细节: 每个文件会追加哪些字段
    lines.append("## 每个文件待追加的 frontmatter 字段")
    lines.append("")
    lines.append("<details><summary>展开 (最多 30 条, 超出请跑 --format json)</summary>")
    lines.append("")

    all_changes = [c for _, (_, _, _, cs) in sorted(all_results.items()) for c in cs]
    for c in all_changes[:30]:
        fields_str = ", ".join(f"`{k}: {v}`" for k, v in c["new_fields"].items())
        lines.append(f"- {c['file']} → 追加 {fields_str}")
    if len(all_changes) > 30:
        lines.append(f"- ... 另 {len(all_changes) - 30} 条")
    lines.append("")
    lines.append("</details>")
    lines.append("")

    lines.append("## 下一步")
    lines.append("")
    lines.append("Phase 2 审完分布合理 → `python scripts/wiki_migrate_v2.py --apply` 真写文件.")
    lines.append("本 Phase (第一周) 禁用 --apply.")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Wiki frontmatter v2 migrate (Phase 1 dry-run only)")
    parser.add_argument("--workspace", help="指定 workspace")
    parser.add_argument("--root", default=".")
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--apply", action="store_true",
                        help="Phase 1 禁用, 报 error 提示先审 dry-run")
    parser.add_argument("--out-file", help="写 markdown 到文件 (默认 stdout)")
    args = parser.parse_args()

    if args.apply:
        print("[wiki_migrate] ERROR: Phase 1 只允许 --dry-run.")
        print("先跑 --dry-run, 审完 canonical/trusted/contextual/generated 分布合理后再说 --apply.")
        print("（spec: docs/wiki-frontmatter-v2.md 第六节 Phase 2）")
        return 1

    root = os.path.abspath(args.root)
    ws_paths = find_workspaces(root, args.workspace)
    if not ws_paths:
        print(f"[wiki_migrate] 没找到 workspace in {root}")
        return 0

    results = {os.path.basename(ws): scan_workspace(ws) for ws in ws_paths}
    text = build_report(results)
    if args.out_file:
        with open(args.out_file, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"[wiki_migrate] 报告写入 {args.out_file}")
    else:
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except (AttributeError, OSError):
            pass
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
