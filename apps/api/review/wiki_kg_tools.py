"""Pecker v2 路线图步骤 7: L4 GraphRAG Phase 3 — wiki KG 检索工具.

替代 manifest 字符串匹配, worker 引用 wiki 时走 entity_id 而非 [[页面名]].

对外 API:
- load_kg(workspace) → (entities, relations) — 读 wiki/_kg/ 下 json, 缓存
- search_entity(query, top_k=5, workspace=...) → list[Entity]
- expand_neighbors(entity_id, hops=1, workspace=...) → Subgraph
- get_entity_by_alias(alias, workspace=...) → Entity | None

设计:
- 不依赖 embedding (50 个 entity 规模 keyword overlap 已经够)
- search 用 jieba 分词 + title/aliases/description 匹配 + 命中分加权
- expand_neighbors 在 relations.json 里找 source==entity_id OR target==entity_id 的 edges, 双向都算
- KG 数据按 workspace 单例缓存 (mtime 检查 → 文件改了自动 reload)
"""
from __future__ import annotations

import json
import os
import re
import threading
from typing import Any, Dict, List, Optional, Tuple

# jieba 分词 (与 evidence_verify 共用; 没装就回退到字符 n-gram)
try:
    import jieba
    jieba.setLogLevel(40)
    _JIEBA_OK = True
except ImportError:
    _JIEBA_OK = False


# ============================================================
# 数据加载 (单例 + mtime 失效)
# ============================================================

_CACHE_LOCK = threading.RLock()
# workspace 路径 → (mtime_e, mtime_r, entities, relations, by_id, alias_idx)
_CACHE: Dict[str, Tuple] = {}


def _kg_paths(workspace: str) -> Tuple[str, str]:
    """返回 (entities_json, relations_json) 路径."""
    base = os.path.join(workspace, "wiki", "_kg")
    return os.path.join(base, "entities.json"), os.path.join(base, "relations.json")


def load_kg(workspace: str) -> Tuple[List[Dict], List[Dict]]:
    """加载 KG 数据, 单例缓存. workspace 不存在/无 _kg → 返回 ([], [])."""
    if not workspace or not os.path.isdir(workspace):
        return [], []
    ents_path, rels_path = _kg_paths(workspace)
    if not (os.path.isfile(ents_path) and os.path.isfile(rels_path)):
        return [], []

    with _CACHE_LOCK:
        e_mtime = os.path.getmtime(ents_path)
        r_mtime = os.path.getmtime(rels_path)
        cached = _CACHE.get(workspace)
        if cached and cached[0] == e_mtime and cached[1] == r_mtime:
            return cached[2], cached[3]

        with open(ents_path, "r", encoding="utf-8") as f:
            entities = json.load(f)
        with open(rels_path, "r", encoding="utf-8") as f:
            relations = json.load(f)

        # 建索引: id → entity, alias → entity
        by_id = {e["id"]: e for e in entities}
        alias_idx: Dict[str, str] = {}   # alias_lower → entity_id
        for e in entities:
            alias_idx[e["title"].lower()] = e["id"]
            for a in e.get("aliases", []):
                alias_idx.setdefault(a.lower(), e["id"])

        _CACHE[workspace] = (e_mtime, r_mtime, entities, relations, by_id, alias_idx)
        return entities, relations


def _get_indices(workspace: str) -> Tuple[Dict[str, Dict], Dict[str, str]]:
    """返回 (by_id, alias_idx). 触发 load 缓存."""
    load_kg(workspace)
    cached = _CACHE.get(workspace)
    if not cached:
        return {}, {}
    return cached[4], cached[5]


# ============================================================
# 分词 (中文 + 英文 mixed)
# ============================================================

_STOP_WORDS = frozenset({
    "的", "是", "在", "有", "和", "与", "或", "需要", "应该", "可以",
    "the", "and", "for", "is", "are", "to", "of", "a", "an"
})


def _tokenize(text: str) -> set:
    """中文 jieba + 英文 word, 长度 >= 2, 去停用词. 返回 set."""
    if not text:
        return set()
    tokens = set()
    if _JIEBA_OK:
        for w in jieba.lcut(text):
            w = w.strip().lower()
            if len(w) >= 2 and w not in _STOP_WORDS:
                tokens.add(w)
    else:
        # 回退: 中文 2-gram + 英文 word
        tokens.update(t.lower() for t in re.findall(r"[\u4e00-\u9fff]{2,4}", text)
                      if t.lower() not in _STOP_WORDS)
    # 英文词单独切 (jieba 中文模式对英文支持一般)
    for w in re.findall(r"[a-zA-Z][a-zA-Z0-9_-]{2,}", text):
        wl = w.lower()
        if wl not in _STOP_WORDS:
            tokens.add(wl)
    return tokens


# ============================================================
# search_entity (keyword overlap + 字段加权)
# ============================================================

