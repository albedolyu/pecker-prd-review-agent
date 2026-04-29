"""啄木鸟 v2 路线图步骤 7 验证 demo: 演示 search_entity + expand_neighbors.

跑法:
    python scripts/demo_kg_query.py
    python scripts/demo_kg_query.py --query "字段映射规范"
    python scripts/demo_kg_query.py --workspace workspace-劳动仲裁 --query "脱敏"

验证目标:
1. 直击 worker 痛点 #1 — alias 不一致问题:
   老路径: [[规范-字段映射]] 字符串匹配 vs [[字段映射规范]] (worker 写法) → 命中失败
   新路径: search_entity("字段映射规范") → 命中 alias 列表 → 修复

2. 1-hop 邻居拓展能否做跨 wiki 推理:
   "PRD 引用字段 X, X 在表 Y 不存在" — 通过 expand_neighbors(X, hops=1) 看到 X 是否真在 Y 里
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from review.wiki_kg_tools import (
    expand_neighbors,
    get_entity_by_alias,
    load_kg,
    search_entity,
)


def _print_entity(ent: dict, indent: str = "  "):
    aliases = ent.get("aliases", [])
    alias_str = f" 别名={aliases}" if aliases else ""
    desc = ent.get("description", "")
    score = f" score={ent.get('score')}" if "score" in ent else ""
    print(f"{indent}[{ent['type']}] {ent['title']} (id={ent['id']}){score}")
    print(f"{indent}  {desc[:80]}{alias_str}")


def demo_search(workspace: str, query: str):
    print(f"\n=== search_entity('{query}') top-5 ===")
    results = search_entity(query, top_k=5, workspace=workspace)
    if not results:
        print("  (无命中)")
        return None
    for ent in results:
        _print_entity(ent)
    return results[0] if results else None


def demo_neighbors(workspace: str, entity_id: str, hops: int = 1):
    print(f"\n=== expand_neighbors('{entity_id}', hops={hops}) ===")
    sub = expand_neighbors(entity_id, hops=hops, workspace=workspace)
    center = sub.get("center")
    if not center:
        print(f"  (entity_id={entity_id} 不存在)")
        return
    print(f"  中心实体: [{center['type']}] {center['title']}")
    print(f"  邻居 entities ({len(sub['entities'])} 个):")
    for ent in sub["entities"]:
        if ent["id"] == entity_id:
            continue
        _print_entity(ent, indent="    ")
    print(f"  邻居 edges ({len(sub['edges'])} 条):")
    for edge in sub["edges"]:
        print(f"    {edge['source_id']} --[{edge['relation_type']} w={edge['weight']}]--> {edge['target_id']}")
        if edge.get("description"):
            print(f"      desc: {edge['description'][:80]}")


def demo_alias_resolution(workspace: str):
    """直击 worker 痛点 #1: 老 [[规范-字段映射]] 字符串匹配 vs 新 alias resolution."""
    print("\n=== Worker 痛点 #1: alias 不一致问题修复演示 ===")
    test_aliases = ["字段映射", "规范-字段映射", "字段来源", "脱敏", "公告脱敏"]
    print(f"  测试输入 (worker 可能写出的不同表达):")
    for alias in test_aliases:
        ent = get_entity_by_alias(alias, workspace=workspace)
        if ent:
            print(f"    '{alias}' -> [{ent['type']}] {ent['title']} (id={ent['id']})")
        else:
            print(f"    '{alias}' -> (未命中)")


def demo_overall_stats(workspace: str):
    entities, relations = load_kg(workspace)
    print(f"\n=== KG 总览 ===")
    print(f"  entities: {len(entities)}")
    print(f"  relations: {len(relations)}")
    by_type = {}
    for e in entities:
        by_type[e["type"]] = by_type.get(e["type"], 0) + 1
    print(f"  by_type: {by_type}")
    aliased = [e for e in entities if e.get("aliases")]
    print(f"  含 aliases 的 entity: {len(aliased)}/{len(entities)}")


def main():
    parser = argparse.ArgumentParser(description="演示 wiki KG search + neighbor expansion")
    parser.add_argument("--workspace", default="workspace-劳动仲裁")
    parser.add_argument("--query", default="字段映射规范",
                        help="搜的关键词 (默认 '字段映射规范' 直击 worker 痛点 #1)")
    parser.add_argument("--hops", type=int, default=1, choices=[1, 2])
    args = parser.parse_args()

    workspace_dir = _ROOT / args.workspace
    if not workspace_dir.is_dir():
        print(f"✗ workspace 不存在: {workspace_dir}", file=sys.stderr)
        sys.exit(2)
    workspace = str(workspace_dir)

    demo_overall_stats(workspace)
    top_ent = demo_search(workspace, args.query)
    if top_ent:
        demo_neighbors(workspace, top_ent["id"], hops=args.hops)
    demo_alias_resolution(workspace)
    print()


if __name__ == "__main__":
    main()
