"""啄木鸟 FastAPI app — 为 Next.js 前端提供 REST + SSE 接口。

启动方式:
    uvicorn api.main:app --reload --port 8000 --host 0.0.0.0

依赖 env var:
    USE_CLAUDE_CODE=1                   必须,走本地 Claude Code CLI
    PECKER_MAX_CONCURRENT=2             同时评审数上限(防公共账号 rate limit)
    PECKER_WEB_PASSWORD=xxx             可选,Web 访问密码
    PECKER_READONLY_USERS=a,b           可选,只读 reviewer 白名单
    PECKER_SIGNATURE_SECRET=xxx         必须,ReviewResult 防篡改 HMAC 密钥
    PECKER_JWT_SECRET=xxx               必须,登录 cookie JWT 密钥
    WIKI_PATH=./shared-wiki             可选,wiki 目录
    FEISHU_APP_ID / FEISHU_APP_SECRET / FEISHU_REPORT_CHAT_ID  可选
"""
from __future__ import annotations

import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# 在 import 任何啄木鸟业务模块前先加载 .env
_PROJECT_ROOT = Path(__file__).parent.parent
load_dotenv(_PROJECT_ROOT / ".env", override=True)

# 确保业务模块可 import(project root 在 sys.path)
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动时做必要的 env var 校验,缺失关键密钥直接拒绝启动。"""
    errors = []

    use_cc = os.environ.get("USE_CLAUDE_CODE", "").strip().lower() in ("1", "true", "yes", "on")
    if not use_cc:
        errors.append("USE_CLAUDE_CODE 必须设为 1(本项目只支持本地 Claude Code CLI)")
    else:
        import shutil
        if not shutil.which("claude"):
            errors.append("找不到 claude CLI,请先 `npm install -g @anthropic-ai/claude-code && claude login`")

    warnings = []

    def _check_secret(name: str, required_min=16, recommended_min=32):
        val = os.environ.get(name, "")
        if not val:
            errors.append(f"{name} 未设置 — 用 `bash scripts/gen-secrets.sh` 生成")
        elif len(val) < required_min:
            errors.append(
                f"{name} 长度 {len(val)} 不足 {required_min} 字符(强度过低) — "
                f"用 `bash scripts/gen-secrets.sh` 重新生成"
            )
        elif len(val) < recommended_min:
            warnings.append(
                f"{name} 长度 {len(val)} < {recommended_min} 推荐值, 生产环境建议重新生成"
            )

    _check_secret("PECKER_SIGNATURE_SECRET")
    _check_secret("PECKER_JWT_SECRET")

    if errors:
        print("\n[FastAPI 启动失败]", file=sys.stderr)
        for e in errors:
            print(f"  ✗ {e}", file=sys.stderr)
        print("\n请检查 .env 文件后重试。", file=sys.stderr)
        raise RuntimeError("FastAPI 启动前置检查失败")

    if warnings:
        print("\n[FastAPI 启动警告]", file=sys.stderr)
        for w in warnings:
            print(f"  ⚠ {w}", file=sys.stderr)
        print("", file=sys.stderr)

    print("[FastAPI] 启动完成,所有前置检查通过")
    print(f"[FastAPI] 并发上限: {os.environ.get('PECKER_MAX_CONCURRENT', '2')}")
    print(f"[FastAPI] 监听 CORS origin: http://localhost:3000 (Next.js dev)")
    yield
    print("[FastAPI] 关闭")


app = FastAPI(
    title="啄木鸟 Pecker API",
    description="PRD 评审系统的后端 API,为 Next.js 前端提供流式评审能力",
    version="2.0.0",
    lifespan=lifespan,
)

# 开发时允许 Next.js dev server (localhost:3000) 调用
# 生产环境不需要 CORS 因为 Next.js 会 rewrite 代理 /api/*
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        # 允许其它 dev 端口直连(主要给 SSE /api/review/run,绕开 Next.js
        # dev rewrite 对 streaming response 的 buffer 行为)
        "http://localhost:3300",
        "http://localhost:3500",
        "http://127.0.0.1:3500",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health():
    """Liveness probe — 仅验证 FastAPI 在跑,不校验 Claude CLI 或 env"""
    return {"status": "ok", "service": "pecker-api", "version": "2.0.0"}


@app.get("/api/")
async def root():
    """根路径,提示 API 版本和可用 endpoint 列表(调试用)"""
    return {
        "name": "啄木鸟 Pecker API",
        "version": "2.0.0",
        "docs": "/docs",
        "health": "/api/health",
        "routes_registered": [r.path for r in app.routes if hasattr(r, "path")],
    }


# ============================================================
# 注册路由(每个子模块独立,便于分阶段实现)
# ============================================================

from api.routes import workspaces, drafts, audit, review, reports, feishu, auth
app.include_router(workspaces.router, prefix="/api")
app.include_router(drafts.router, prefix="/api")
app.include_router(audit.router, prefix="/api")
app.include_router(review.router, prefix="/api")
app.include_router(reports.router, prefix="/api")
app.include_router(feishu.router, prefix="/api")
app.include_router(auth.router, prefix="/api")
