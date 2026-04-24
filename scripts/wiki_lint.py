"""T4 Wiki frontmatter v2 lint — warn-only, 不 error, 不阻塞 CI (2026-04-24).

spec: docs/wiki-frontmatter-v2.md 第四节

扫 workspace-*/wiki/*.md, 产 markdown 表:
  1. 按 workspace × authority tier 统计分布
  2. 列每条 warning (哪个文件哪一条规则不过)

不改任何 wiki 文件, 不 error exit (哪怕 warn 满屏). 只读, 适合 CI 展示.

用法:
  python scripts/wiki_lint.py                              # 所有 workspace
  python scripts/wiki_lint.py --workspace workspace-侵权软件
  python scripts/wiki_lint.py --format json                # 给下游脚本消费
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from review.evidence_verify import (
    _META_WIKI_FILENAMES,
    _parse_wiki_frontmatter,
    _wiki_authority_tier,
)


# 过期阈值 (docs/wiki-frontmatter-v2.md 第二节)
_CANONICAL_MAX_DAYS = 180
_TRUSTED_MAX_DAYS = 90


def lint_wiki_file(path):
    """返回 [warning_msg, ...], 空列表表示这条 wiki 全过."""
    warnings = []
    fm = _parse_wiki_frontmatter(path)
    rel = os.path.relpath(path)

    if not fm:
        warnings.append(f"{rel}: frontmatter 解析失败或缺失, 文件不进 strong evidence 池")
        return warnings

    # 必填字段检查 (warn only, 不 error)
    for field in ("title", "authority", "owner", "sources"):
        if field not in fm:
            warnings.append(f"{rel}: 缺字段 `{field}`")

    # sources 与 authority 矛盾
    try:
        sources_n = int(fm.get("sources", "0") or "0")
    except (ValueError, TypeError):
        sources_n = 0

    authority = fm.get("authority", "").strip()

    if sources_n == 0 and authority in ("canonical", "trusted"):
        warnings.append(
            f"{rel}: sources:0 但 authority={authority}, 读取时会强制降到 generated (见 _wiki_authority_tier)"
        )

    if authority == "canonical" and sources_n < 2:
        warnings.append(f"{rel}: authority=canonical 要求 sources>=2, 实际 {sources_n}")
    if authority == "trusted" and sources_n < 1:
        warnings.append(f"{rel}: authority=trusted 要求 sources>=1, 实际 {sources_n}")

    # last_verified 过期
    lv_raw = fm.get("last_verified", "").strip()
    if authority in ("canonical", "trusted"):
        if not lv_raw:
            warnings.append(f"{rel}: authority={authority} 要求 last_verified, 未填")
        else:
            try:
                lv_date = datetime.strptime(lv_raw, "%Y-%m-%d")
                age = (datetime.now() - lv_date).days
                max_days = _CANONICAL_MAX_DAYS if authority == "canonical" else _TRUSTED_MAX_DAYS
                if age > max_days:
                    warnings.append(
                        f"{rel}: authority={authority} 的 last_verified={lv_raw} "
                        f"已 {age} 天 > {max_days}d, 建议重新 verify"
                    )
            except ValueError:
                warnings.append(f"{rel}: last_verified={lv_raw} 格式非 YYYY-MM-DD")

    # verified_by 建议 (非硬性)
    if authority in ("canonical", "trusted") and not fm.get("verified_by", "").strip():
        warnings.append(f"{rel}: authority={authority} 建议补 verified_by (PM/研发/数据)")

    return warnings


def lint_workspace(ws_path):
    """扫一个 workspace 的 wiki 目录. 返回 (distribution Counter, [all_warnings])."""
    wiki_dir = os.path.join(ws_path, "wiki")
    if not os.path.isdir(wiki_dir):
        return Counter(), []

    dist: Counter[str] = Counter()
    warnings: list[str] = []
    for p in glob.glob(os.path.join(wiki_dir, "*.md")):
        if os.path.basename(p) in _META_WIKI_FILENAMES:
            continue
        tier = _wiki_authority_tier(p)
        dist[tier] += 1
        warnings.extend(lint_wiki_file(p))
    return dist, warnings


def find_workspaces(root, specific=None):
    """找所有 workspace-* 目录."""
    if specific:
        p = os.path.join(root, specific)
        return [p] if os.path.isdir(p) else []
    return sorted(
        p for p in glob.glob(os.path.join(root, "workspace-*"))
        if os.path.isdir(p)
    )


def build_markdown_report(results):
    """results = {ws_name: (dist, warnings)}, 生成 markdown 表."""
    lines = ["# Wiki frontmatter v2 lint 报告", "",
             f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M')}", "",
             "## 按 workspace × authority 分布", "",
             "| workspace | canonical | trusted | contextual | generated | 合计 |",
             "|---|---:|---:|---:|---:|---:|"]

    total_dist: Counter[str] = Counter()
    for ws, (dist, _) in sorted(results.items()):
        tiers = [dist.get(t, 0) for t in ("canonical", "trusted", "contextual", "generated")]
        total = sum(tiers)
        lines.append(f"| {os.path.basename(ws)} | {tiers[0]} | {tiers[1]} | {tiers[2]} | {tiers[3]} | {total} |")
        for t in ("canonical", "trusted", "contextual", "generated"):
            total_dist[t] += dist.get(t, 0)

    total_all = sum(total_dist.values())
    lines.append(f"| **合计** | {total_dist['canonical']} | {total_dist['trusted']} | "
                 f"{total_dist['contextual']} | {total_dist['generated']} | {total_all} |")
    lines.append("")

    # Warnings
    total_warn = sum(len(w) for _, w in results.values())
    lines.append(f"## Warnings ({total_warn} 条)")
    lines.append("")
    if total_warn == 0:
        lines.append("✓ 全部通过")
    else:
        for ws, (_, warnings) in sorted(results.items()):
            if not warnings:
                continue
            lines.append(f"### {os.path.basename(ws)}")
            for w in warnings:
                lines.append(f"- {w}")
            lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Wiki frontmatter v2 lint (warn-only)")
    parser.add_argument("--workspace", help="指定 workspace (不加则扫全部 workspace-*)")
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    parser.add_argument("--root", default=".", help="项目根 (默认 cwd)")
    args = parser.parse_args()

    root = os.path.abspath(args.root)
    ws_paths = find_workspaces(root, args.workspace)
    if not ws_paths:
        print(f"[wiki_lint] 没找到 workspace ({args.workspace or 'workspace-*'}) in {root}")
        return 0

    results = {os.path.basename(ws): lint_workspace(ws) for ws in ws_paths}

    if args.format == "json":
        out = {
            ws: {
                "distribution": dict(dist),
                "warnings": warnings,
            }
            for ws, (dist, warnings) in results.items()
        }
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        print(build_markdown_report(results))

    return 0   # warn-only, 永远 0 退出


if __name__ == "__main__":
    sys.exit(main())
