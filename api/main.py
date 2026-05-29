"""啄木鸟 FastAPI app — 为 Next.js 前端提供 REST + SSE 接口。

启动方式:
    uvicorn api.main:app --reload --port 8000 --host 0.0.0.0

依赖 env var:
    OPENAI_API_KEY=xxx                  团队上线默认,走 OpenAI 兼容 API
    OPENAI_BASE_URL=xxx                 可选,OpenAI 兼容中转地址
    OPENAI_WIRE_API=responses           可选,OpenAI wire: responses / chat_completions
    OPENAI_REASONING_EFFORT=xhigh       可选,Responses 推理强度
    OPENAI_DISABLE_RESPONSE_STORAGE=true 可选,不保存 Responses 输出
    USE_CLAUDE_CODE=1                   可选,仅本地开发走 Claude CLI
    PECKER_MAX_CONCURRENT=2             同时评审数上限(防公共账号 rate limit)
    PECKER_WEB_PASSWORD=xxx             可选,Web 访问密码
    PECKER_READONLY_USERS=a,b           可选,只读 reviewer 白名单
    PECKER_SIGNATURE_SECRET=xxx         必须,ReviewResult 防篡改 HMAC 密钥
    PECKER_JWT_SECRET=xxx               必须,登录 cookie JWT 密钥
    WIKI_PATH=./shared-wiki             可选,wiki 目录
    PECKER_FENGNIAO_WIKI_PATH / PECKER_FENGNIAO_KNOWLEDGE_PATH / PECKER_FENGNIAO_SOURCE_ROOTS 可选,小助手风鸟依据查询
    FEISHU_APP_ID / FEISHU_APP_SECRET / FEISHU_REPORT_CHAT_ID  可选
"""
from __future__ import annotations

import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from api.control_plane_health import build_control_plane_health

# 在 import 任何啄木鸟业务模块前先加载 .env。
# 已由 systemd / CI / pytest 显式设置的环境变量优先,避免 .env 覆盖运行时注入的 secret。
_PROJECT_ROOT = Path(__file__).parent.parent
load_dotenv(_PROJECT_ROOT / ".env", override=False)

# 确保业务模块可 import(project root 在 sys.path)
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


def _validate_llm_runtime():
    """按 model_routes.yaml 校验真实启用中的 LLM 运行方式,不回显任何密钥。"""
    errors = []
    warnings = []
    auth = {
        "status": "unknown",
        "routes_file": "",
        "active_routes": [],
    }

    try:
        from model_router import get_route_config

        cfg = get_route_config(force_reload=True)
        auth["routes_file"] = cfg.routes_path
        active_pairs = set()
        active_route_ids_by_pair = {}
        for route_id, route in cfg.routes.items():
            if route.get("enabled", True):
                pair = (route.get("vendor", ""), route.get("transport", ""))
                active_pairs.add(pair)
                active_route_ids_by_pair.setdefault(pair, []).append(route_id)
        auth["active_routes"] = sorted(
            f"{vendor}:{transport}" for vendor, transport in active_pairs
        )
    except Exception as exc:
        errors.append(f"模型路由配置不可用: {type(exc).__name__}: {exc}")
        auth["status"] = "error"
        return errors, warnings, auth

    active = set(auth["active_routes"])
    if "openai:native" in active and not (
        os.environ.get("OPENAI_API_KEY") or os.environ.get("API_KEY")
    ):
        errors.append("OPENAI_API_KEY/API_KEY 未设置 — 团队版 GPT API 路由无法发起评审")

    if "openai:cli" in active:
        try:
            from clients.codex_cli import _find_codex_entry

            _node_bin, codex_js = _find_codex_entry()
            if not codex_js:
                errors.append("找不到 Codex CLI — 本地开发模式需先安装并登录 Codex")
        except Exception as exc:
            errors.append(f"Codex CLI 自检失败: {type(exc).__name__}: {exc}")

    if "anthropic:cli" in active:
        import shutil

        if not shutil.which("claude"):
            errors.append("找不到 Claude CLI — 本地开发模式需先安装并登录 Claude Code")

    if "anthropic:native" in active and not (
        os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("API_KEY")
    ):
        errors.append("ANTHROPIC_API_KEY/API_KEY 未设置 — Anthropic API 路由不可用")

    if "deepseek:native" in active and not os.environ.get("DEEPSEEK_API_KEY"):
        deepseek_route_ids = active_route_ids_by_pair.get(("deepseek", "native"), [])
        if deepseek_route_ids and all(str(route_id).startswith("fallback.") for route_id in deepseek_route_ids):
            warnings.append("DEEPSEEK_API_KEY 未设置 — DeepSeek 备选路由不可用,主 OpenAI 路由仍可启动")
        else:
            errors.append("DEEPSEEK_API_KEY 未设置 — DeepSeek API 路由不可用")

    auth["status"] = "ok" if not errors else "error"
    return errors, warnings, auth


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动时做必要的 env var 校验,缺失关键密钥直接拒绝启动。"""
    errors, warnings, llm_auth = _validate_llm_runtime()
    app.state.llm_auth = llm_auth
    # 兼容旧前端/脚本读取字段,不再代表 Claude 专属鉴权。
    app.state.claude_auth = llm_auth.get("status", "unknown")

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
async def health(request: Request):
    """Liveness probe — 附带 LLM 路由鉴权自检结果,不暴露密钥。"""
    return {
        "status": "ok",
        "service": "pecker-api",
        "version": "2.0.0",
        "llm_auth": getattr(request.app.state, "llm_auth", {"status": "unknown"}),
        "claude_auth": getattr(request.app.state, "claude_auth", "unknown"),
        "control_plane": build_control_plane_health(),
    }


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

from api.routes import workspaces, drafts, audit, review, review_jobs, review_history, reports, feishu, auth, metrics, feedback, admin_usage, fengniao_assistant
app.include_router(workspaces.router, prefix="/api")
app.include_router(drafts.router, prefix="/api")
app.include_router(audit.router, prefix="/api")
app.include_router(review.router, prefix="/api")
app.include_router(review_jobs.router, prefix="/api")
app.include_router(review_history.router, prefix="/api")
app.include_router(reports.router, prefix="/api")
app.include_router(feishu.router, prefix="/api")
app.include_router(auth.router, prefix="/api")
app.include_router(metrics.router, prefix="/api")
app.include_router(feedback.router, prefix="/api")
app.include_router(admin_usage.router, prefix="/api")
app.include_router(fengniao_assistant.router, prefix="/api")
