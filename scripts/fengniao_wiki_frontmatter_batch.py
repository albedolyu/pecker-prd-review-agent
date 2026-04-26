"""风鸟 wiki 批量 frontmatter 补全工具 (sprint Day3+ 双保险, 2026-04-26).

# 背景
风鸟代码库 wiki (`C:\\Users\\20834\\Desktop\\代码项目\\风鸟代码库\\wiki\\`) 51 个 .md
是从 `riskbird-mobile-vue3` (前端) + `RiskBirdApi` (后端) 源码自动同步生成的代码 wiki,
理论上应该是 **canonical** 级 (源码 = ground truth).

但目前 51 个文件 frontmatter 里 0 个有 `verified_by` 字段, 按 pecker
`review/evidence_verify.py:_wiki_authority_tier` 的冷启动映射规则:
  - `sources == 0` → generated
  - `sources >= 1 + verified_by 空` → contextual
  - `sources >= 1 + verified_by 有` → trusted
  - `authority: canonical` 必须显式且非 sources:0
所以现在它们要么 generated 要么 contextual, **永远进不了强依据池**.

pecker 已用 `PECKER_EXTERNAL_CANONICAL_WIKI` env 路径优先级 0 强制 override 成 canonical
(见 `_is_external_canonical_path`), 但这是单点保护. 本脚本批量补 frontmatter 让
**即使按 cold-start 也能算 canonical**, 做双保险.

# 补的字段 (尊重已有, 不覆盖)
- `verified_by: 源码同步` (满足 cold-start 的 trusted/canonical 必要条件)
- `sources: <count>` (数正文里 riskbird-mobile-vue3 / RiskBirdApi 出现次数, 至少 1)
- `last_verified: "2026-04-26"` (今天)
- `authority: canonical` (显式声明)

# 用法
  # dry-run (默认), 看会改什么不真改
  python scripts/fengniao_wiki_frontmatter_batch.py --out report.md

  # 真改 (会先警告)
  python scripts/fengniao_wiki_frontmatter_batch.py --apply --yes

# 约束
  - 默认 dry-run, --apply 必须配 --yes 才真改
  - 已有字段绝对不动 (idempotent)
  - YAML 解析失败的文件 warn + 跳过, 不阻断
  - --apply 时追加 audit 行到 wiki-root/log.md
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import datetime
from typing import Dict, List, Tuple

import yaml


# 默认风鸟 wiki 根目录
_DEFAULT_WIKI_ROOT = r"C:/Users/20834/Desktop/代码项目/风鸟代码库/wiki"

# 源码仓库关键词 — 用来数 sources 字段缺失时的兜底引用计数
_SOURCE_REPO_KEYWORDS = ("riskbird-mobile-vue3", "RiskBirdApi")

# 今天日期 (任务约定 2026-04-26)
_TODAY = "2026-04-26"

# 补的标准字段值
_DEFAULT_VERIFIED_BY = "源码同步"
_DEFAULT_AUTHORITY = "canonical"


def _split_frontmatter(raw: str) -> Tuple[Dict, str, str]:
    """切 raw markdown 为 (frontmatter_dict, fm_text, body).

    没 frontmatter → ({}, "", raw).
    有 frontmatter 但 yaml 解析失败 → 抛 yaml.YAMLError, 上层 warn + skip.
    """
    m = re.match(r"^\s*---\s*\n(.*?)\n---\s*\n?(.*)$", raw, re.DOTALL)
    if not m:
        return {}, "", raw
    fm_text = m.group(1)
    body = m.group(2)
    fm = yaml.safe_load(fm_text)
    if fm is None:
        return {}, fm_text, body
    if not isinstance(fm, dict):
        # frontmatter 不是 dict (e.g. 纯字符串/list), 视为无效
        raise yaml.YAMLError(f"frontmatter 不是 dict: {type(fm).__name__}")
    return fm, fm_text, body


def _count_source_refs(body: str) -> int:
    """数正文里源码仓库关键词出现总次数, 至少返回 1."""
    total = 0
    for kw in _SOURCE_REPO_KEYWORDS:
        total += body.count(kw)
    return max(total, 1)


def _compute_added_fields(fm: Dict, body: str) -> Dict:
    """对照现有 frontmatter, 计算要补的字段 (已有的不动)."""
    added: Dict = {}
    if "verified_by" not in fm or not str(fm.get("verified_by", "")).strip():
        added["verified_by"] = _DEFAULT_VERIFIED_BY
    if "sources" not in fm or fm.get("sources") in (None, ""):
        added["sources"] = _count_source_refs(body)
    if "last_verified" not in fm or not str(fm.get("last_verified", "")).strip():
        added["last_verified"] = _TODAY
    if "authority" not in fm or not str(fm.get("authority", "")).strip():
        added["authority"] = _DEFAULT_AUTHORITY
    return added


def _serialize_frontmatter(fm: Dict) -> str:
    """dict → YAML frontmatter 文本 (用 PyYAML, 保字段顺序, allow_unicode=True).

    用 default_flow_style=False + sort_keys=False 保留输入顺序, 不要折叠.
    """
    return yaml.safe_dump(
        fm,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
    ).rstrip("\n")


def _build_new_content(fm: Dict, body: str) -> str:
    """拼接新 markdown: ---\\n{yaml}\\n---\\n\\n{body}."""
    fm_text = _serialize_frontmatter(fm)
    return f"---\n{fm_text}\n---\n\n{body.lstrip(chr(10))}"


def _scan_one_file(file_path: str) -> Dict:
    """扫一个文件, 返回 dict.

    返回字段:
      file_path: 绝对路径
      rel_path: 相对 wiki-root
      frontmatter_existed: 原本是否有 frontmatter
      fields_added: dict (verified_by/sources/last_verified/authority 的待补值)
      sources_count: 计算出的 sources (无论是否要补)
      error: 解析错误信息 (None 表示成功)
      raw: 原始内容 (--apply 时复用避免二读)
      fm: 已有 frontmatter dict
      body: 正文部分
    """
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            raw = f.read()
    except (IOError, UnicodeDecodeError) as e:
        return {
            "file_path": file_path, "rel_path": "",
            "frontmatter_existed": False, "fields_added": {},
            "sources_count": 0, "error": f"read failed: {e}",
            "raw": "", "fm": {}, "body": "",
        }

    try:
        fm, _fm_text, body = _split_frontmatter(raw)
    except yaml.YAMLError as e:
        return {
            "file_path": file_path, "rel_path": "",
            "frontmatter_existed": True, "fields_added": {},
            "sources_count": 0, "error": f"yaml parse failed: {e}",
            "raw": raw, "fm": {}, "body": "",
        }

    fm = fm or {}
    body = body or ""
    added = _compute_added_fields(fm, body)
    sources_count = added.get("sources") or fm.get("sources") or _count_source_refs(body)

    return {
        "file_path": file_path,
        "rel_path": "",  # 上层填
        "frontmatter_existed": bool(fm),
        "fields_added": added,
        "sources_count": int(sources_count) if sources_count else 1,
        "error": None,
        "raw": raw,
        "fm": fm,
        "body": body,
    }


def _walk_wiki(wiki_root: str) -> List[str]:
    """递归找 wiki_root 下所有 .md 文件, 路径排序."""
    paths = []
    for root, _dirs, files in os.walk(wiki_root):
        for fn in files:
            if fn.endswith(".md"):
                paths.append(os.path.join(root, fn))
    paths.sort()
    return paths


def _apply_one(result: Dict) -> bool:
    """真写一个文件: 把 added 字段 merge 进 fm, 拼回去写入. 返回是否真改."""
    if result.get("error"):
        return False
    if not result["fields_added"]:
        return False
    new_fm = dict(result["fm"])
    new_fm.update(result["fields_added"])
    new_content = _build_new_content(new_fm, result["body"])
    with open(result["file_path"], "w", encoding="utf-8", newline="\n") as f:
        f.write(new_content)
    return True


def _append_audit_log(wiki_root: str, n_updated: int) -> None:
    """追加 audit 行到 wiki_root/log.md (没 log.md 创一个)."""
    log_path = os.path.join(wiki_root, "log.md")
    line = (
        f"\n## [{_TODAY}] batch frontmatter update — "
        f"{n_updated} files updated by fengniao_wiki_frontmatter_batch.py\n"
    )
    mode = "a" if os.path.isfile(log_path) else "w"
    with open(log_path, mode, encoding="utf-8") as f:
        f.write(line)


def _classify(results: List[Dict]) -> Dict[str, int]:
    """分类计数: full_add (4 字段全补) / partial (1-3 字段) / no_op (0 字段) / error."""
    counts = {"full_add_4": 0, "partial": 0, "no_op": 0, "error": 0}
    for r in results:
        if r.get("error"):
            counts["error"] += 1
            continue
        n = len(r["fields_added"])
        if n == 4:
            counts["full_add_4"] += 1
        elif n == 0:
            counts["no_op"] += 1
        else:
            counts["partial"] += 1
    return counts


def _format_report_md(results: List[Dict], wiki_root: str, counts: Dict) -> str:
    """生成 markdown 报告文本."""
    lines = [
        "# 风鸟 wiki frontmatter 批量补全 — Dry Run 报告",
        "",
        f"**生成时间**: {_TODAY}",
        f"**wiki-root**: `{wiki_root}`",
        f"**扫描文件总数**: {len(results)}",
        "",
        "## 分类汇总",
        "",
        "| 类别 | 文件数 | 含义 |",
        "|------|--------|------|",
        f"| full_add_4 | {counts['full_add_4']} | 4 个字段全部要补 (frontmatter 无 verified_by/sources/last_verified/authority 任一) |",
        f"| partial | {counts['partial']} | 部分字段已有, 只补缺失的 |",
        f"| no_op | {counts['no_op']} | 4 字段全已有, 不动 (idempotent) |",
        f"| error | {counts['error']} | YAML 解析或读取失败, 跳过 |",
        "",
        "## 逐文件预览",
        "",
        "| file | added_fields | sources_count | frontmatter_existed | error |",
        "|------|--------------|---------------|---------------------|-------|",
    ]
    for r in results:
        rel = r["rel_path"] or os.path.relpath(r["file_path"], wiki_root)
        rel = rel.replace("\\", "/")
        if r.get("error"):
            lines.append(f"| `{rel}` | - | - | - | {r['error']} |")
            continue
        added = r["fields_added"]
        added_str = ", ".join(f"{k}={v}" for k, v in added.items()) if added else "(none)"
        existed = "yes" if r["frontmatter_existed"] else "no"
        lines.append(
            f"| `{rel}` | {added_str} | {r['sources_count']} | {existed} | - |"
        )
    lines.append("")
    lines.append("## 下一步")
    lines.append("")
    lines.append("- 若预览 OK, 跑 `python scripts/fengniao_wiki_frontmatter_batch.py --apply --yes` 真改")
    lines.append("- `--apply` 会追加 audit 行到 `<wiki-root>/log.md`")
    lines.append("- 如需回滚, 用 git 撤销 (前提是 wiki 在 git 仓库内)")
    return "\n".join(lines) + "\n"


def run(wiki_root: str, apply: bool, yes: bool, out_path: str = None) -> int:
    """主流程, 返回 exit code."""
    if not os.path.isdir(wiki_root):
        print(f"[fengniao_wiki_frontmatter_batch] ERROR: wiki-root 不存在: {wiki_root}",
              file=sys.stderr)
        return 1

    paths = _walk_wiki(wiki_root)
    if not paths:
        print(f"[fengniao_wiki_frontmatter_batch] WARN: {wiki_root} 下没 .md 文件",
              file=sys.stderr)
        return 0

    results = []
    for p in paths:
        r = _scan_one_file(p)
        r["rel_path"] = os.path.relpath(p, wiki_root).replace("\\", "/")
        if r.get("error"):
            print(f"[fengniao_wiki_frontmatter_batch] WARN skip {r['rel_path']}: {r['error']}",
                  file=sys.stderr)
        results.append(r)

    counts = _classify(results)
    report = _format_report_md(results, wiki_root, counts)

    if out_path:
        os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
        with open(out_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(report)
        print(f"[fengniao_wiki_frontmatter_batch] 报告已写入 {out_path}")
    else:
        # stdout 输出 (Windows GBK 兼容: 用 utf-8 重定向写不出特殊字符也不阻塞)
        try:
            print(report)
        except UnicodeEncodeError:
            sys.stdout.buffer.write(report.encode("utf-8", errors="replace"))

    if not apply:
        print(f"\n[dry-run] 扫 {len(results)} 文件, "
              f"full_add_4={counts['full_add_4']} partial={counts['partial']} "
              f"no_op={counts['no_op']} error={counts['error']}")
        print("[dry-run] 加 --apply --yes 真改文件.")
        return 0

    # --apply 必须配 --yes
    print(f"\n[!] 该操作会改写 {len(results)} 个文件, 请确保 git 干净.", file=sys.stderr)
    if not yes:
        print("[!] 加 --yes 才真改 (跳过交互式确认).", file=sys.stderr)
        return 1

    n_updated = 0
    for r in results:
        if _apply_one(r):
            n_updated += 1
    _append_audit_log(wiki_root, n_updated)
    print(f"[apply] 共改写 {n_updated} 文件, audit 行已追加到 {wiki_root}/log.md")
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="风鸟 wiki frontmatter 批量补全 (cold-start canonical 双保险)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--wiki-root", default=_DEFAULT_WIKI_ROOT,
                        help=f"风鸟 wiki 根目录 (默认 {_DEFAULT_WIKI_ROOT})")
    parser.add_argument("--dry-run", action="store_true", default=True,
                        help="干跑, 只打印不改 (默认 True, 与 --apply 互斥)")
    parser.add_argument("--apply", action="store_true",
                        help="真改文件 (必须配 --yes)")
    parser.add_argument("--yes", action="store_true",
                        help="跳过 --apply 二次确认")
    parser.add_argument("--out", help="把 dry-run 报告写到指定 markdown 文件")
    args = parser.parse_args()

    # Windows console UTF-8 兜底
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

    return run(
        wiki_root=args.wiki_root,
        apply=args.apply,
        yes=args.yes,
        out_path=args.out,
    )


if __name__ == "__main__":
    sys.exit(main())
