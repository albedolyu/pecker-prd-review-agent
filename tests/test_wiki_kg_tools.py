"""单元测试: review/wiki_kg_tools.py — 不依赖 LLM, 用 fixture KG 数据."""
from __future__ import annotations

import json
import os

import pytest

from review.wiki_kg_tools import (
    entity_exists,
    expand_neighbors,
    get_entity_by_alias,
    load_kg,
    parse_entity_refs,
    search_entity,
)


# ============================================================
# Fixtures: 构造一个迷你 KG 写到 tmp workspace
# ============================================================

_FIXTURE_ENTITIES = [
    {
        "id": "e_aaaaaaaa",
        "title": "字段映射规范",
        "type": "spec_doc",
        "description": "规定 PRD 字段必须标 source_table 来源",
        "aliases": ["规范-字段映射", "字段来源规范"],
        "source_pages": ["规范-字段映射.md"],
    },
    {
        "id": "e_bbbbbbbb",
        "title": "ds_risk_labour_arbitration",
        "type": "data_table",
        "description": "劳动仲裁主表",
        "aliases": ["劳动仲裁主表"],
        "source_pages": ["约束-ds_risk_labour_arbitration.md"],
    },
    {
        "id": "e_cccccccc",
        "title": "ds_risk_labour_arbitration.title",
        "type": "field",
        "description": "公告标题字段, varchar(500)",
        "aliases": [],
        "source_pages": ["约束-ds_risk_labour_arbitration.md"],
    },
    {
        "id": "e_dddddddd",
        "title": "脱敏规则",
        "type": "masking_rule",
        "description": "对自然人姓名/身份证脱敏",
        "aliases": ["数据脱敏", "隐私脱敏"],
        "source_pages": ["概念-脱敏规则.md"],
    },
    {
        "id": "e_eeeeeeee",
        "title": "loading 状态",
        "type": "ui_state",
        "description": "数据加载中的 UI 状态",
        "aliases": ["加载中"],
        "source_pages": ["决策-UI四态规范.md"],
    },
]

_FIXTURE_RELATIONS = [
    {
        "id": "r_11111111",
        "source_id": "e_bbbbbbbb",
        "target_id": "e_cccccccc",
        "relation_type": "包含字段",
        "description": "主表的标题列",
        "weight": 9,
    },
    {
        "id": "r_22222222",
        "source_id": "e_bbbbbbbb",
        "target_id": "e_dddddddd",
        "relation_type": "脱敏",
        "description": "主表中的自然人字段需走脱敏",
        "weight": 7,
    },
    {
        "id": "r_33333333",
        "source_id": "e_aaaaaaaa",
        "target_id": "e_bbbbbbbb",
        "relation_type": "约束",
        "description": "字段映射规范约束主表的字段定义",
        "weight": 6,
    },
]


@pytest.fixture
def kg_workspace(tmp_path):
    """在 tmp workspace/wiki/_kg/ 写 entities.json + relations.json."""
    ws = tmp_path / "ws_kg_fixture"
    kg_dir = ws / "wiki" / "_kg"
    kg_dir.mkdir(parents=True)
    with open(kg_dir / "entities.json", "w", encoding="utf-8") as f:
        json.dump(_FIXTURE_ENTITIES, f, ensure_ascii=False)
    with open(kg_dir / "relations.json", "w", encoding="utf-8") as f:
        json.dump(_FIXTURE_RELATIONS, f, ensure_ascii=False)
    return str(ws)


# ============================================================
# load_kg
# ============================================================

def test_load_kg_returns_entities_and_relations(kg_workspace):
    ents, rels = load_kg(kg_workspace)
    assert len(ents) == len(_FIXTURE_ENTITIES)
    assert len(rels) == len(_FIXTURE_RELATIONS)


def test_load_kg_missing_workspace_returns_empty():
    ents, rels = load_kg("/nonexistent/workspace")
    assert ents == [] and rels == []


def test_load_kg_no_kg_dir_returns_empty(tmp_path):
    ws = tmp_path / "ws_no_kg"
    ws.mkdir()
    ents, rels = load_kg(str(ws))
    assert ents == [] and rels == []


# ============================================================
# search_entity — 直击 worker 痛点 #1
# ============================================================

def test_search_entity_finds_by_alias(kg_workspace):
    """worker 痛点 #1 修复: alias 不一致也能命中."""
    # 用户搜 "字段映射规范" — 应命中 e_aaaaaaaa (含此 title)
    results = search_entity("字段映射规范", top_k=3, workspace=kg_workspace)
    assert results, "应至少有一条命中"
    assert results[0]["id"] == "e_aaaaaaaa"


def test_search_entity_alias_resolves_inverse(kg_workspace):
    """搜 alias 也命中 (老 [[规范-字段映射]] 字符串匹配会 miss)."""
    results = search_entity("规范-字段映射", top_k=3, workspace=kg_workspace)
    assert results
    assert results[0]["id"] == "e_aaaaaaaa", "alias 命中比 manifest 字符串匹配更稳"


def test_search_entity_top_k_respected(kg_workspace):
    results = search_entity("脱敏", top_k=2, workspace=kg_workspace)
    assert len(results) <= 2


def test_search_entity_returns_score(kg_workspace):
    results = search_entity("脱敏规则", top_k=5, workspace=kg_workspace)
    assert results
    assert "score" in results[0]
    assert results[0]["score"] > 0


def test_search_entity_no_match_returns_empty(kg_workspace):
    results = search_entity("一个完全不存在的关键词随机哈哈哈", top_k=3, workspace=kg_workspace)
    assert results == []


def test_search_entity_empty_query_returns_empty(kg_workspace):
    assert search_entity("", workspace=kg_workspace) == []


