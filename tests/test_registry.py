"""Task B1 — registry 模块测试 (TDD RED 阶段)

覆盖:
- 路径规范化 (Windows 小写驱动器 + 跨平台 resolve)
- load_registry 缺失/损坏文件的降级
- save → load round-trip
- register_repo 按路径去重
- list_pending 判 HEAD != last_scanned_commit
- list_pending 跳过不可达仓库
- mark_scanned 更新 sha
"""
import json
import os
import sys
import tempfile
import pytest
from pathlib import Path
from registry import (
    load_registry,
    save_registry,
    register_repo,
    list_pending,
    mark_scanned,
    _normalize_path,
    RegistryEntry,
)


def test_normalize_path_is_absolute(tmp_path):
    p = _normalize_path(str(tmp_path))
    assert os.path.isabs(p)


def test_normalize_path_lowercases_drive_on_windows(tmp_path):
    p = _normalize_path(str(tmp_path))
    if sys.platform.startswith("win"):
        # 驱动器字母应当是小写
        assert p[0].islower()


def test_load_registry_missing_file_returns_empty(tmp_path):
    reg = load_registry(str(tmp_path / "noexist.json"))
    assert reg == {"version": "1", "repos": []}


def test_load_registry_corrupt_file_returns_empty(tmp_path):
    path = tmp_path / "corrupt.json"
    path.write_text("{not json")
    reg = load_registry(str(path))
    assert reg == {"version": "1", "repos": []}


def test_save_then_load_roundtrip(tmp_path):
    path = str(tmp_path / "reg.json")
    reg = {"version": "1", "repos": [
        {"repo_path": "/a/b", "workspace": "ws", "scope": "x",
         "last_scanned_commit": "abc", "last_scan_at": "2026-04-15T00:00:00"}
    ]}
    save_registry(path, reg)
    loaded = load_registry(path)
    assert loaded == reg


def test_register_repo_dedups_by_path(tmp_path):
    path = str(tmp_path / "reg.json")
    fake_repo = tmp_path / "fake_repo"
    fake_repo.mkdir()
    register_repo(path, str(fake_repo), workspace="ws1", scope="投资", prd="p.md")
    register_repo(path, str(fake_repo), workspace="ws2", scope="投资", prd="p2.md")
    reg = load_registry(path)
    assert len(reg["repos"]) == 1
    # 后注册的应该覆盖前注册的
    assert reg["repos"][0]["workspace"] == "ws2"
    assert reg["repos"][0]["prd"] == "p2.md"


def test_list_pending_detects_new_commits(tmp_path, monkeypatch):
    fake_repo = str(tmp_path / "fake")
    os.makedirs(fake_repo)

    # mock HEAD returns "new_sha"
    monkeypatch.setattr("registry._get_head_sha", lambda _p: "new_sha")

    reg = {"version": "1", "repos": [
        {"repo_path": _normalize_path(fake_repo), "workspace": "ws", "scope": "x",
         "last_scanned_commit": "old_sha", "last_scan_at": "2026-01-01T00:00:00"}
    ]}
    pending = list_pending(reg)
    assert len(pending) == 1
    assert pending[0]["repo_path"] == _normalize_path(fake_repo)
    assert pending[0]["current_sha"] == "new_sha"


def test_list_pending_skips_up_to_date(tmp_path, monkeypatch):
    fake_repo = str(tmp_path / "fake")
    os.makedirs(fake_repo)
    monkeypatch.setattr("registry._get_head_sha", lambda _p: "same")
    reg = {"version": "1", "repos": [
        {"repo_path": _normalize_path(fake_repo), "workspace": "ws", "scope": "x",
         "last_scanned_commit": "same", "last_scan_at": "2026-01-01T00:00:00"}
    ]}
    assert list_pending(reg) == []


def test_list_pending_handles_unreachable_repo(tmp_path, monkeypatch):
    monkeypatch.setattr("registry._get_head_sha", lambda _p: None)
    reg = {"version": "1", "repos": [
        {"repo_path": str(tmp_path / "ghost"), "workspace": "ws", "scope": "x",
         "last_scanned_commit": "x", "last_scan_at": "2026-01-01T00:00:00"}
    ]}
    # None HEAD => 跳过,不放进 pending
    assert list_pending(reg) == []


def test_mark_scanned_updates_sha(tmp_path):
    path = str(tmp_path / "reg.json")
    fake_repo = tmp_path / "fake"
    fake_repo.mkdir()
    register_repo(path, str(fake_repo), workspace="ws", scope="x", prd="p.md")
    mark_scanned(path, str(fake_repo), "new_sha_123")
    reg = load_registry(path)
    assert reg["repos"][0]["last_scanned_commit"] == "new_sha_123"
    assert reg["repos"][0]["last_scan_at"]  # 应该被填充了时间戳
