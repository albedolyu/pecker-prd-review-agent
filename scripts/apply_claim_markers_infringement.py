"""一次性给 workspace-侵权软件 wiki 17 条 untagged 强断言加 ^[tag] inline marker.

数据来源: scripts/wiki_lint.py --check-claims --workspace workspace-侵权软件 跑出的 23 条
warning, 经 PM 分类后保留 17 条真问题 (6 verified + 7 inferred + 4 ambiguous), 6 条假阳跳过.

用法:
    python scripts/apply_claim_markers_infringement.py            # dry-run, 输出 diff
    python scripts/apply_claim_markers_infringement.py --apply --yes  # 真改
"""
from __future__ import annotations

import argparse
import difflib
import re
import sys
from pathlib import Path
from typing import NamedTuple

# 修一下 Windows 控制台 UTF-8 输出 (参考 scripts/wiki_lint.py)
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass

WORKSPACE_WIKI = Path("workspace-侵权软件/wiki")


class Patch(NamedTuple):
    """单条 marker patch.

    file_rel: 相对 WORKSPACE_WIKI 的文件名
    line: 1-based 真实行号 (与 wiki_lint 报告一致)
    snippet: claim 起始的文本片段 (用于 str.find 定位)
    tag: verified / inferred / ambiguous
    """

    file_rel: str
    line: int
    snippet: str
    tag: str


# 17 条 patch (按文件名排序, 同文件内按行号)
PATCHES: list[Patch] = [
    # A. verified — PRD 复述/已落定事实 (6 条)
    Patch("决策-侵权软件评审发现.md", 20, "按 `publish_date` 排序", "verified"),
    Patch("概念-侵权软件.md", 17, "侵权软件是指企业被工信部", "verified"),
    Patch("概念-侵权软件.md", 17, "数据来源为工信部官网", "verified"),
    Patch("概念-侵权软件.md", 36, "目标用户：软件使用者", "verified"),
    Patch("概念-riskbird_status枚举.md", 17, "`riskbird_status` 是侵权软件主表", "verified"),
    Patch("约束-ds_risk_software_infringement_data.md", 68, "支持前端切换为升序", "verified"),
    # B. inferred — 推断/无直接证据 (7 条)
    Patch("场景-风险扫描侵权软件.md", 21, "PRD 第三章（风险扫描）整体为从其他需求", "inferred"),
    Patch("场景-风险扫描侵权软件.md", 21, "以下标注为已知信息和待确认项", "inferred"),
    Patch("场景-风险扫描侵权软件.md", 42, "设计图链接：⚠️ 当前为占位链接，需替换为实际 Figma", "inferred"),
    Patch("场景-风险扫描侵权软件.md", 47, "设计图链接：⚠️ 当前为占位链接，需替换", "inferred"),
    Patch("场景-风险扫描侵权软件.md", 51, "本章节为本次评审最严重问题", "inferred"),
    Patch("竞品-企查查-侵权软件.md", 32, "企查查的列表页字段可作为风鸟字段", "inferred"),
    Patch("竞品-企查查-侵权软件.md", 34, "查风险模块为风鸟差异化机会点", "inferred"),
    # C. ambiguous — 待确认/疑问 (4 条 + L34 同行 2 个 = 5 条 patch)
    Patch("概念-riskbird_status枚举.md", 34, "屏蔽（=1）的触发条件是什么", "ambiguous"),
    Patch("概念-riskbird_status枚举.md", 34, "人工操作还是系统自动", "ambiguous"),
    Patch("概念-riskbird_status枚举.md", 35, "是否有其他枚举值", "ambiguous"),
    Patch("约束-ds_risk_software_infringement_data.md", 72, "`riskbird_status` 是否存在其他枚举值", "ambiguous"),
    Patch("约束-ds_risk_software_infringement_data.md", 74, "PG 数据库是否涉及本需求", "ambiguous"),
]


