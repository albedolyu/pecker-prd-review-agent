"""RulePerformanceHistoryStore schema migration 测试 (2026-04-23 #3).

覆盖 v0 → v1 的自动 migration 契约:
- 无 __meta__ 的旧数据 load 后仍可读
- 下次 save 会自动写入 __meta__
- 多次 load/save 不会反复加新的 __meta__ 字段
- __meta__ 对 iter_rules 遍历透明
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from rule_perf_store import (
    RulePerformanceHistoryStore,
    _META_KEY,
    _CURRENT_SCHEMA_VERSION,
    _detect_schema_version,
)


@pytest.fixture
def ws(tmp_path):
    return tmp_path


def test_detect_v0_no_meta():
    data = {"V-01": {"stats": {}}, "V-02": {"stats": {}}}
    assert _detect_schema_version(data) == 0


def test_detect_v1_with_meta():
    data = {"__meta__": {"schema_version": 1}, "V-01": {}}
    assert _detect_schema_version(data) == 1


def test_load_legacy_v0_still_works(ws):
    """写一份 v0 旧格式文件直接到磁盘, load 应能读, 业务字段保留."""
    (ws / "output").mkdir()
    legacy = {
        "V-01": {"stats": {"confirmed": 5, "total": 10}, "rejection_rate": 0.5},
        "V-02": {"stats": {"confirmed": 2, "total": 2}, "rejection_rate": 0.0},
    }
    (ws / "output" / "rule_performance_history.json").write_text(
        json.dumps(legacy), encoding="utf-8",
    )

    store = RulePerformanceHistoryStore(ws)
    loaded = store.load()

    # 业务数据完整
    assert loaded["V-01"]["stats"]["confirmed"] == 5
    assert loaded["V-02"]["rejection_rate"] == 0.0


def test_save_adds_meta_for_legacy_data(ws):
    """load v0 → 改动 → save, __meta__ 应被写入."""
    (ws / "output").mkdir()
    legacy = {"V-01": {"stats": {"confirmed": 1, "total": 1}}}
    (ws / "output" / "rule_performance_history.json").write_text(
        json.dumps(legacy), encoding="utf-8",
    )

    store = RulePerformanceHistoryStore(ws)
    data = store.load()
    data["V-01"]["stats"]["confirmed"] = 2  # 模拟业务更新
    store.save(data)

    # 读回, __meta__ 应该有了
    raw = json.loads((ws / "output" / "rule_performance_history.json").read_text(encoding="utf-8"))
    assert _META_KEY in raw
    assert raw[_META_KEY]["schema_version"] == _CURRENT_SCHEMA_VERSION
    assert "updated_at" in raw[_META_KEY]


def test_save_updates_timestamp_not_duplicates(ws):
    """多次 save, __meta__ 只有一份, schema_version / updated_at 被更新."""
    store = RulePerformanceHistoryStore(ws)
    store.save({"V-01": {"v": 1}})
    first_ts = json.loads(
        (ws / "output" / "rule_performance_history.json").read_text(encoding="utf-8"),
    )[_META_KEY]["updated_at"]

    import time
    time.sleep(1.1)
    store.save({"V-01": {"v": 2}})
    raw = json.loads(
        (ws / "output" / "rule_performance_history.json").read_text(encoding="utf-8"),
    )

    # __meta__ 只有一个
    assert list(raw.keys()).count(_META_KEY) == 1
    # updated_at 被更新
    assert raw[_META_KEY]["updated_at"] > first_ts


def test_iter_rules_skips_meta(ws):
    """iter_rules 给下游 caller 用, 必须跳过 __meta__."""
    store = RulePerformanceHistoryStore(ws)
    store.save({"V-01": {"ok": True}, "V-02": {"ok": True}})
    data = store.load()

    rule_ids = [rid for rid, _ in store.iter_rules(data)]
    assert _META_KEY not in rule_ids
    assert set(rule_ids) == {"V-01", "V-02"}


def test_preserves_custom_meta_fields(ws):
    """save 时应保留 __meta__ 里的其他自定义字段, 只覆盖 schema_version / updated_at."""
    (ws / "output").mkdir()
    existing = {
        "__meta__": {"schema_version": 1, "custom_tag": "foo"},
        "V-01": {"ok": True},
    }
    (ws / "output" / "rule_performance_history.json").write_text(
        json.dumps(existing), encoding="utf-8",
    )

    store = RulePerformanceHistoryStore(ws)
    data = store.load()
    store.save(data)

    raw = json.loads((ws / "output" / "rule_performance_history.json").read_text(encoding="utf-8"))
    # custom_tag 保留
    assert raw[_META_KEY]["custom_tag"] == "foo"
    assert raw[_META_KEY]["schema_version"] == _CURRENT_SCHEMA_VERSION
