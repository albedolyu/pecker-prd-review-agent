"""P1 #1 (2026-04-24): drafts 端点横向越权修复的回归测试。

背景:
api/routes/drafts.py GET/PUT/DELETE /api/drafts/{reviewer} 三个端点原先只验
cookie 有没有(get_current_user),不验 JWT 里的 reviewer 是否等于 URL 里的 reviewer。
登录用户 alice 可以直接 `GET /api/drafts/bob` 拿到 bob 的草稿(含 PRD 原文)。

修复: 端点开头调 _require_self_or_admin,JWT.reviewer != URL.reviewer 且非 admin → 403。
"""
from __future__ import annotations

import os
import sys

import pytest
from fastapi import HTTPException

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from api.routes.drafts import _require_self_or_admin
from api.routes.drafts import DraftPayload, write_draft_file


class TestRequireSelfOrAdmin:
    def test_self_access_allowed(self, monkeypatch):
        """用户读/写/删自己的草稿 → 放行(不抛异常)。"""
        monkeypatch.delenv("PECKER_ADMIN_USERS", raising=False)
        _require_self_or_admin({"reviewer": "alice"}, "alice")  # 不应抛

    def test_cross_user_access_denied(self, monkeypatch):
        """alice 请求 /api/drafts/bob → 403,这是核心越权场景。"""
        monkeypatch.delenv("PECKER_ADMIN_USERS", raising=False)
        with pytest.raises(HTTPException) as ei:
            _require_self_or_admin({"reviewer": "alice"}, "bob")
        assert ei.value.status_code == 403
        assert "无权" in ei.value.detail

    def test_admin_can_read_anyone(self, monkeypatch):
        """admin 可跨人读(运维恢复场景 / on-call 调试)。"""
        monkeypatch.setenv("PECKER_ADMIN_USERS", "root,opsguy")
        _require_self_or_admin({"reviewer": "root"}, "bob")  # 不应抛
        _require_self_or_admin({"reviewer": "opsguy"}, "alice")  # 不应抛

    def test_empty_user_denied(self, monkeypatch):
        """JWT payload 被改空 reviewer → 也应拒绝(防空对空匹配绕过)。"""
        monkeypatch.delenv("PECKER_ADMIN_USERS", raising=False)
        with pytest.raises(HTTPException):
            _require_self_or_admin({"reviewer": ""}, "bob")
        with pytest.raises(HTTPException):
            _require_self_or_admin({}, "bob")

    def test_admin_reads_self_also_ok(self, monkeypatch):
        """admin 读自己的草稿也应放行(走 reviewer == reviewer 分支,不依赖 admin bypass)。"""
        monkeypatch.setenv("PECKER_ADMIN_USERS", "root")
        _require_self_or_admin({"reviewer": "root"}, "root")


def test_draft_payload_preserves_review_mode():
    payload = DraftPayload(phase=3, prd_name="demo.md", prd_content="# Demo", mode="quick")

    assert payload.mode == "quick"


def test_write_draft_file_redacts_secret_from_returned_path(tmp_path):
    fake_key = "sk-01234567890abcdefABCDEFghij"
    result = write_draft_file(
        tmp_path,
        f"alice {fake_key}",
        DraftPayload(phase=1, prd_name="demo.md", prd_content="# Demo"),
    )

    assert fake_key not in result["path"]
    assert "REDACTED_SECRET" in result["path"]
