"""
P1 记忆迁移脚本 — 把老 JSON 记忆迁到 wiki markdown 页面

老格式: workspace/output/.review_memory/*.json
新格式: workspace/wiki/{前缀}-{title}.md (带 memory/* tag)

使用:
    # 迁移单个 workspace
    python migrate_memory_to_wiki.py --workspace workspace-对外投资

    # 迁移所有 workspace-* 目录
    python migrate_memory_to_wiki.py --all

    # dry-run 只打印会做什么,不实际写
    python migrate_memory_to_wiki.py --workspace workspace-对外投资 --dry-run

    # 迁移后删除老 JSON(谨慎)
    python migrate_memory_to_wiki.py --workspace workspace-对外投资 --delete-old
"""

import argparse
import glob
import json
import os
import re
import sys
from datetime import datetime

import io
if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from review_memory import (
    TYPE_TO_WIKI_PREFIX,
    _safe_title,
    _memory_hash,
    _collect_wiki_hashes,
    _normalize_content,
)


def migrate_workspace(workspace, dry_run=False, delete_old=False):
    """迁移单个 workspace 的记忆

    Returns: dict 统计信息
    """
    mem_dir = os.path.join(workspace, "output", ".review_memory")
    wiki_path = os.path.join(workspace, "wiki")

    if not os.path.isdir(mem_dir):
        return {"workspace": workspace, "status": "no_mem_dir", "migrated": 0}
    if not os.path.isdir(wiki_path):
        return {"workspace": workspace, "status": "no_wiki_dir", "migrated": 0}

    # 已存在的 wiki 记忆 hash(去重)
    existing_hashes = _collect_wiki_hashes(wiki_path)

    json_files = sorted(glob.glob(os.path.join(mem_dir, "*.json")))
    if not json_files:
        return {"workspace": workspace, "status": "empty", "migrated": 0}

    migrated = 0
    skipped_dup = 0
    failed = 0
    deleted = 0

    try:
        from kakapo_dream import _infer_extended_frontmatter
    except Exception:
        def _infer_extended_frontmatter(fname):
            return {"title": fname, "scope": "workspace", "category": "misc"}

    for jf in json_files:
        try:
            with open(jf, "r", encoding="utf-8") as f:
                mem = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            print(f"  [SKIP] 解析失败 {os.path.basename(jf)}: {e}")
            failed += 1
            continue

        mtype = mem.get("type", "unknown")
        title = mem.get("title", "untitled")
        content = mem.get("content", "")
        if not content:
            continue

        # 重新算 hash(因为老 JSON 的 content_hash 字段可能缺失)
        h = mem.get("content_hash") or _memory_hash(mtype, content)

        if h in existing_hashes:
            skipped_dup += 1
            if dry_run:
                print(f"  [DUP] {os.path.basename(jf)} (已存在 wiki 页)")
            # 即使 hash 匹配也走 delete-old 分支:wiki 已有此条,老 JSON 是冗余
            elif delete_old:
                try:
                    os.remove(jf)
                    deleted += 1
                    print(f"  [DEL DUP] {os.path.basename(jf)} (wiki 已有同内容页)")
                except OSError as e:
                    print(f"  [FAIL DEL] {os.path.basename(jf)}: {e}")
            continue

        prefix = TYPE_TO_WIKI_PREFIX.get(mtype, "概念-")
        safe_t = _safe_title(title)
        fname = f"{prefix}{safe_t}.md"
        fpath = os.path.join(wiki_path, fname)

        if os.path.exists(fpath):
            fname = f"{prefix}{safe_t}-{h[:8]}.md"
            fpath = os.path.join(wiki_path, fname)

        ext = _infer_extended_frontmatter(fname)

        extracted_at = mem.get("extracted_at", "")
        created_date = extracted_at[:10] if extracted_at else datetime.now().strftime("%Y-%m-%d")
        today = datetime.now().strftime("%Y-%m-%d")

        page = (
            f"---\n"
            f"title: {ext['title']}\n"
            f"source: 啄木鸟评审提取(迁移自 JSON)\n"
            f"created: {created_date}\n"
            f"updated: {today}\n"
            f"tags: [memory/{mtype}, extracted/auto, migrated]\n"
            f"sources: 1\n"
            f"scope: {ext['scope']}\n"
            f"category: {ext['category']}\n"
            f"extracted_from: {mem.get('prd_name', '')}\n"
            f"extracted_reviewer: {mem.get('reviewer', '')}\n"
            f"content_hash: {h}\n"
            f"---\n\n"
            f"# {title}\n\n"
            f"{content}\n\n"
            f"> 本页面从 `{os.path.basename(jf)}` 迁移而来({today})\n"
        )

        if dry_run:
            print(f"  [NEW] {fname}")
            migrated += 1
            existing_hashes.add(h)
            continue

        try:
            with open(fpath, "w", encoding="utf-8") as f:
                f.write(page)
            existing_hashes.add(h)
            migrated += 1
            if delete_old:
                os.remove(jf)
                deleted += 1
        except OSError as e:
            print(f"  [FAIL] 写 {fname}: {e}")
            failed += 1

    return {
        "workspace": workspace,
        "status": "ok",
        "total_json": len(json_files),
        "migrated": migrated,
        "skipped_dup": skipped_dup,
        "failed": failed,
        "deleted_old": deleted,
    }


def main():
    parser = argparse.ArgumentParser(description="迁移 .review_memory JSON → wiki markdown")
    parser.add_argument("--workspace", help="单个 workspace 路径")
    parser.add_argument("--all", action="store_true", help="迁移所有 workspace-* 目录")
    parser.add_argument("--dry-run", action="store_true", help="只打印,不实际写")
    parser.add_argument("--delete-old", action="store_true", help="迁移成功后删除老 JSON(谨慎)")
    args = parser.parse_args()

    if not args.workspace and not args.all:
        parser.error("必须指定 --workspace 或 --all")

    if args.all:
        workspaces = sorted(glob.glob("workspace-*"))
    else:
        workspaces = [args.workspace]

    print(f"准备迁移 {len(workspaces)} 个 workspace" + (" (DRY RUN)" if args.dry_run else ""))
    if args.delete_old and not args.dry_run:
        print("⚠ 迁移成功后会删除老 JSON")

    total_migrated = 0
    total_skipped = 0
    for ws in workspaces:
        print(f"\n=== {ws} ===")
        result = migrate_workspace(ws, dry_run=args.dry_run, delete_old=args.delete_old)
        if result["status"] == "ok":
            print(f"  {result['total_json']} JSON → 迁移 {result['migrated']} 条"
                  f",跳过 {result['skipped_dup']} 重复,失败 {result['failed']}"
                  + (f",删除老文件 {result['deleted_old']}" if args.delete_old else ""))
            total_migrated += result["migrated"]
            total_skipped += result["skipped_dup"]
        else:
            print(f"  {result['status']}")

    print(f"\n完成: 共迁移 {total_migrated} 条,跳过 {total_skipped} 条重复")


if __name__ == "__main__":
    sys.exit(main() or 0)
