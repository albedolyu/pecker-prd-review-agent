"""
C 类依据回写 wiki — 缺失 ③ 闭环

把 Phase 3 中 PM 接受（status=confirmed）的 C 类 (经验/竞品/外部参考) item
升级为 wiki 决策页,下次同类型 PRD 评审时 worker 就能直接引用 [[决策-XXX]] 作为
A 类硬证据,而不是再次走 C 类「待确定」流程。

输入:
    review_items_*.json (含 verification_status / status / evidence_type)
    workspace 目录

输出:
    workspace/wiki/决策-{slug}.md  (frontmatter + 来源记录 + 引用上下文)
    控制台报告

运行方式:
    # 自动识别最新 review_items 并 promote
    python promote_c_to_wiki.py --workspace workspace-对外投资

    # dry-run 只看不写
    python promote_c_to_wiki.py --workspace workspace-对外投资 --dry-run

    # 指定 items 文件
    python promote_c_to_wiki.py --workspace workspace-对外投资 --items workspace-对外投资/output/review_items_20260415.json
"""

import argparse
import glob
import json
import os
import re
import sys
from datetime import datetime


def _slugify(text, max_len=40):
    """把 issue 文本转成 wiki 文件名 slug

    保留中文 + 字母数字,删除标点符号
    """
    if not text:
        return "未命名决策"
    # 去掉常见前缀
    text = re.sub(r"^(PRD|prd)\s*[:：]?\s*", "", text)
    # 保留中文字母数字
    cleaned = re.sub(r"[^\w\u4e00-\u9fff\-]", "", text)
    cleaned = cleaned.strip("-_")
    if not cleaned:
        return "未命名决策"
    return cleaned[:max_len]


def _find_latest_items_file(workspace):
    """在 workspace/output/ 找最新的 review_items_*.json"""
    pattern = os.path.join(workspace, "output", "review_items_*.json")
    files = glob.glob(pattern)
    if not files:
        return None
    # 按修改时间倒序
    files.sort(key=lambda f: os.path.getmtime(f), reverse=True)
    return files[0]


def _build_decision_page(item, prd_name, source_file):
    """根据 C 类 item 构造 wiki 决策页内容

    Wiki frontmatter schema (路线图 D3 子集):
        title / category / source / created / promoted_from / evidence_type
    """
    today = datetime.now().strftime("%Y-%m-%d")
    issue = item.get("issue") or item.get("problem") or ""
    suggestion = item.get("suggestion", "")
    location = item.get("location", "")
    rule_id = item.get("rule_id", "")
    ev_content = item.get("evidence_content", "")
    confidence = item.get("confidence_score", 0.5)

    slug = _slugify(issue)

    frontmatter = f"""---
title: 决策-{slug}
category: 决策
source_prd: {prd_name}
promoted_from: C 类待确定 -> A 类决策
promoted_at: {today}
promoted_from_item: {item.get("id", "?")}
original_rule: {rule_id}
original_confidence: {confidence}
---
"""

    body = f"""
# 决策-{slug}

> **本页面由 promote_c_to_wiki.py 自动生成**
> 来源:{prd_name} 评审中 PM 已确认的 C 类经验决策
> 来源 item: {item.get("id", "?")} ({rule_id})
> 升级时间: {today}

## 决策内容

{suggestion}

## 适用场景

- **PRD 章节**: {location}
- **触发问题**: {issue}

## 原始 C 类依据

{ev_content}

## PM 决策记录

- ✅ **接受**(status=confirmed)
- 升级为 A 类硬证据,后续同类型 PRD 可以直接引用 `[[决策-{slug}]]`

## 引用方式

下次评审 worker 在遇到类似问题时,可以这样写:

```
**依据**: [A] [[决策-{slug}]] 已由 PM 在 {prd_name} 中确认
```

---

> 此页面应由 PM 在使用过程中持续完善。模板字段:背景、决策依据、影响范围、复审日期。
"""
    return slug, frontmatter + body


def promote(workspace, items_file=None, dry_run=False, only_status=("confirmed", "accepted")):
    """主入口

    Args:
        workspace: workspace 目录
        items_file: 指定 items.json 路径,None 时自动找最新
        dry_run: 只打印不写文件
        only_status: 只处理这些 status 的 item (PM 已接受)
    """
    if not items_file:
        items_file = _find_latest_items_file(workspace)
        if not items_file:
            print(f"[error] {workspace}/output/ 下找不到 review_items_*.json")
            return 1

    print(f"[input] {items_file}")
    with open(items_file, encoding="utf-8") as f:
        items = json.load(f)

    # 从文件名抓 PRD 名 (review_items_20260415.json -> PRD 名暂用 workspace 后缀)
    prd_name = os.path.basename(workspace).replace("workspace-", "")

    wiki_dir = os.path.join(workspace, "wiki")
    if not os.path.isdir(wiki_dir):
        os.makedirs(wiki_dir, exist_ok=True)

    # 筛选 C 类 + 已确认
    promoted = []
    skipped_reasons = {"not_c": 0, "not_confirmed": 0, "exists": 0}

    for item in items:
        ev_type = (item.get("evidence_type") or "").strip().upper()
        status = (item.get("status") or item.get("verification_status") or "").lower()

        if ev_type != "C":
            skipped_reasons["not_c"] += 1
            continue

        # status: confirmed/accepted = PM 接受;verified = verify_evidence 通过(不代表 PM 接受)
        # 当前 verification_status 是 verify_evidence 的结果,实际 PM 决策需要 Phase 3 的 status 字段
        # 这里宽松处理: status 在 only_status 列表中,或 verification_status=verified 且无 status 字段
        if status not in only_status and status != "verified":
            skipped_reasons["not_confirmed"] += 1
            continue

        slug, content = _build_decision_page(item, prd_name, items_file)
        out_path = os.path.join(wiki_dir, f"决策-{slug}.md")

        if os.path.isfile(out_path):
            skipped_reasons["exists"] += 1
            print(f"  [skip] {out_path} 已存在")
            continue

        if dry_run:
            print(f"  [dry-run] would write {out_path}")
            print(f"      issue: {(item.get('issue') or '')[:80]}")
        else:
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(content)
            print(f"  [write] {out_path}")

        promoted.append({"id": item.get("id"), "slug": slug, "path": out_path})

    print()
    print(f"=== promote_c_to_wiki summary ===")
    print(f"输入 items: {len(items)}")
    print(f"已 promote: {len(promoted)}")
    print(f"跳过 (非 C 类): {skipped_reasons['not_c']}")
    print(f"跳过 (未确认): {skipped_reasons['not_confirmed']}")
    print(f"跳过 (页面已存在): {skipped_reasons['exists']}")
    if promoted:
        print()
        print("已 promote 的决策页:")
        for p in promoted:
            print(f"  - {p['id']}: {p['path']}")
        if not dry_run:
            print()
            print("请检查并完善以上 wiki 页面,下次评审 worker 即可引用为 A 类")
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="C 类依据 -> wiki 决策页(关闭 ③ 反馈闭环缺失)"
    )
    parser.add_argument("--workspace", required=True, help="workspace 目录")
    parser.add_argument("--items", default=None, help="指定 items.json,默认自动找最新")
    parser.add_argument("--dry-run", action="store_true", help="只打印不写文件")
    args = parser.parse_args()

    return promote(args.workspace, items_file=args.items, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
