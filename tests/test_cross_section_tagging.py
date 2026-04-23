"""跨章节矛盾标记测试 (gate 6a, 2026-04-23)."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from review.aggregation import (
    _is_cross_section_contradiction,
    merge_and_deduplicate,
    tag_cross_section_items,
)


def test_rule_id_v06_tagged():
    """V-06 可追溯链完整性天然跨章节。"""
    assert _is_cross_section_contradiction({"rule_id": "V-06", "location": "", "issue": ""})


def test_rule_id_v05_tagged():
    """V-05 信息完整性/自洽天然跨章节。"""
    assert _is_cross_section_contradiction({"rule_id": "V-05", "location": "", "issue": ""})


def test_two_section_refs_in_location():
    """location 含两个 § 章节号 → 跨章节。"""
    item = {
        "rule_id": "V-08",
        "location": "§3 vs §6.1",
        "issue": "同一数据字段描述不同",
    }
    assert _is_cross_section_contradiction(item)


def test_contradiction_keyword_in_issue():
    """issue 含"矛盾" 关键词 → 跨章节。"""
    item = {
        "rule_id": "V-08",
        "location": "§2.1",
        "issue": "快捷档位数量前后矛盾: 状态 3 写三档,细节章节写四档",
    }
    assert _is_cross_section_contradiction(item)


def test_two_places_keyword():
    """issue 含"两处"关键词 → 跨章节。"""
    item = {"rule_id": "", "location": "", "issue": "两处对同一问题描述不一致"}
    assert _is_cross_section_contradiction(item)


def test_single_section_not_tagged():
    """正常单章节问题不应误标。"""
    item = {
        "rule_id": "V-08",
        "location": "§2.1 Web UI",
        "issue": "缺少排序字段说明",
    }
    assert not _is_cross_section_contradiction(item)


def test_tag_list_mutates_in_place():
    items = [
        {"rule_id": "V-06", "location": "全文", "issue": "可追溯链断裂"},
        {"rule_id": "V-08", "location": "§2.1", "issue": "缺排序"},
    ]
    tag_cross_section_items(items)
    assert items[0]["is_cross_section"] is True
    assert items[1]["is_cross_section"] is False


def test_merge_and_deduplicate_tags_items():
    """merge_and_deduplicate 端到端: 输出 items 必须都有 is_cross_section 字段。"""
    raw = [
        {"rule_id": "V-06", "location": "全文", "issue": "可追溯链断裂", "severity": "must"},
        {"rule_id": "V-08", "location": "§2.1", "issue": "缺排序", "severity": "should"},
    ]
    merged = merge_and_deduplicate(raw)
    assert len(merged) == 2
    for item in merged:
        assert "is_cross_section" in item
    # V-06 应标记, V-08 不应
    v06 = next(i for i in merged if i.get("rule_id") == "V-06")
    v08 = next(i for i in merged if i.get("rule_id") == "V-08")
    assert v06["is_cross_section"] is True
    assert v08["is_cross_section"] is False
