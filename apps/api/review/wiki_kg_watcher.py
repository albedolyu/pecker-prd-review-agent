"""Pecker v2 KG 增量更新机制 — 检测 wiki/ 文件变更, 增量重抽.

设计:
- 状态文件: wiki/_kg/file_index.json — 记每个 md 的 (mtime, sha1, source_page)
- 比较状态文件 vs 当前 wiki/ 实际状态, 给出 (added/modified/removed) 三类页
- 重抽策略 (单页修改不触发全 KG 重抽):
  - added: 抽该页 → 增量加 entity, 关系跟已有 entity 名字 / alias 对齐
  - modified: 删除该页 source_page=该页 的所有 entity → 重抽 → 重新合入
  - removed: 删除该页 source_page=该页 的 entity + 关联 relations
- 写回 entities.json + relations.json + meta.json + file_index.json (原子写: 写 .tmp 再 rename)

API:
    detect_changes(workspace) -> {"added": [...], "modified": [...], "removed": [...]}
    apply_incremental(workspace, max_gleanings=2) -> 汇总 dict
    rebuild_index(workspace) -> 重建 file_index.json (用于初始迁移)

线程安全: 写回阶段加 _LOCK 串行 (单进程内多 worker 调用安全)
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# 引导 sys.path
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if str(_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(_ROOT / "scripts"))

import build_wiki_kg as bkg


_LOCK = threading.RLock()


# ============================================================
# file_index.json 读写
# ============================================================

def _index_path(workspace: str) -> Path:
    return Path(workspace) / "wiki" / "_kg" / "file_index.json"


def _load_index(workspace: str) -> Dict[str, Dict]:
    """读 file_index.json, 不存在返 {}."""
    p = _index_path(workspace)
    if not p.is_file():
        return {}
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def _atomic_write_json(path: Path, data: Any) -> None:
    """原子写: 写 .tmp 再 rename, 防 KG 损坏."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _save_index(workspace: str, index: Dict[str, Dict]) -> None:
    _atomic_write_json(_index_path(workspace), index)


# ============================================================
# 检测变更
# ============================================================

def _file_sha1(path: str, chunk: int = 65536) -> str:
    """计算文件 sha1 (避免读全内容到内存)."""
    h = hashlib.sha1()
    try:
        with open(path, "rb") as f:
            while True:
                buf = f.read(chunk)
                if not buf:
                    break
                h.update(buf)
    except OSError:
        return ""
    return h.hexdigest()


def _scan_wiki_state(wiki_dir: str) -> Dict[str, Dict]:
    """扫 wiki/ 当前状态: relpath → {mtime, sha1, size}."""
    state: Dict[str, Dict] = {}
    for root, dirs, files in os.walk(wiki_dir):
        dirs[:] = [d for d in dirs if d != "_kg" and not d.startswith(".")]
        for fn in files:
            if not fn.endswith(".md") or fn.startswith("."):
                continue
            fpath = os.path.join(root, fn)
            relpath = os.path.relpath(fpath, wiki_dir).replace("\\", "/")
            try:
                st = os.stat(fpath)
                state[relpath] = {
                    "mtime": st.st_mtime,
                    "size": st.st_size,
                    "sha1": _file_sha1(fpath),
                }
            except OSError:
                continue
    return state


def detect_changes(workspace: str) -> Dict[str, List[str]]:
    """对比 file_index.json 与当前 wiki/ 状态.

    Returns:
        {"added": [relpath], "modified": [relpath], "removed": [relpath], "unchanged": [...]}
        若无 file_index.json (初始状态), 所有现有 md 视为 added.
    """
    wiki_dir = str(Path(workspace) / "wiki")
    cur = _scan_wiki_state(wiki_dir)
    prev = _load_index(workspace)

    added, modified, removed, unchanged = [], [], [], []
    for rp, info in cur.items():
        if rp not in prev:
            added.append(rp)
        else:
            old = prev[rp]
            # 优先 sha1 比对; 其次 mtime + size
            if old.get("sha1") and info.get("sha1"):
                if old["sha1"] != info["sha1"]:
                    modified.append(rp)
                else:
                    unchanged.append(rp)
            else:
                if abs(old.get("mtime", 0) - info["mtime"]) > 0.5 or old.get("size") != info["size"]:
                    modified.append(rp)
                else:
                    unchanged.append(rp)
    for rp in prev:
        if rp not in cur:
            removed.append(rp)

    return {"added": added, "modified": modified, "removed": removed, "unchanged": unchanged}


# ============================================================
# 增量应用
# ============================================================