# 句末断句符 (与 review/claim_provenance.py _SENTENCE_TERMINATOR 同步)
_TERMINATOR_PATTERN = re.compile(r"[。！？!?]|\.(?=\s|$|[\u4e00-\u9fa5])")
_EXISTING_MARKER = re.compile(r"\^\[\s*(verified|inferred|ambiguous)\s*\]")


def _find_claim_end(line: str, snippet_end: int) -> int:
    """从 snippet 末尾位置向后扫第一个断句符, 返回 marker 该插的位置(标点之前).

    无断句符则返回行末实词位置 (rstrip 后的长度).
    """
    m = _TERMINATOR_PATTERN.search(line, snippet_end)
    if m:
        return m.start()
    return len(line.rstrip())


def _apply_patch_to_line(line: str, snippet: str, tag: str) -> tuple[str, bool, str]:
    """对单行做一次 patch.

    Returns:
        (new_line, changed, reason)
        changed=False 时 reason 说明跳过原因.
    """
    pos = line.find(snippet)
    if pos < 0:
        return line, False, f"snippet 未在该行匹配: {snippet[:30]}"
    end = _find_claim_end(line, pos + len(snippet))
    chunk = line[pos:end]
    if _EXISTING_MARKER.search(chunk):
        return line, False, "该 claim 已有 marker"
    marker = f"^[{tag}]"
    new = line[:end] + marker + line[end:]
    return new, True, ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="真改文件 (默认 dry-run)")
    ap.add_argument("--yes", action="store_true", help="确认 --apply (双因子)")
    ap.add_argument("--workspace-root", default=".", help="pecker 仓库根目录")
    args = ap.parse_args()

    if args.apply and not args.yes:
        print("[error] --apply 必须配合 --yes 使用 (会改写 workspace wiki, 请确保 git 干净)", file=sys.stderr)
        return 2

    root = Path(args.workspace_root) / WORKSPACE_WIKI
    if not root.is_dir():
        print(f"[error] wiki 目录不存在: {root}", file=sys.stderr)
        return 2

    by_file: dict[str, list[Patch]] = {}
    for p in PATCHES:
        by_file.setdefault(p.file_rel, []).append(p)

    total_files_changed = 0
    total_applied = 0
    total_skipped = 0
    skipped_reasons: list[str] = []
    diffs: list[str] = []

    for file_rel, patches in by_file.items():
        path = root / file_rel
        if not path.is_file():
            print(f"[warn] 文件不存在跳过: {path}", file=sys.stderr)
            total_skipped += len(patches)
            continue
        original_text = path.read_text(encoding="utf-8")
        lines = original_text.split("\n")
        applied_here = 0
        for p in patches:
            idx = p.line - 1
            if idx < 0 or idx >= len(lines):
                total_skipped += 1
                skipped_reasons.append(f"{file_rel}:L{p.line} 行号越界")
                continue
            new_line, changed, reason = _apply_patch_to_line(lines[idx], p.snippet, p.tag)
            if changed:
                lines[idx] = new_line
                applied_here += 1
            else:
                total_skipped += 1
                skipped_reasons.append(f"{file_rel}:L{p.line} {reason}")
        new_text = "\n".join(lines)
        if new_text != original_text:
            total_files_changed += 1
            total_applied += applied_here
            diff = difflib.unified_diff(
                original_text.splitlines(keepends=True),
                new_text.splitlines(keepends=True),
                fromfile=str(path),
                tofile=str(path) + " (with markers)",
                n=1,
            )
            diffs.append("".join(diff))
            if args.apply:
                path.write_text(new_text, encoding="utf-8")

    print()
    for d in diffs:
        print(d)
    print()
    print(f"=== 汇总: {total_files_changed} 文件, "
          f"{total_applied} 条 marker {'已写入' if args.apply else '将插入'}, "
          f"{total_skipped} 条跳过 ===")
    if skipped_reasons:
        print("[skipped 详情]")
        for r in skipped_reasons:
            print(f"  - {r}")
    if not args.apply:
        print("(dry-run, 未改动文件; 加 --apply --yes 真改)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
