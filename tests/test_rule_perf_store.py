"""RulePerformanceHistoryStore 单测 — 配合 2026-04-23 #2 代码优雅度 refactor。

覆盖三处 caller (api/routes/review / cuckoo_scorer / feedback) 共享的 load/save 契约:
- 不存在文件 → load 返回 {}
- 文件存在且合法 → load 返回 dict
- 文件坏 (非 JSON / 非 dict) → load 返回 {} 不抛
- save 原子性: 先写 tempfile 再 rename, 崩溃不产生半 json
- save 会自动 mkdir -p output/
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from rule_perf_store import RulePerformanceHistoryStore


@pytest.fixture
def ws(tmp_path):
    """临时 workspace 目录。"""
    return tmp_path


def test_load_nonexistent_returns_empty_dict(ws):
    store = RulePerformanceHistoryStore(ws)
    assert store.load() == {}


def test_save_then_load_roundtrip(ws):
    store = RulePerformanceHistoryStore(ws)
    payload = {"V-08": {"stats": {"confirmed": 3, "rejected": 1, "total": 4}}}
    store.save(payload)
    loaded = store.load()
    # save 会自动加 __meta__ schema_version, 业务 rule 部分一致即可
    assert loaded["V-08"] == payload["V-08"]
    assert loaded["__meta__"]["schema_version"] == store.SCHEMA_VERSION


def test_save_creates_output_dir(ws):
    store = RulePerformanceHistoryStore(ws)
    assert not (ws / "output").exists()
    store.save({"V-01": {"stats": {"total": 1}}})
    assert (ws / "output" / "rule_performance_history.json").is_file()


def test_save_retries_transient_permission_error_on_replace(ws, monkeypatch):
    store = RulePerformanceHistoryStore(ws)
    calls = {"replace": 0}
    orig_replace = os.replace

    def flaky_replace(src, dst):
        calls["replace"] += 1
        if calls["replace"] == 1:
            raise PermissionError("simulated transient Windows lock")
        return orig_replace(src, dst)

    import rule_perf_store

    monkeypatch.setattr(os, "replace", flaky_replace)
    monkeypatch.setattr(rule_perf_store.time, "sleep", lambda _: None)

    store.save({"V-01": {"stats": {"total": 1}}})

    assert calls["replace"] == 2
    assert store.load()["V-01"]["stats"]["total"] == 1
    assert list((ws / "output").glob(".rule_perf_*.tmp")) == []


def test_load_corrupted_returns_empty_dict(ws):
    """JSON 坏了应该 fail-safe 返回 {}, 不抛"""
    store = RulePerformanceHistoryStore(ws)
    (ws / "output").mkdir()
    (ws / "output" / "rule_performance_history.json").write_text("not-json", encoding="utf-8")
    assert store.load() == {}


def test_load_json_list_returns_empty_dict(ws):
    """防御: 被写坏成 list 也返回 {} 而不是 list, 让下游 setdefault 安全"""
    store = RulePerformanceHistoryStore(ws)
    (ws / "output").mkdir()
    (ws / "output" / "rule_performance_history.json").write_text('["x"]', encoding="utf-8")
    assert store.load() == {}


def test_save_is_atomic_no_half_write(ws, monkeypatch):
    """save 中途 crash 不应让原文件消失或变半"""
    store = RulePerformanceHistoryStore(ws)
    store.save({"V-01": {"ok": True}})

    # 模拟 json.dump 过程中抛异常 (写 tempfile 失败)
    orig_dump = json.dump
    def bomb(*a, **k):
        raise RuntimeError("simulated crash")
    monkeypatch.setattr("json.dump", bomb)

    with pytest.raises(RuntimeError):
        store.save({"V-02": {"new": True}})

    # 原文件应该还在, 内容是上次保存的 (业务 rule 部分, __meta__ 不比较)
    monkeypatch.setattr("json.dump", orig_dump)
    loaded = store.load()
    assert loaded["V-01"] == {"ok": True}
    assert "V-02" not in loaded  # bomb 的那次没落盘

    # tempfile 不应泄漏到 output/ 目录
    tmp_files = list((ws / "output").glob(".rule_perf_*.tmp"))
    assert tmp_files == [], f"tempfile 泄漏: {tmp_files}"


def test_path_property_correct(ws):
    store = RulePerformanceHistoryStore(ws)
    assert store.path == ws / "output" / "rule_performance_history.json"