# ============================================================
# expand_neighbors
# ============================================================

def test_expand_neighbors_one_hop(kg_workspace):
    """主表 1-hop: 应拿到 .title 字段 + 脱敏规则 + 字段映射规范."""
    sub = expand_neighbors("e_bbbbbbbb", hops=1, workspace=kg_workspace)
    assert sub["center"]["id"] == "e_bbbbbbbb"
    neighbor_ids = {e["id"] for e in sub["entities"] if e["id"] != "e_bbbbbbbb"}
    # 主表 → 字段 (双向都算邻居), 主表 → 脱敏, 字段映射规范 → 主表
    assert neighbor_ids == {"e_cccccccc", "e_dddddddd", "e_aaaaaaaa"}, \
        f"主表应该有 3 个 1-hop 邻居 (含双向), 实际 {neighbor_ids}"


def test_expand_neighbors_includes_edges(kg_workspace):
    sub = expand_neighbors("e_bbbbbbbb", hops=1, workspace=kg_workspace)
    assert len(sub["edges"]) == 3   # fixture 中 e_bbbbbbbb 关联 3 条边


def test_expand_neighbors_two_hops(kg_workspace):
    """字段映射规范 2-hop: 经主表到字段 / 脱敏."""
    sub = expand_neighbors("e_aaaaaaaa", hops=2, workspace=kg_workspace)
    neighbor_ids = {e["id"] for e in sub["entities"]}
    # 1-hop: 主表; 2-hop: 字段 + 脱敏
    assert "e_bbbbbbbb" in neighbor_ids
    assert "e_cccccccc" in neighbor_ids
    assert "e_dddddddd" in neighbor_ids


def test_expand_neighbors_unknown_id(kg_workspace):
    sub = expand_neighbors("e_99999999", hops=1, workspace=kg_workspace)
    assert sub["center"] is None
    assert sub["entities"] == []
    assert sub["edges"] == []


def test_expand_neighbors_hops_capped_at_2(kg_workspace):
    """hops > 2 应被截断到 2 (防爆图)."""
    sub = expand_neighbors("e_aaaaaaaa", hops=99, workspace=kg_workspace)
    assert sub["hops"] == 2


# ============================================================
# get_entity_by_alias
# ============================================================

def test_get_entity_by_alias_exact_title(kg_workspace):
    ent = get_entity_by_alias("脱敏规则", workspace=kg_workspace)
    assert ent and ent["id"] == "e_dddddddd"


def test_get_entity_by_alias_alias_list(kg_workspace):
    ent = get_entity_by_alias("数据脱敏", workspace=kg_workspace)
    assert ent and ent["id"] == "e_dddddddd"


def test_get_entity_by_alias_case_insensitive(kg_workspace):
    ent = get_entity_by_alias("DS_RISK_LABOUR_ARBITRATION", workspace=kg_workspace)
    assert ent and ent["id"] == "e_bbbbbbbb"


def test_get_entity_by_alias_fuzzy_substring(kg_workspace):
    """模糊匹配: 输入是 alias 子串."""
    ent = get_entity_by_alias("字段来源", workspace=kg_workspace)
    assert ent and ent["id"] == "e_aaaaaaaa"


def test_get_entity_by_alias_no_match(kg_workspace):
    assert get_entity_by_alias("完全没这个词abcxyz123", workspace=kg_workspace) is None


# ============================================================
# entity_exists + parse_entity_refs (给 evidence_verify 用)
# ============================================================

def test_entity_exists_known(kg_workspace):
    assert entity_exists("e_aaaaaaaa", workspace=kg_workspace) is True


def test_entity_exists_unknown(kg_workspace):
    assert entity_exists("e_unknown", workspace=kg_workspace) is False


def test_parse_entity_refs_single():
    text = "**依据**: [A] [[entity:e_a1b2c3d4]] (字段映射规范)"
    assert parse_entity_refs(text) == ["e_a1b2c3d4"]


def test_parse_entity_refs_multiple():
    text = "[[entity:e_aaaaaaaa]] 和 [[entity:e_bbbbbbbb]]"
    assert parse_entity_refs(text) == ["e_aaaaaaaa", "e_bbbbbbbb"]


def test_parse_entity_refs_mixed_with_old_format():
    """新老引用混用: 只抽 entity: 形式, [[页面名]] 不在结果里."""
    text = "[[entity:e_aaaaaaaa]] 与 [[约束-接口命名规范]]"
    assert parse_entity_refs(text) == ["e_aaaaaaaa"]


def test_parse_entity_refs_no_match():
    text = "**依据**: [A] [[约束-接口命名规范]] 无 entity 引用"
    assert parse_entity_refs(text) == []


# ============================================================
# 缓存失效: 改文件后能 reload (mtime 检查)
# ============================================================

def test_load_kg_cache_invalidates_on_mtime_change(kg_workspace, tmp_path):
    """改 entities.json 后 load_kg 应返回新数据."""
    import time
    # 第一次加载
    ents1, _ = load_kg(kg_workspace)
    n1 = len(ents1)
    # 写入新 entity, 等 1 秒确保 mtime 变化
    time.sleep(1.1)
    new_entities = list(_FIXTURE_ENTITIES) + [{
        "id": "e_ffffffff",
        "title": "新加的",
        "type": "page_concept",
        "description": "测试 reload",
        "aliases": [],
        "source_pages": [],
    }]
    ents_path = os.path.join(kg_workspace, "wiki", "_kg", "entities.json")
    with open(ents_path, "w", encoding="utf-8") as f:
        json.dump(new_entities, f, ensure_ascii=False)
    ents2, _ = load_kg(kg_workspace)
    assert len(ents2) == n1 + 1
