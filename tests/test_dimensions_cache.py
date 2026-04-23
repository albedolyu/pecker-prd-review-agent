"""dimensions 模块 lru_cache 行为回归测试.

Background: 2026-04-23 优雅度 #4 refactor 把 _loaded_dimensions / _loaded_wiki_keywords
模块 global 改成 @lru_cache. 首版有 subtle bug — 所有 `workspace=None` 调用都命中
同一 cache entry, CLI 切 os.environ["WORKSPACE"] 后仍返回第一次的配置。

修法: _resolve_workspace_key(None) 把 None 解析成 env var 值作为真实 key, 让
lru_cache 按实际 workspace 分桶. 本测试锁死这个行为.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from review.dimensions import (
    _DEFAULT_WS_KEY,
    _cached_load,
    _resolve_workspace_key,
    get_review_dimensions,
)


def test_resolve_explicit_workspace_preserved():
    assert _resolve_workspace_key("/tmp/ws-foo") == "/tmp/ws-foo"


def test_resolve_none_reads_env(monkeypatch):
    monkeypatch.setenv("WORKSPACE", "/tmp/ws-from-env")
    assert _resolve_workspace_key(None) == "/tmp/ws-from-env"


def test_resolve_none_no_env_uses_default_sentinel(monkeypatch):
    monkeypatch.delenv("WORKSPACE", raising=False)
    assert _resolve_workspace_key(None) == _DEFAULT_WS_KEY


def test_cli_workspace_switch_does_not_return_stale_config(monkeypatch):
    """CLI 场景: 第一次跑 workspace-A, 改 env 再调, 必须重新加载不命中旧 cache.

    这是 refactor 首版的 bug, 本测试防止回退.
    """
    _cached_load.cache_clear()

    monkeypatch.setenv("WORKSPACE", "/tmp/ws-A")
    dims_a = get_review_dimensions()  # miss, 缓存到 key="/tmp/ws-A"

    monkeypatch.setenv("WORKSPACE", "/tmp/ws-B")
    dims_b = get_review_dimensions()  # 应 miss (新 key), 不应复用 A

    info = _cached_load.cache_info()
    # 两次调用都应 miss (两个不同 key), 不是一次 miss 一次 hit
    assert info.misses == 2, f"期望 2 次 miss, 实际 {info}"
    assert info.currsize == 2


def test_same_workspace_second_call_hits_cache(monkeypatch):
    """同 workspace 连续调两次, 第二次必须 cache hit, 避免重复读 YAML."""
    _cached_load.cache_clear()
    monkeypatch.setenv("WORKSPACE", "/tmp/ws-stable")

    get_review_dimensions()
    get_review_dimensions()

    info = _cached_load.cache_info()
    assert info.hits == 1
    assert info.misses == 1
