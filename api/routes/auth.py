"""POST /api/auth/login — 团队密码验证 + JWT cookie 签发
GET /api/me — 返回当前登录 reviewer + readonly 状态
POST /api/auth/logout — 清 cookie
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException, Request, Response, status
from jose import JWTError, jwt
from pydantic import BaseModel, Field

router = APIRouter(tags=["auth"])

COOKIE_NAME = "pecker_session"
JWT_ALG = "HS256"
JWT_EXP_HOURS = 8


def _get_jwt_secret() -> str:
    secret = os.environ.get("PECKER_JWT_SECRET", "")
    if not secret or len(secret) < 16:
        raise HTTPException(
            status_code=500,
            detail="PECKER_JWT_SECRET 未配置或过短",
        )
    return secret


class LoginRequest(BaseModel):
    password: str = Field(..., min_length=1)
    reviewer: str = Field(..., min_length=1, max_length=40, description="评审人姓名,用于署名和审计")


@router.post("/auth/login")
async def login(req: LoginRequest, response: Response):
    """验证密码 + 签发 JWT cookie。

    密码校验: 明文对比 env var PECKER_WEB_PASSWORD(缺失时拒绝登录 = 关闭整个后端)。
    Cookie 有效期 8 小时,SameSite=Lax,HttpOnly。
    """
    expected = os.environ.get("PECKER_WEB_PASSWORD", "")
    if not expected:
        # 不配置密码时禁止登录(生产环境必须配)
        raise HTTPException(
            status_code=503,
            detail="服务端未配置 PECKER_WEB_PASSWORD,登录功能关闭",
        )

    if req.password != expected:
        raise HTTPException(status_code=401, detail="密码错误")

    # 判定是否只读
    readonly_list = os.environ.get("PECKER_READONLY_USERS", "")
    readonly_users = {u.strip() for u in readonly_list.split(",") if u.strip()}
    is_readonly = req.reviewer.strip() in readonly_users

    # 签发 JWT
    payload = {
        "reviewer": req.reviewer.strip(),
        "readonly": is_readonly,
        "exp": datetime.utcnow() + timedelta(hours=JWT_EXP_HOURS),
        "iat": datetime.utcnow(),
    }
    token = jwt.encode(payload, _get_jwt_secret(), algorithm=JWT_ALG)

    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        max_age=JWT_EXP_HOURS * 3600,
        httponly=True,
        samesite="lax",
        secure=False,  # dev 模式 http,prod 部署 HTTPS 时改 True
    )

    return {
        "status": "ok",
        "reviewer": req.reviewer,
        "readonly": is_readonly,
        "exp_hours": JWT_EXP_HOURS,
    }


@router.get("/me")
async def get_me(request: Request):
    """返回当前登录态 + readonly 状态,给前端 banner 用。"""
    token = request.cookies.get(COOKIE_NAME, "")
    if not token:
        raise HTTPException(status_code=401, detail="未登录")

    try:
        payload = jwt.decode(token, _get_jwt_secret(), algorithms=[JWT_ALG])
    except JWTError as e:
        raise HTTPException(status_code=401, detail=f"登录已失效: {str(e)[:60]}")

    return {
        "reviewer": payload.get("reviewer", ""),
        "readonly": payload.get("readonly", False),
    }


@router.post("/auth/logout")
async def logout(response: Response):
    response.delete_cookie(COOKIE_NAME)
    return {"status": "ok"}
