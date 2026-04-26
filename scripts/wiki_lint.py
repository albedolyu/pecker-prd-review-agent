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
from review.claim_provenance import lint_wiki_claims


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


def scan_claim_provenance(ws_paths):
    """对每个 workspace 的 wiki 跑 claim-level provenance lint.

    只扫 generated/contextual tier 的 wiki (canonical/trusted 由 PM 校对).
    返回 {ws_name: [(file_path, [ClaimLintWarning, ...]), ...]}.

    spec: obsidian-wiki inline marker (^[verified]/^[inferred]/^[ambiguous]).
    """
    out: dict[str, list[tuple[str, list]]] = {}
    for ws in ws_paths:
        ws_name = os.path.basename(ws)
        wiki_dir = os.path.join(ws, "wiki")
        if not os.path.isdir(wiki_dir):
            out[ws_name] = []
            continue
        files: list[tuple[str, list]] = []
        for p in glob.glob(os.path.join(wiki_dir, "*.md")):
            if os.path.basename(p) in _META_WIKI_FILENAMES:
                continue
            tier = _wiki_authority_tier(p)
            if tier not in ("generated", "contextual"):
                continue
            warns = lint_wiki_claims(p, authority=tier)
            if warns:
                files.append((p, warns))
        out[ws_name] = files
    return out


def build_claim_report(claim_results):
    """生成 claim-level provenance lint 的 markdown 报告.

    格式:
    - workspace × file × warning_count 表
    - 附 sample 5 条
    """
    lines = ["# Claim-level provenance lint 报告", "",
             f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M')}", "",
             "扫描所有 generated/contextual tier 的 wiki, 检查 untagged 强断言句",
             "(参考 obsidian-wiki ^[verified]/^[inferred]/^[ambiguous] 语法).", "",
             "## workspace × file × warning_count", "",
             "| workspace | file | warnings |",
             "|---|---|---:|"]

    total = 0
    samples: list[str] = []
    for ws_name, files in sorted(claim_results.items()):
        for fp, warns in files:
            n = len(warns)
            total += n
            rel = os.path.relpath(fp)
            lines.append(f"| {ws_name} | `{os.path.basename(fp)}` | {n} |")
            if len(samples) < 5:
                for w in warns[: max(1, 5 - len(samples))]:
                    if len(samples) >= 5:
                        break
                    samples.append(f"- `{rel}:{w.line}` — {w.reason}: {w.claim_text[:80]}")

    if total == 0:
        lines.append("| (无) | - | 0 |")

    lines.append(f"\n**合计 untagged 强断言**: {total} 条\n")

    if samples:
        lines.append("## Sample warnings (前 5 条)\n")
        lines.extend(samples)
        lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Wiki frontmatter v2 lint (warn-only)")
    parser.add_argument("--workspace", help="指定 workspace (不加则扫全部 workspace-*)")
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    parser.add_argument("--root", default=".", help="项目根 (默认 cwd)")
    parser.add_argument(
        "--check-claims",
        action="store_true",
        help="启用 claim-level provenance lint (扫 untagged 强断言, 参考 obsidian-wiki)",
    )
    args = parser.parse_args()

    root = os.path.abspath(args.root)
    ws_paths = find_workspaces(root, args.workspace)
    if not ws_paths:
        print(f"[wiki_lint] 没找到 workspace ({args.workspace or 'workspace-*'}) in {root}")
        return 0

    # claim-level provenance 模式: 单独走 lint_wiki_claims
    if args.check_claims:
        claim_results = scan_claim_provenance(ws_paths)
        if args.format == "json":
            out = {
                ws_name: [
                    {
                        "file": os.path.relpath(fp),
                        "warnings": [
                            {"line": w.line, "reason": w.reason, "claim": w.claim_text}
                            for w in warns
                        ],
                    }
                    for fp, warns in files
                ]
                for ws_name, files in claim_results.items()
            }
            text = json.dumps(out, ensure_ascii=False, indent=2)
        else:
            text = build_claim_report(claim_results)

        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except (AttributeError, OSError):
            pass
        try:
            print(text)
        except UnicodeEncodeError:
            print(text.encode("ascii", errors="replace").decode("ascii"))
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
        text = json.dumps(out, ensure_ascii=False, indent=2)
    else:
        text = build_markdown_report(results)

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        pass
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.encode("ascii", errors="replace").decode("ascii"))

    return 0   # warn-only, 永远 0 退出


if __name__ == "__main__":
    sys.exit(main())
