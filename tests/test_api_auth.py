"""
Phase A.5 (plan A12): api.deps.get_current_user 必须从 JWT cookie 解析 reviewer
运行: pytest tests/test_api_auth.py -v

背景:
A12 在 Phase A commit b941050 里被半实现 — auth.py 的 login/me/logout 能签发和解析
pecker_session cookie,但共享的 get_current_user 依赖还停留在占位实现(读 X-Reviewer
header,缺失时 fallback "anonymous"),导致 audit / reports / feishu 的 require_writer
readonly 拦截被客户端可控的 header 绕过。

本文件是这个修复的回归测试:
1. 有效 JWT cookie → 返回 cookie 里的 reviewer(不是 "anonymous")
2. 缺失 cookie → 抛 401(不再静默 fallback)
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta

import pytest
from jose import jwt

# 让 Python 找到上级目录的 api/ 包
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# 固定一个测试用 JWT secret(必须 ≥ 16 字符,匹配 auth._get_jwt_secret 的校验)
_TEST_SECRET = "unit-test-jwt-secret-at-least-32-chars-aaaa"
os.environ["PECKER_JWT_SECRET"] = _TEST_SECRET


def _make_jwt(reviewer: str, readonly: bool = False, secret: str = _TEST_SECRET) -> str:
    """构造一个有效 payload 的 JWT token,签名用 HS256。"""
    payload = {
        "reviewer": reviewer,
        "readonly": readonly,
        "exp": datetime.utcnow() + timedelta(hours=1),
        "iat": datetime.utcnow(),
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def _fake_request(headers: list[tuple[bytes, bytes]]):
    """造一个最小可用的 starlette Request,用来直调依赖函数。"""
    from starlette.requests import Request

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/test",
        "headers": headers,
        "query_string": b"",
    }
    return Request(scope)


class TestGetCurrentUserReadsJwtCookie:
    """A12: get_current_user 必须从 pecker_session cookie 解析 reviewer。"""

    def test_reads_reviewer_from_valid_cookie(self):
        """核心修复:有效 cookie → 返回 cookie 里的 reviewer(而不是 anonymous)。

        这个测试在占位实现上会失败,因为占位实现读的是 X-Reviewer header,
        没有 header 时会 fallback 成 'anonymous'。
        """
        from api.deps import get_current_user

        token = _make_jwt("张三")
        req = _fake_request([(b"cookie", f"pecker_session={token}".encode())])

        user = get_current_user(req)

        assert user["reviewer"] == "张三", (
            "get_current_user 必须从 JWT cookie 解析 reviewer,"
            "占位实现会返回 'anonymous'"
        )
        assert user["readonly"] is False

    def test_raises_401_when_no_cookie(self):
        """没有 cookie → 401,不再静默 fallback 到 'anonymous'。

        占位实现会返回 {reviewer: 'anonymous', readonly: False},等效于
        未认证用户可以任意调用 POST /api/audit、/api/feishu/send 等端点。
        修复后应该抛 401。
        """
        from fastapi import HTTPException

        from api.deps import get_current_user

        req = _fake_request([])

        with pytest.raises(HTTPException) as exc_info:
            get_current_user(req)
        assert exc_info.value.status_code == 401