def _load_kg(workspace: str) -> Tuple[List[Dict], List[Dict]]:
    """读 wiki/_kg/entities.json + relations.json. 不存在返 ([], [])."""
    base = Path(workspace) / "wiki" / "_kg"
    e_path, r_path = base / "entities.json", base / "relations.json"
    if not e_path.is_file() or not r_path.is_file():
        return [], []
    with open(e_path, "r", encoding="utf-8") as f:
        ents = json.load(f)
    with open(r_path, "r", encoding="utf-8") as f:
        rels = json.load(f)
    return ents, rels


def _filter_out_pages(entities: List[Dict], relations: List[Dict],
                      pages: List[str]) -> Tuple[List[Dict], List[Dict]]:
    """从 entities/relations 里移除 source_page 在 pages 集合的 entity, 以及涉及该 entity 的 relations.

    保留逻辑: entity.source_pages 移除指定页后, 若仍非空, 保留 entity (其他页还引用); 否则丢弃.
    relation: 若 source_id / target_id 都还存在, 保留; 否则丢弃.
    """
    page_set = set(pages)
    kept_ents: List[Dict] = []
    for e in entities:
        sp = e.get("source_pages", [])
        new_sp = [p for p in sp if p not in page_set]
        if new_sp:
            e2 = dict(e)
            e2["source_pages"] = new_sp
            kept_ents.append(e2)
        # 否则丢弃 (entity 没了)
    kept_ids = {e["id"] for e in kept_ents}
    kept_rels = [r for r in relations
                 if r.get("source_id") in kept_ids and r.get("target_id") in kept_ids]
    return kept_ents, kept_rels


def _read_pages(wiki_dir: str, relpaths: List[str]) -> List[Tuple[str, str]]:
    """读取指定 relpath 列表对应的 md 内容. 跳过元文件."""
    out = []
    for rp in relpaths:
        if bkg.is_meta_page(rp):
            continue
        fp = os.path.join(wiki_dir, rp)
        try:
            with open(fp, "r", encoding="utf-8", errors="replace") as f:
                out.append((rp, f.read()))
        except OSError:
            continue
    return out


def _extract_pages(pages: List[Tuple[str, str]], max_gleanings: int) -> Tuple[List[Dict], List[Dict], List[Dict]]:
    """串行抽多页 (增量更新通常只抽 1-3 页, 不需要并发)."""
    raw_e: List[Dict] = []
    raw_r: List[Dict] = []
    metrics: List[Dict] = []
    for rp, content in pages:
        try:
            ents, rels, m = bkg.extract_page(rp, content, max_gleanings=max_gleanings, adaptive=True)
            raw_e.extend(ents)
            raw_r.extend(rels)
            metrics.append(m)
        except Exception as exc:
            metrics.append({"relpath": rp, "error": str(exc)[:200], "skipped": False,
                            "chars": len(content), "elapsed_s": 0,
                            "entities_raw": 0, "relations_raw": 0})
    return raw_e, raw_r, metrics


def _merge_kg(old_ents: List[Dict], old_rels: List[Dict],
              raw_new_ents: List[Dict], raw_new_rels: List[Dict]) -> Tuple[List[Dict], List[Dict]]:
    """合并旧 KG + 新抽出的 raw 实体/关系.

    策略: 把旧 KG 的 entity 转回 raw 格式 (name/type/desc/aliases/source_page) 与 new 拼起来,
    再走一遍 dedupe_and_assign_ids. 这样 entity 的 id 保持一致 (id = sha1(type:name)).
    """
    # 旧 entity → raw 格式 (一份 entity 在 source_pages 里有 N 项, 复制 N 份让 dedupe 合 source_pages)
    raw_e = list(raw_new_ents)
    for e in old_ents:
        sps = e.get("source_pages") or [""]
        for sp in sps:
            raw_e.append({
                "name": e["title"],
                "type": e["type"],
                "description": e.get("description", ""),
                "aliases": list(e.get("aliases", [])),
                "source_page": sp,
            })
    # 旧 relation → raw 格式 (用 src/tgt id 反查 name 不可行, 直接用 id 直通)
    # 走个偷懒: dedupe_and_assign_ids 重新按 src_name/tgt_name 求 id, 老 relation 在 raw_new_rels 里如果没出现就需要保留.
    # 解法: 给老 relation 用 entity id 反查 title 作 src_name/tgt_name
    name_by_id = {e["id"]: e["title"] for e in old_ents}
    raw_r = list(raw_new_rels)
    for r in old_rels:
        sn = name_by_id.get(r["source_id"])
        tn = name_by_id.get(r["target_id"])
        if not sn or not tn:
            continue
        raw_r.append({
            "source_name": sn,
            "target_name": tn,
            "relation_type": r["relation_type"],
            "description": r.get("description", ""),
            "weight": r.get("weight", 5),
        })
    return bkg.dedupe_and_assign_ids(raw_e, raw_r)


