"""workspace ACL 回归测试(配合 api/workspace_acl.py 2026-04-23 落地的 1.6 gate)。

覆盖三条核心路径:
- 无 .pecker_acl.json → 公开(backward compat)
- ACL 文件存在 + user 不在 owner/readers → 拒绝
- PECKER_ADMIN_USERS bypass 所有 ACL
+ 边缘:损坏 ACL 文件 fail-safe 关闭访问 / 空 reviewer 拒绝
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from api.workspace_acl import can_access_workspace, require_workspace_access


@pytest.fixture
def ws_dir(tmp_path):
    """临时 workspace 目录。"""
    d = tmp_path / "workspace-test"
    d.mkdir()
    return d


def _write_acl(ws: Path, payload: dict):
    (ws / ".pecker_acl.json").write_text(json.dumps(payload), encoding="utf-8")


def test_no_acl_file_is_public(ws_dir, monkeypatch):
    """无 .pecker_acl.json 视为公开 — 向后兼容现有 workspace-sample 等 demo。"""
    monkeypatch.delenv("PECKER_ADMIN_USERS", raising=False)
    assert can_access_workspace(ws_dir, {"reviewer": "alice", "readonly": False}) is True
    assert can_access_workspace(ws_dir, {"reviewer": "bob", "readonly": False}) is True


def test_acl_owner_can_access(ws_dir, monkeypatch):
    monkeypatch.delenv("PECKER_ADMIN_USERS", raising=False)
    _write_acl(ws_dir, {"owner": "alice", "readers": []})
    assert can_access_workspace(ws_dir, {"reviewer": "alice"}) is True


def test_acl_reader_can_access(ws_dir, monkeypatch):
    monkeypatch.delenv("PECKER_ADMIN_USERS", raising=False)
    _write_acl(ws_dir, {"owner": "alice", "readers": ["bob", "carol"]})
    assert can_access_workspace(ws_dir, {"reviewer": "bob"}) is True
    assert can_access_workspace(ws_dir, {"reviewer": "carol"}) is True


def test_acl_stranger_denied(ws_dir, monkeypatch):
    """既不是 owner 也不在 readers 列表 → 拒绝。"""
    monkeypatch.delenv("PECKER_ADMIN_USERS", raising=False)
    _write_acl(ws_dir, {"owner": "alice", "readers": ["bob"]})
    assert can_access_workspace(ws_dir, {"reviewer": "mallory"}) is False


def test_admin_bypasses_acl(ws_dir, monkeypatch):
    """PECKER_ADMIN_USERS 里的人无视 ACL。"""
    monkeypatch.setenv("PECKER_ADMIN_USERS", "admin1,admin2")
    _write_acl(ws_dir, {"owner": "alice", "readers": []})
    assert can_access_workspace(ws_dir, {"reviewer": "admin1"}) is True
    assert can_access_workspace(ws_dir, {"reviewer": "admin2"}) is True


def test_empty_reviewer_denied(ws_dir, monkeypatch):
    """reviewer 空字符串应拒绝(防 JWT payload 被篡空)。"""
    monkeypatch.delenv("PECKER_ADMIN_USERS", raising=False)
    assert can_access_workspace(ws_dir, {"reviewer": ""}) is False
    assert can_access_workspace(ws_dir, {}) is False


def test_corrupted_acl_fails_closed(ws_dir, monkeypatch):
    """ACL 文件损坏(非 JSON)应 fail-closed(拒绝所有非 admin 访问),不是降级为公开。

    这是和 "无 ACL = 公开" 的关键差别:有 ACL 但坏 → 安全起见关门。
    """
    monkeypatch.delenv("PECKER_ADMIN_USERS", raising=False)
    (ws_dir / ".pecker_acl.json").write_text("not-json-garbage", encoding="utf-8")
    assert can_access_workspace(ws_dir, {"reviewer": "alice"}) is False
    assert can_access_workspace(ws_dir, {"reviewer": "bob"}) is False


def test_corrupted_acl_still_admin_bypass(ws_dir, monkeypatch):
    """ACL 坏了 admin 仍能进(否则 admin 无法去修复 ACL)。"""
    monkeypatch.setenv("PECKER_ADMIN_USERS", "root")
    (ws_dir / ".pecker_acl.json").write_text("{{{broken", encoding="utf-8")
    assert can_access_workspace(ws_dir, {"reviewer": "root"}) is True


def test_require_workspace_access_raises_403(ws_dir, monkeypatch):
    """require_workspace_access 拒绝时抛 HTTPException 403,不是静默 return False。"""
    monkeypatch.delenv("PECKER_ADMIN_USERS", raising=False)
    _write_acl(ws_dir, {"owner": "alice"})
    with pytest.raises(HTTPException) as ei:
        require_workspace_access(ws_dir, {"reviewer": "mallory"})
    assert ei.value.status_code == 403