def search_entity(query: str, top_k: int = 5, workspace: Optional[str] = None) -> List[Dict[str, Any]]:
    """在 entity title/aliases/description 上做 keyword 命中匹配, 排序后返 top_k.

    评分策略 (重在 alias 命中, 直击 worker 痛点 #1):
    - title 完整子串匹配: +10
    - alias 完整子串匹配: +8 (alias 命中比 title 描述匹配更高)
    - title token overlap: +3 / token
    - alias token overlap: +2 / token
    - description token overlap: +1 / token

    Returns:
        list of dict: {id, title, type, description, aliases, source_pages, score}
    """
    if not query or not workspace:
        return []
    entities, _ = load_kg(workspace)
    if not entities:
        return []

    q_lower = query.lower()
    q_tokens = _tokenize(query)
    if not q_tokens and not q_lower:
        return []

    scored = []
    for ent in entities:
        title = ent.get("title", "")
        aliases = ent.get("aliases", []) or []
        desc = ent.get("description", "")

        score = 0.0
        # 子串匹配
        if q_lower in title.lower() or title.lower() in q_lower:
            score += 10
        for a in aliases:
            al = a.lower()
            if q_lower in al or al in q_lower:
                score += 8
                break
        # token overlap
        title_tokens = _tokenize(title)
        if title_tokens:
            score += 3 * len(q_tokens & title_tokens)
        for a in aliases:
            a_tokens = _tokenize(a)
            if a_tokens:
                score += 2 * len(q_tokens & a_tokens)
        desc_tokens = _tokenize(desc)
        if desc_tokens:
            score += 1 * len(q_tokens & desc_tokens)

        if score > 0:
            scored.append((score, ent))

    scored.sort(key=lambda x: x[0], reverse=True)
    results = []
    for score, ent in scored[:top_k]:
        out = {
            "id": ent["id"],
            "title": ent["title"],
            "type": ent["type"],
            "description": ent.get("description", ""),
            "aliases": ent.get("aliases", []),
            "source_pages": ent.get("source_pages", []),
            "score": round(score, 2),
        }
        results.append(out)
    return results


# ============================================================
# expand_neighbors (1-hop / 2-hop 子图)
# ============================================================

def expand_neighbors(entity_id: str, hops: int = 1, workspace: Optional[str] = None) -> Dict[str, Any]:
    """拓展 entity 的邻居子图.

    在 relations.json 里找 source_id==entity_id OR target_id==entity_id 的 edges (双向都算邻居).

    Args:
        entity_id: 起点 entity_id (e_xxx)
        hops: 跳数, 1 = 直接邻居, 2 = 邻居的邻居 (上限 2 防爆图)
        workspace: workspace 路径

    Returns:
        {
            "center": Entity,                          # 起点
            "entities": list[Entity],                  # 拓展到的所有 entity (含 center)
            "edges": list[{source_id, target_id, relation_type, description, weight}],
            "hops": int,
        }
        center 不存在 → entities=[], edges=[]
    """
    if not entity_id or not workspace:
        return {"center": None, "entities": [], "edges": [], "hops": hops}
    entities, relations = load_kg(workspace)
    by_id, _ = _get_indices(workspace)
    center = by_id.get(entity_id)
    if not center:
        return {"center": None, "entities": [], "edges": [], "hops": hops}

    visited = {entity_id}
    edges: List[Dict] = []
    frontier = {entity_id}
    hops = max(1, min(hops, 2))   # 上限 2 防爆

    for _ in range(hops):
        next_frontier = set()
        for rel in relations:
            src = rel.get("source_id")
            tgt = rel.get("target_id")
            if src in frontier or tgt in frontier:
                # 选另一端入下一轮
                other = tgt if src in frontier else src
                if other and other not in visited:
                    next_frontier.add(other)
                    visited.add(other)
                # edge 去重 (按 id)
                if rel not in edges:
                    edges.append(rel)
        if not next_frontier:
            break
        frontier = next_frontier

    out_entities = [by_id[eid] for eid in visited if eid in by_id]
    return {
        "center": center,
        "entities": out_entities,
        "edges": edges,
        "hops": hops,
    }


# ============================================================
# get_entity_by_alias (worker 痛点 #1 直接修复)
# ============================================================

def get_entity_by_alias(alias: str, workspace: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """按 alias 找 entity.

    解析顺序:
    1. 完全匹配 (title 或 aliases) — 大小写不敏感
    2. 模糊匹配: title/alias 包含 alias 或反向

    Returns:
        Entity dict 或 None.
    """
    if not alias or not workspace:
        return None
    entities, _ = load_kg(workspace)
    by_id, alias_idx = _get_indices(workspace)
    if not entities:
        return None

    al = alias.lower().strip()
    # 1. 完全匹配
    eid = alias_idx.get(al)
    if eid:
        return by_id.get(eid)

    # 2. 模糊匹配 — 互相包含
    for ent in entities:
        if al in ent["title"].lower() or ent["title"].lower() in al:
            return ent
        for a in ent.get("aliases", []):
            al2 = a.lower()
            if al in al2 or al2 in al:
                return ent
    return None


# ============================================================
# 辅助: 给 evidence_verify 用 — 检查 entity_id 是否存在
# ============================================================

def entity_exists(entity_id: str, workspace: Optional[str] = None) -> bool:
    """快速检查 entity_id 在 KG 中存在 — evidence_verify 走新路径用."""
    if not entity_id or not workspace:
        return False
    by_id, _ = _get_indices(workspace)
    return entity_id in by_id


def parse_entity_refs(text: str) -> List[str]:
    """从 evidence_content 中抽 [[entity:e_xxx]] 引用, 返回 entity_id 列表.

    格式: [[entity:e_023]] / [[entity:e_a1b2c3d4]]
    """
    if not text:
        return []
    return re.findall(r"\[\[entity:(e_[a-f0-9]{4,16})\]\]", text)
