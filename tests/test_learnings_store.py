"""信鸽 v2 LearningsStore 单元测试."""
from __future__ import annotations

import json
import os
import shutil
import tempfile

import pytest

from review.learnings_store import (
    Learning,
    LearningsStore,
    SCOPES,
    find_relevant_learnings,
)


@pytest.fixture
def tmp_workspace():
    d = tempfile.mkdtemp(prefix="learnings_test_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


# ============================================================
# Learning dataclass
# ============================================================

def test_learning_from_dict_full():
    data = {
        "id": "abc12345",
        "trigger_pattern": "PRD 涉及收藏",
        "instruction": "上限 10 条",
        "scope": "team_local",
        "source_finding_id": "R-001",
        "reviewer": "潘驰",
        "created_at": "2026-04-28T10:00:00",
        "last_used": None,
        "usage_count": 3,
        "related_rule_ids": ["RC-005"],
        "dim_keys": ["ai_coding"],
    }
    learning = Learning.from_dict(data)
    assert learning.id == "abc12345"
    assert learning.usage_count == 3
    assert learning.dim_keys == ["ai_coding"]


def test_learning_from_dict_missing_fields():
    """yaml 缺字段不应抛, 走默认值兜底."""
    data = {"id": "x", "trigger_pattern": "t", "instruction": "i"}
    learning = Learning.from_dict(data)
    assert learning.scope == "pr_local"
    assert learning.usage_count == 0
    assert learning.dim_keys == []


# ============================================================
# Add / Get
# ============================================================

def test_add_and_get(tmp_workspace):
    store = LearningsStore(tmp_workspace)
    learning = store.add(
        trigger_pattern="PRD 涉及收藏功能",
        instruction="上限 10 条 (VIP 100)",
        scope="team_local",
        reviewer="潘驰",
        related_rule_ids=["RC-005"],
        dim_keys=["ai_coding"],
    )
    assert learning.id
    assert learning.scope == "team_local"

    fetched = store.get(learning.id)
    assert fetched is not None
    assert fetched.trigger_pattern == "PRD 涉及收藏功能"
    assert fetched.related_rule_ids == ["RC-005"]


def test_add_empty_fields_raises(tmp_workspace):
    store = LearningsStore(tmp_workspace)
    with pytest.raises(ValueError):
        store.add(trigger_pattern="", instruction="x")
    with pytest.raises(ValueError):
        store.add(trigger_pattern="x", instruction="")


def test_add_invalid_scope_falls_back(tmp_workspace):
    """非法 scope 自动回 pr_local, 不抛."""
    store = LearningsStore(tmp_workspace)
    learning = store.add(
        trigger_pattern="t",
        instruction="i",
        scope="company_global",  # 非法
    )
    assert learning.scope == "pr_local"


# ============================================================
# 重复内容自动避让
# ============================================================

def test_duplicate_id_auto_suffix(tmp_workspace):
    """同一 PM 反复添加内容相同的 learning, 第二次自动 -2 后缀."""
    store = LearningsStore(tmp_workspace)
    l1 = store.add(trigger_pattern="x", instruction="y", reviewer="A")
    l2 = store.add(trigger_pattern="x", instruction="y", reviewer="A")
    assert l1.id != l2.id
    assert l2.id.endswith("-2")


# ============================================================
# list / 过滤
# ============================================================

def test_list_all_with_scope_filter(tmp_workspace):
    store = LearningsStore(tmp_workspace)
    store.add(trigger_pattern="t1", instruction="i1", scope="team_local")
    store.add(trigger_pattern="t2", instruction="i2", scope="org_global")
    store.add(trigger_pattern="t3", instruction="i3", scope="pr_local")

    team = store.list_all(scope="team_local")
    assert len(team) == 1
    org = store.list_all(scope="org_global")
    assert len(org) == 1


def test_list_all_with_dim_filter(tmp_workspace):
    store = LearningsStore(tmp_workspace)
    store.add(trigger_pattern="t1", instruction="i", dim_keys=["ai_coding"])
    store.add(trigger_pattern="t2", instruction="i", dim_keys=["data_quality"])
    store.add(trigger_pattern="t3", instruction="i", dim_keys=["ai_coding", "data_quality"])

    ai = store.list_all(dim_key="ai_coding")
    assert len(ai) == 2  # 第一条 + 第三条


# ============================================================
# update_usage
# ============================================================

def test_update_usage_increments(tmp_workspace):
    store = LearningsStore(tmp_workspace)
    learning = store.add(trigger_pattern="t", instruction="i")
    assert learning.usage_count == 0

    store.update_usage(learning.id)
    refetched = store.get(learning.id)
    assert refetched.usage_count == 1
    assert refetched.last_used is not None

    store.update_usage(learning.id)
    refetched = store.get(learning.id)
    assert refetched.usage_count == 2


def test_update_usage_unknown_id_returns_false(tmp_workspace):
    store = LearningsStore(tmp_workspace)
    assert store.update_usage("nonexistent") is False


# ============================================================
# delete
# ============================================================

def test_delete(tmp_workspace):
    store = LearningsStore(tmp_workspace)
    l = store.add(trigger_pattern="t", instruction="i")
    assert store.delete(l.id) is True
    assert store.get(l.id) is None
    # 再删一次 returns False
    assert store.delete(l.id) is False


# ============================================================
# Index 自愈
# ============================================================

# 2026-04-29 v2 切换: yaml 后端 → sqlite WAL + file lock.
# 老的 index_path / _yaml_path / corrupted yaml self-heal 测试已不适用,
# sqlite 自带 ACID + WAL crash recovery, 不再需要应用层 self-heal.
# 损坏场景由 sqlite 自身处理 (sqlite3.DatabaseError) → see test_learnings_concurrent.py
# 历史 yaml 老 caller 走 scripts/migrate_learnings_to_sqlite.py 一次性迁移.


# ============================================================
# find_relevant_learnings 启发式
# ============================================================

def test_find_relevant_keyword_match(tmp_workspace):
    store = LearningsStore(tmp_workspace)
    store.add(
        trigger_pattern="PRD 涉及收藏功能",
        instruction="上限 10 条",
        scope="team_local",
        dim_keys=["ai_coding"],
    )
    store.add(
        trigger_pattern="PRD 引用 ds_risk_court_case 物理表",
        instruction="字段映射 5 项",
        scope="team_local",
        dim_keys=["data_quality"],
    )

    prd = "本 PRD 描述了收藏功能, 用户可以收藏企业."
    relevant = find_relevant_learnings(store, prd, dim_key="ai_coding")
    assert len(relevant) == 1
    assert "收藏" in relevant[0].trigger_pattern


def test_find_relevant_no_match_empty(tmp_workspace):
    """trigger 完全无 keyword 在 PRD 出现时应返回空."""
    store = LearningsStore(tmp_workspace)
    store.add(
        trigger_pattern="PRD 涉及对外投资",
        instruction="x",
        dim_keys=["ai_coding"],
    )
    prd = "用户管理与权限分配模块"
    relevant = find_relevant_learnings(store, prd, dim_key="ai_coding")
    assert len(relevant) == 0


def test_find_relevant_priority_order(tmp_workspace):
    """org_global > team_local > pr_local; 同 scope 按 usage_count desc."""
    store = LearningsStore(tmp_workspace)
    pr_l = store.add(trigger_pattern="收藏功能 上限", instruction="x1", scope="pr_local")
    team_l = store.add(trigger_pattern="收藏功能 团队", instruction="x2", scope="team_local")
    org_l = store.add(trigger_pattern="收藏功能 组织", instruction="x3", scope="org_global")

    prd = "PRD 提到收藏功能"
    relevant = find_relevant_learnings(store, prd, dim_key="ai_coding")
    # 期望: org_global 第一, team 第二, pr 第三
    assert relevant[0].scope == "org_global"
    assert relevant[1].scope == "team_local"
    assert relevant[2].scope == "pr_local"


def test_find_relevant_dim_filter(tmp_workspace):
    """有显式 dim_keys 标注的 learning 不应注入到其他维度."""
    store = LearningsStore(tmp_workspace)
    store.add(
        trigger_pattern="PRD 涉及收藏",
        instruction="x",
        dim_keys=["data_quality"],  # 只对 data_quality 生效
    )
    prd = "本 PRD 包含收藏功能"
    # 用 ai_coding 维度查 → 不应命中
    relevant = find_relevant_learnings(store, prd, dim_key="ai_coding")
    assert len(relevant) == 0
    # 用 data_quality 维度查 → 命中
    relevant = find_relevant_learnings(store, prd, dim_key="data_quality")
    assert len(relevant) == 1


def test_find_relevant_global_no_dim_keys(tmp_workspace):
    """无显式 dim_keys 标注的 learning 视为全维度可见."""
    store = LearningsStore(tmp_workspace)
    store.add(
        trigger_pattern="PRD 涉及收藏",
        instruction="x",
        # 不指定 dim_keys
    )
    prd = "本 PRD 包含收藏"
    for dim in ("ai_coding", "data_quality", "structure"):
        relevant = find_relevant_learnings(store, prd, dim_key=dim)
        assert len(relevant) == 1


def test_find_relevant_max_count(tmp_workspace):
    """max_count 限制返回条数."""
    store = LearningsStore(tmp_workspace)
    for i in range(10):
        store.add(trigger_pattern=f"PRD 收藏功能 #{i}", instruction="x")
    relevant = find_relevant_learnings(store, "收藏功能", dim_key="ai_coding", max_count=3)
    assert len(relevant) == 3


# ============================================================
# scope 常量 sanity
# ============================================================

def test_scopes_constant_complete():
    assert "pr_local" in SCOPES
    assert "team_local" in SCOPES
    assert "org_global" in SCOPES