def apply_incremental(workspace: str, max_gleanings: int = 2,
                      dry_run: bool = False) -> Dict[str, Any]:
    """对单个 workspace 跑增量更新.

    流程:
        1. detect_changes 找出 added/modified/removed
        2. 没变更 → 直接返
        3. 有变更:
           - 加载旧 KG
           - 对 modified + removed 的页, 从旧 KG 移除其 source_page 所有 entity/关系
           - 抽 added + modified 页
           - 合并 + 重新 dedupe
           - 写回 (原子)
           - 更新 file_index.json
    """
    workspace_dir = Path(workspace)
    wiki_dir = workspace_dir / "wiki"
    if not wiki_dir.is_dir():
        return {"workspace": workspace, "status": "error", "error": f"wiki/ 不存在: {wiki_dir}"}

    with _LOCK:
        changes = detect_changes(str(workspace_dir))
        n_added = len(changes["added"])
        n_mod = len(changes["modified"])
        n_rm = len(changes["removed"])
        if n_added + n_mod + n_rm == 0:
            return {
                "workspace": workspace_dir.name,
                "status": "no_change",
                "added": 0, "modified": 0, "removed": 0,
            }

        if dry_run:
            return {
                "workspace": workspace_dir.name,
                "status": "dry_run",
                "added": n_added, "modified": n_mod, "removed": n_rm,
                "added_pages": changes["added"][:20],
                "modified_pages": changes["modified"][:20],
                "removed_pages": changes["removed"][:20],
            }

        t0 = time.time()
        # 1. 加载旧 KG
        old_ents, old_rels = _load_kg(str(workspace_dir))

        # 2. 移除 modified + removed 页的旧贡献
        pages_to_drop = list(set(changes["modified"]) | set(changes["removed"]))
        if pages_to_drop:
            kept_ents, kept_rels = _filter_out_pages(old_ents, old_rels, pages_to_drop)
        else:
            kept_ents, kept_rels = old_ents, old_rels

        # 3. 抽 added + modified
        pages_to_extract = changes["added"] + changes["modified"]
        page_inputs = _read_pages(str(wiki_dir), pages_to_extract)
        raw_new_e, raw_new_r, metrics = _extract_pages(page_inputs, max_gleanings)

        # 4. 合并 + 重新分配 id (kept 转 raw + new 一起跑 dedupe)
        if raw_new_e or raw_new_r:
            new_ents, new_rels = _merge_kg(kept_ents, kept_rels, raw_new_e, raw_new_r)
        else:
            # 仅 removed, 没有重抽 → 直接用 kept
            new_ents, new_rels = kept_ents, kept_rels

        # 5. 写回
        kg_dir = wiki_dir / "_kg"
        _atomic_write_json(kg_dir / "entities.json", new_ents)
        _atomic_write_json(kg_dir / "relations.json", new_rels)
        meta = {
            "wiki_dir": str(wiki_dir),
            "entities_count": len(new_ents),
            "relations_count": len(new_rels),
            "by_type": {},
            "incremental": True,
            "added": n_added, "modified": n_mod, "removed": n_rm,
            "elapsed_seconds": round(time.time() - t0, 1),
            "max_gleanings": max_gleanings,
            "built_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "builder": "wiki_kg_watcher.apply_incremental",
        }
        for e in new_ents:
            meta["by_type"][e["type"]] = meta["by_type"].get(e["type"], 0) + 1
        _atomic_write_json(kg_dir / "meta.json", meta)

        # 6. 更新 file_index
        cur_state = _scan_wiki_state(str(wiki_dir))
        _save_index(str(workspace_dir), cur_state)

        return {
            "workspace": workspace_dir.name,
            "status": "ok",
            "added": n_added, "modified": n_mod, "removed": n_rm,
            "entities": len(new_ents),
            "relations": len(new_rels),
            "elapsed_seconds": meta["elapsed_seconds"],
            "page_metrics": metrics,
        }


def rebuild_index(workspace: str) -> Dict[str, Any]:
    """重建 file_index.json (初次迁移到增量机制时用).

    通常在 build_kg_all 跑完后调一次, 之后增量机制就能正常 detect_changes.
    """
    wiki_dir = Path(workspace) / "wiki"
    if not wiki_dir.is_dir():
        return {"status": "error", "error": "wiki/ 不存在"}
    cur_state = _scan_wiki_state(str(wiki_dir))
    _save_index(str(Path(workspace)), cur_state)
    return {
        "status": "ok",
        "workspace": Path(workspace).name,
        "indexed_files": len(cur_state),
    }
