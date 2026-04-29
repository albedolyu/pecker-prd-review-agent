"""啄木鸟 v2 KG 增量更新 CLI 入口.

调 review/wiki_kg_watcher.py 的 detect_changes / apply_incremental, 单 workspace 增量重抽.

用法:
    # 单 workspace 增量
    python scripts/incremental_kg_update.py --workspace 产品召回

    # 多 workspace
    python scripts/incremental_kg_update.py --workspaces 产品召回,侵权软件

    # 所有 workspace
    python scripts/incremental_kg_update.py --all

    # 仅查变更 (不抽)
    python scripts/incremental_kg_update.py --workspace 产品召回 --dry-run

    # 重建 file_index.json (从 build_kg_all 跑完的全量 KG 迁移到增量机制)
    python scripts/incremental_kg_update.py --workspace 产品召回 --rebuild-index

设计:
- 默认串行处理多 workspace (增量量小, 不需要并发)
- 单 workspace 增量内部已串行 (1-3 页通常)
- 退出码: 0 ok / 1 部分失败 / 2 配置错
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import List

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "scripts"))

# windows GBK 兼容
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

try:
    from dotenv import load_dotenv
    load_dotenv(_ROOT / ".env", override=True)
except ImportError:
    pass

from review import wiki_kg_watcher as wkw


def _resolve_workspaces(args, root: Path) -> List[Path]:
    if args.all:
        out = []
        for p in sorted(root.iterdir()):
            if p.is_dir() and p.name.startswith("workspace-") and (p / "wiki").is_dir():
                out.append(p)
        return out
    names_raw = args.workspaces or args.workspace
    if not names_raw:
        print("[ERR] 必须传 --workspace / --workspaces / --all", file=sys.stderr)
        sys.exit(2)
    names = [n.strip() for n in names_raw.split(",") if n.strip()]
    out = []
    for n in names:
        cand = (root / n) if n.startswith("workspace-") else (root / f"workspace-{n}")
        if cand.is_dir() and (cand / "wiki").is_dir():
            out.append(cand)
        else:
            print(f"[WARN] 找不到 workspace: {n} (寻 {cand})", file=sys.stderr)
    return out


def main():
    parser = argparse.ArgumentParser(description="增量更新 wiki KG")
    parser.add_argument("--workspace", default="", help="单个 workspace 名 (含或不含 workspace- 前缀)")
    parser.add_argument("--workspaces", default="", help="逗号分隔多 workspace")
    parser.add_argument("--all", action="store_true", help="全部 workspace")
    parser.add_argument("--max-gleanings", type=int, default=2)
    parser.add_argument("--dry-run", action="store_true", help="只查变更不抽")
    parser.add_argument("--rebuild-index", action="store_true",
                        help="重建 file_index.json (从全量 KG 迁移用)")
    args = parser.parse_args()

    workspaces = _resolve_workspaces(args, _ROOT)
    if not workspaces:
        print("[ERR] 没有匹配到 workspace", file=sys.stderr)
        sys.exit(2)

    print(f"=== 处理 {len(workspaces)} 个 workspace ===")
    results = []
    t0 = time.time()
    for ws in workspaces:
        ws_name = ws.name
        if args.rebuild_index:
            r = wkw.rebuild_index(str(ws))
            print(f"[{ws_name}] rebuild_index: {r}")
            results.append(r)
            continue
        # detect 先打印
        changes = wkw.detect_changes(str(ws))
        n_a, n_m, n_r = len(changes["added"]), len(changes["modified"]), len(changes["removed"])
        print(f"\n[{ws_name}] +{n_a} added / ~{n_m} modified / -{n_r} removed")
        if n_a + n_m + n_r == 0:
            print(f"  无变更, 跳过")
            results.append({"workspace": ws_name, "status": "no_change"})
            continue
        if changes["added"]:
            print(f"  added: {changes['added'][:10]}{'...' if len(changes['added']) > 10 else ''}")
        if changes["modified"]:
            print(f"  modified: {changes['modified'][:10]}{'...' if len(changes['modified']) > 10 else ''}")
        if changes["removed"]:
            print(f"  removed: {changes['removed'][:10]}{'...' if len(changes['removed']) > 10 else ''}")

        if args.dry_run:
            results.append({
                "workspace": ws_name, "status": "dry_run",
                "added": n_a, "modified": n_m, "removed": n_r,
            })
            continue

        # 实际跑
        try:
            r = wkw.apply_incremental(str(ws), max_gleanings=args.max_gleanings, dry_run=False)
            print(f"  -> {r['status']}: {r.get('entities', 0)} entities, "
                  f"{r.get('relations', 0)} relations, {r.get('elapsed_seconds', 0)}s")
            results.append(r)
        except Exception as exc:
            err = {"workspace": ws_name, "status": "error", "error": str(exc)[:200]}
            print(f"  [ERR] {exc}")
            results.append(err)

    print(f"\n=== 总耗时 {round(time.time() - t0, 1)}s ===")
    # exit code
    fail = sum(1 for r in results if r.get("status") == "error")
    sys.exit(1 if fail else 0)


if __name__ == "__main__":
    main()
