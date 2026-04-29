"""啄木鸟 v2 KG 批量构建驱动 — 跨 workspace 并发 + 断点续跑.

用法:
    # 自动遍历所有 workspace-*, 已存在新鲜 KG 自动跳过
    python scripts/build_kg_all.py --all-workspaces

    # 显式指定子集
    python scripts/build_kg_all.py --workspaces 产品召回,侵权软件,对外投资

    # 强制重抽 (覆盖已有 _kg/)
    python scripts/build_kg_all.py --workspaces 产品召回 --force

    # 调并发: workspace 之间 4 并发, 单 workspace 内串行
    python scripts/build_kg_all.py --all-workspaces --workspace-concurrency 4

    # 单 workspace 内多页并发 (省时但更费 rate-limit budget)
    python scripts/build_kg_all.py --all-workspaces --page-concurrency 3

设计:
- workspace 之间用 asyncio.Semaphore 控制并发上限 (默认 3, 尊重 DeepSeek RPS)
- workspace 内可串行 (--page-concurrency=1, 默认) 或低度并发 (--page-concurrency 2-3)
- 单 workspace 失败 (异常) 不阻塞其他 workspace, 失败原因写到 build_kg_all.log
- 断点续跑: _kg/entities.json mtime ≥ wiki/ 任一 md mtime → skip (除非 --force)
- 进度: 启动时打 "扫描结果"; 每 workspace 完成打一行汇总; 结束打总表
- 兼容 windows GBK 控制台 (用 ascii 标记 [OK]/[SKIP]/[FAIL])
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# 加载 .env + sys.path
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "scripts"))

try:
    from dotenv import load_dotenv
    load_dotenv(_ROOT / ".env", override=True)
except ImportError:
    pass

# windows GBK 控制台兼容: 把 stdout 强制 utf-8 (3.7+ 支持 reconfigure)
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

# 复用 build_wiki_kg 的工具
import build_wiki_kg as bkg


def _list_all_workspaces(root: Path) -> List[Path]:
    """扫所有 workspace-* 目录 (排除 sample / 无 wiki/)."""
    out = []
    for p in sorted(root.iterdir()):
        if not p.is_dir():
            continue
        name = p.name
        if not name.startswith("workspace-"):
            continue
        if not (p / "wiki").is_dir():
            continue
        out.append(p)
    return out


def _has_business_pages(wiki_dir: Path) -> Tuple[int, int]:
    """返回 (业务页数, 总字符数). 业务页 = 非 meta 文件."""
    biz, chars = 0, 0
    for root_, dirs, files in os.walk(wiki_dir):
        dirs[:] = [d for d in dirs if d != "_kg" and not d.startswith(".")]
        for fn in files:
            if not fn.endswith(".md") or fn.startswith("."):
                continue
            if bkg.is_meta_page(fn):
                continue
            try:
                fp = os.path.join(root_, fn)
                chars += os.path.getsize(fp)
                biz += 1
            except OSError:
                continue
    return biz, chars


def _resolve_workspace_args(args, root: Path) -> List[Path]:
    """根据 --all-workspaces / --workspaces 解析出目标 workspace 列表."""
    if args.all_workspaces:
        return _list_all_workspaces(root)
    if args.workspaces:
        names = [w.strip() for w in args.workspaces.split(",") if w.strip()]
        out = []
        for n in names:
            # 容忍带不带 workspace- 前缀
            cand = (root / n) if n.startswith("workspace-") else (root / f"workspace-{n}")
            if cand.is_dir() and (cand / "wiki").is_dir():
                out.append(cand)
            else:
                print(f"[WARN] 找不到 workspace: {n} (寻 {cand})", file=sys.stderr)
        return out
    print("[ERR] 必须传 --all-workspaces 或 --workspaces W1,W2", file=sys.stderr)
    sys.exit(2)


# ============================================================
# 单 workspace 抽取 (内部串行, 多线程友好)
# ============================================================

async def _extract_pages_seq(pages: List[Tuple[str, str]], max_gleanings: int,
                             page_concurrency: int) -> Tuple[List[Dict], List[Dict], List[Dict]]:
    """串行 / 低并发抽多页. 返回 (raw_entities, raw_relations, page_metrics)."""
    raw_e: List[Dict] = []
    raw_r: List[Dict] = []
    metrics: List[Dict] = []
    sem = asyncio.Semaphore(max(1, page_concurrency))
    loop = asyncio.get_event_loop()

    async def _one(idx: int, relpath: str, content: str):
        async with sem:
            # extract_page 是 CPU+IO 阻塞 (LLM HTTP), 用 to_thread 跑
            try:
                ents, rels, m = await loop.run_in_executor(
                    None, bkg.extract_page, relpath, content, max_gleanings, True
                )
            except Exception as exc:
                m = {"relpath": relpath, "chars": len(content), "elapsed_s": 0,
                     "skipped": False, "error": str(exc)[:200],
                     "entities_raw": 0, "relations_raw": 0}
                ents, rels = [], []
            return ents, rels, m

    tasks = [_one(i, p, c) for i, (p, c) in enumerate(pages)]
    for fut in asyncio.as_completed(tasks):
        ents, rels, m = await fut
        raw_e.extend(ents)
        raw_r.extend(rels)
        metrics.append(m)
        # 进度: 每页一行
        tag = "[SKIP]" if m.get("skipped") else ("[ERR]" if m.get("error") else "[OK]")
        info = m.get("error") or f"{m.get('entities_raw',0)}E/{m.get('relations_raw',0)}R, {m.get('elapsed_s',0)}s"
        print(f"    {tag} {m.get('relpath')} ({m.get('chars',0)}字, g={m.get('gleaning_rounds','-')}) -> {info}")

    return raw_e, raw_r, metrics


async def _build_one_workspace(workspace_dir: Path, force: bool, max_gleanings: int,
                               page_concurrency: int) -> Dict[str, Any]:
    """构建单个 workspace 的 KG. 返回汇总 dict."""
    name = workspace_dir.name
    wiki_dir = workspace_dir / "wiki"
    out_dir = wiki_dir / "_kg"
    summary: Dict[str, Any] = {
        "workspace": name,
        "status": "pending",
        "biz_pages": 0,
        "entities": 0,
        "relations": 0,
        "elapsed_s": 0,
        "error": None,
        "skipped_reason": None,
    }
    biz, chars = _has_business_pages(wiki_dir)
    summary["biz_pages"] = biz
    if biz == 0:
        summary["status"] = "skipped"
        summary["skipped_reason"] = "无业务 md 页 (只有 index/log)"
        return summary

    # 断点续跑判定
    if not force and bkg.kg_is_fresh(str(out_dir), str(wiki_dir)):
        summary["status"] = "skipped"
        summary["skipped_reason"] = "KG 新鲜 (mtime 检查通过)"
        # 读取已存在 KG 的统计
        try:
            with open(out_dir / "entities.json", "r", encoding="utf-8") as f:
                summary["entities"] = len(json.load(f))
            with open(out_dir / "relations.json", "r", encoding="utf-8") as f:
                summary["relations"] = len(json.load(f))
        except OSError:
            pass
        return summary

    print(f"\n=== 开始抽 {name} ({biz} 业务页, {chars} 字) ===")
    t0 = time.time()
    pages_all = bkg.walk_wiki_md(str(wiki_dir))
    # 过滤元文件 — 抽取阶段直接跳, 不浪费 LLM 调用
    pages = [(rp, ct) for rp, ct in pages_all if not bkg.is_meta_page(rp)]
    if not pages:
        summary["status"] = "skipped"
        summary["skipped_reason"] = "过滤后无可抽页面"
        return summary

    try:
        raw_e, raw_r, metrics = await _extract_pages_seq(pages, max_gleanings, page_concurrency)
        # 去重 + 分配 id
        entities, relations = bkg.dedupe_and_assign_ids(raw_e, raw_r)

        # 写 KG
        meta = {
            "wiki_dir": str(wiki_dir),
            "pages_scanned": len(pages_all),
            "biz_pages_extracted": len(pages),
            "pages_failed": [m["relpath"] for m in metrics if m.get("error")],
            "entities_count": len(entities),
            "relations_count": len(relations),
            "by_type": {},
            "elapsed_seconds": round(time.time() - t0, 1),
            "max_gleanings": max_gleanings,
            "page_concurrency": page_concurrency,
            "built_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "builder": "build_kg_all.py",
        }
        for e in entities:
            meta["by_type"][e["type"]] = meta["by_type"].get(e["type"], 0) + 1
        bkg._write_kg_outputs(str(out_dir), entities, relations, meta)

        # 写 metrics.json (供 dashboard 用)
        metrics_doc = {
            "workspace": name,
            "built_at": meta["built_at"],
            "total_elapsed_s": meta["elapsed_seconds"],
            "page_count": len(pages),
            "page_metrics": metrics,
            "avg_per_page_s": round(sum(m.get("elapsed_s", 0) for m in metrics) / max(1, len(metrics)), 1),
        }
        with open(out_dir / "metrics.json", "w", encoding="utf-8") as f:
            json.dump(metrics_doc, f, ensure_ascii=False, indent=2)

        summary.update({
            "status": "ok",
            "entities": len(entities),
            "relations": len(relations),
            "elapsed_s": meta["elapsed_seconds"],
            "by_type": meta["by_type"],
            "failed_pages": len(meta["pages_failed"]),
        })
    except Exception as exc:
        summary["status"] = "error"
        summary["error"] = str(exc)[:300]
        summary["elapsed_s"] = round(time.time() - t0, 1)

    return summary


# ============================================================
# 跨 workspace 并发 (默认 3)
# ============================================================

async def run_all(workspaces: List[Path], force: bool, max_gleanings: int,
                  ws_concurrency: int, page_concurrency: int) -> List[Dict[str, Any]]:
    """跨 workspace 并发. workspace 之间 ws_concurrency 并发, workspace 内 page_concurrency."""
    sem = asyncio.Semaphore(max(1, ws_concurrency))

    async def _ws(ws):
        async with sem:
            return await _build_one_workspace(ws, force, max_gleanings, page_concurrency)

    return await asyncio.gather(*[_ws(w) for w in workspaces], return_exceptions=False)


def _print_table(results: List[Dict[str, Any]]) -> None:
    """打印汇总表 (ascii safe, windows GBK ok)."""
    print("\n" + "=" * 88)
    print("KG 构建汇总")
    print("=" * 88)
    hdr = f"{'workspace':<32} {'status':<8} {'biz':>4} {'ents':>5} {'rels':>5} {'time(s)':>8}  备注"
    print(hdr)
    print("-" * 88)
    total_e = total_r = 0
    total_t = 0.0
    for r in results:
        note = r.get("error") or r.get("skipped_reason") or ""
        if len(note) > 30:
            note = note[:30] + ".."
        ws = r["workspace"]
        if len(ws) > 30:
            ws = ws[:30]
        print(f"{ws:<32} {r['status']:<8} {r['biz_pages']:>4} "
              f"{r.get('entities', 0):>5} {r.get('relations', 0):>5} "
              f"{r.get('elapsed_s', 0):>8} {note}")
        if r["status"] == "ok":
            total_e += r["entities"]
            total_r += r["relations"]
            total_t += r["elapsed_s"]
    print("-" * 88)
    print(f"{'TOTAL':<32} {'':<8} {'':>4} {total_e:>5} {total_r:>5} {round(total_t, 1):>8}")
    print("=" * 88)


def main():
    parser = argparse.ArgumentParser(description="批量构建/更新所有 workspace 的 KG")
    parser.add_argument("--all-workspaces", action="store_true",
                        help="自动遍历项目根的 workspace-* 目录")
    parser.add_argument("--workspaces", default="",
                        help="逗号分隔 workspace 名 (可不带 workspace- 前缀)")
    parser.add_argument("--force", action="store_true",
                        help="强制重抽 (即使 KG 新鲜也覆盖)")
    parser.add_argument("--max-gleanings", type=int, default=2,
                        help="gleaning 轮数 (默认 2, 自适应根据页长上下浮动)")
    parser.add_argument("--workspace-concurrency", type=int, default=3,
                        help="跨 workspace 并发 (默认 3, 尊重 DeepSeek RPS)")
    parser.add_argument("--page-concurrency", type=int, default=1,
                        help="单 workspace 内并发页数 (默认 1=串行, 上限 4)")
    parser.add_argument("--dry-run", action="store_true",
                        help="只列出会被处理的 workspace, 不实际抽")
    args = parser.parse_args()

    if not args.all_workspaces and not args.workspaces:
        print("[ERR] 必须传 --all-workspaces 或 --workspaces W1,W2", file=sys.stderr)
        sys.exit(2)

    workspaces = _resolve_workspace_args(args, _ROOT)
    if not workspaces:
        print("[ERR] 没有匹配到任何 workspace", file=sys.stderr)
        sys.exit(2)

    # 上限保护
    page_concurrency = min(max(1, args.page_concurrency), 4)
    ws_concurrency = min(max(1, args.workspace_concurrency), 5)

    print(f"=== 计划处理 {len(workspaces)} 个 workspace ===")
    for w in workspaces:
        biz, chars = _has_business_pages(w / "wiki")
        kg_state = "fresh" if bkg.kg_is_fresh(str(w / "wiki" / "_kg"), str(w / "wiki")) else "stale"
        if biz == 0:
            kg_state = "no-business"
        print(f"  - {w.name}: {biz} biz pages, {chars} chars, kg={kg_state}")
    print(f"=== 配置: ws_concurrency={ws_concurrency}, page_concurrency={page_concurrency}, "
          f"force={args.force}, gleaning_max={args.max_gleanings} ===")

    if args.dry_run:
        print("[DRY-RUN] 不实际抽")
        return

    t0 = time.time()
    try:
        results = asyncio.run(run_all(
            workspaces, args.force, args.max_gleanings,
            ws_concurrency, page_concurrency,
        ))
    except KeyboardInterrupt:
        print("\n[INT] 用户中断, 已抽部分结果可能已写盘")
        sys.exit(130)

    _print_table(results)
    print(f"=== 总耗时: {round(time.time() - t0, 1)}s ===")

    # 落 build_kg_all.log (在项目根, 供 dashboard 索引)
    log_path = _ROOT / "logs" / "build_kg_all.log"
    log_path.parent.mkdir(exist_ok=True)
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] " + json.dumps(
        {"results": results, "total_s": round(time.time() - t0, 1)},
        ensure_ascii=False
    ) + "\n"
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(line)


if __name__ == "__main__":
    main()
