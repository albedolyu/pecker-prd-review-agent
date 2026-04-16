"""POST /api/review/precheck — 知识盲区预检 (非流式, ~15s)
POST /api/review/run — 4 worker 并行评审 + 终审 (SSE 流式, 90-150s)

两个端点都共享同一个 `asyncio.Semaphore` 保护公共账号 rate limit。
"""
from __future__ import annotations

import asyncio
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from api.deps import (
    get_client,
    get_current_user,
    get_project_root,
    get_workspace_dir,
    review_semaphore,
)
from api.models import ConfirmRequest, ReviewResult, verify_review_result
from api.stream import ReviewProgressEmitter, sse_review_pipeline

router = APIRouter(tags=["review"])


# ============================================================
# 预检 (Phase 1): 扫 wiki + Claude 知识盲区分析
# ============================================================

class PrecheckRequest(BaseModel):
    prd_content: str = Field(..., min_length=1, max_length=500_000)
    raw_materials: List[str] = Field(default_factory=list)
    workspace: str = Field(..., description="workspace-* 目录名")


class PrecheckResponse(BaseModel):
    strong: List[str]
    weak: List[str]
    gaps: List[str]
    wiki_pages: Dict[str, str]  # 页面标题 → 内容


def _scan_wiki_for_prd(prd_content: str, wiki_path: Path) -> Dict[str, Any]:
    """扫 wiki 目录,返回相关页面(复用 app.py:scan_wiki_for_prd 的逻辑)。"""
    if not wiki_path.is_dir():
        return {"strong": [], "weak": [], "gaps": [], "wiki_pages": {}}

    # 提取 PRD 关键词
    prd_keywords = set(re.findall(r'[\u4e00-\u9fff]{2,4}', prd_content[:3000]))
    stop = {"文档", "说明", "需求", "版本", "内容", "数据", "系统", "功能", "用户",
            "信息", "通过", "支持", "进行", "使用", "相关", "以下", "如下", "其中"}
    prd_keywords -= stop

    wiki_pages: Dict[str, str] = {}
    strong: List[str] = []
    weak: List[str] = []

    for fname in os.listdir(wiki_path):
        if not fname.endswith(".md") or fname in ("index.md", "log.md", "_scratchpad.md"):
            continue
        fpath = wiki_path / fname
        try:
            content = fpath.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        page_name = fname.replace(".md", "")
        wiki_pages[page_name] = content

        hits = sum(1 for kw in list(prd_keywords)[:30] if kw in fname or kw in content[:500])
        if hits >= 3:
            strong.append(f"[[{page_name}]] — 命中 {hits} 个关键词")
        elif hits >= 1:
            weak.append(f"[[{page_name}]] — 命中 {hits} 个关键词")

    return {"strong": strong, "weak": weak, "gaps": [], "wiki_pages": wiki_pages}


@router.post("/review/precheck", response_model=PrecheckResponse)
async def precheck(req: PrecheckRequest, project_root: Path = Depends(get_project_root)):
    """Phase 1 预检: wiki 扫描 + Claude 知识盲区分析。

    两步:
    1. 本地扫 wiki 目录(无 LLM 调用,<1s)
    2. 调 Claude Sonnet 做知识盲区分析(~10s)

    预检不走 semaphore(短且只读),只对正式评审做并发保护。
    """
    ws_dir = get_workspace_dir(req.workspace)
    wiki_path = ws_dir / "wiki"
    if not wiki_path.is_dir():
        wiki_path = project_root / "shared-wiki"

    wiki_scan = _scan_wiki_for_prd(req.prd_content, wiki_path)

    # 调 Claude 做 gap 分析
    try:
        client = get_client()
        context = f"PRD 内容:\n{req.prd_content[:3000]}"
        if req.raw_materials:
            context += "\n\n补充资料:\n" + "\n---\n".join(t[:1000] for t in req.raw_materials)

        from agent_config import MODEL_TIERS
        response = client.create(
            model=MODEL_TIERS["sonnet"],
            max_tokens=2048,
            system='''你是啄木鸟知识盲区预检模块。分析 PRD 内容,输出以下 3 类信息(JSON 格式):
{
  "strong": ["强相关的已知知识点"],
  "weak": ["弱相关的知识点"],
  "gaps": ["知识盲区——PRD 涉及但你没有足够信息判断的领域"]
}
每类最多 5 条。盲区要具体说明缺什么信息。''',
            messages=[{"role": "user", "content": context}],
        )
        text = response.content[0].text if response.content else "{}"
        m = re.search(r'\{[\s\S]*\}', text)
        llm_result = json.loads(m.group()) if m else {"strong": [], "weak": [], "gaps": []}
    except Exception as e:
        # 预检失败不阻塞流程,返回本地 wiki 扫描结果
        llm_result = {"strong": [], "weak": [], "gaps": [f"预检失败: {str(e)[:100]}"]}

    # 合并本地 + LLM 结果
    return PrecheckResponse(
        strong=wiki_scan["strong"] + llm_result.get("strong", []),
        weak=wiki_scan["weak"] + llm_result.get("weak", []),
        gaps=llm_result.get("gaps", []),
        wiki_pages=wiki_scan["wiki_pages"],
    )


# ============================================================
# 正式评审 (Phase 2): SSE 流式,受 semaphore 保护
# ============================================================

class ReviewRequest(BaseModel):
    prd_content: str = Field(..., min_length=1, max_length=500_000)
    raw_materials: List[str] = Field(default_factory=list)
    user_notes: str = ""
    workspace: str
    prd_name: str = "unknown"
    reviewer: str = "unknown"
    mode: str = Field("standard", pattern="^(standard|quick)$")
    wiki_pages: Dict[str, str] = Field(default_factory=dict)


@router.post("/review/run")
async def run_review(req: ReviewRequest, request: Request):
    """Phase 2 评审 (SSE 流): 4 worker 并行 + 终审交叉校验。

    事件序列:
    - uploaded → wiki_scanned → workers_started
    - worker_done × 4 (15% → 70%)
    - final_reviewer_started → final_reviewer_done
    - result (最终 payload) 或 error

    客户端断开时 cancel 主任务,semaphore 在 finally 释放。
    """
    get_workspace_dir(req.workspace)  # 校验 workspace 合法

    # 注入 WORKSPACE env var(parallel_review 延迟解析会读)
    os.environ["WORKSPACE"] = str(get_project_root() / req.workspace)

    emitter = ReviewProgressEmitter()
    client = get_client()

    async def _pipeline():
        """评审主任务:parallel_review + goshawk,完成后 return 最终 payload。"""
        import time as _time
        _pipeline_start = _time.time()

        from parallel_review import parallel_review, parallel_review_sync
        from goshawk_advisor import advisor_review_async
        from agent_config import MODEL_TIERS

        # 1. 构建增强 PRD
        enhanced_prd = req.prd_content
        if req.raw_materials:
            enhanced_prd += "\n\n---\n## 补充业务资料\n\n" + "\n---\n".join(req.raw_materials)
        if req.user_notes:
            enhanced_prd += f"\n\n---\n## 评审人补充说明\n\n{req.user_notes}"

        emitter.emit("uploaded")
        emitter.emit("wiki_scanned", data={"page_count": len(req.wiki_pages)})
        emitter.emit("workers_started", data={"mode": req.mode})

        # 2. 并行评审 (semaphore 保护)
        async with review_semaphore:
            if req.mode == "quick":
                # 快速模式:全 sonnet,不显示 per-worker 进度细节
                quick_tiers = {k: MODEL_TIERS["sonnet"] for k in MODEL_TIERS}
                import functools
                loop = asyncio.get_running_loop()
                result = await loop.run_in_executor(
                    None,
                    functools.partial(parallel_review_sync, client, enhanced_prd, req.wiki_pages, quick_tiers),
                )
            else:
                result = await parallel_review(
                    client, enhanced_prd, req.wiki_pages, MODEL_TIERS,
                    on_worker_done=lambda dim, r: emitter.emit_worker_done(dim, r),
                )

            items = result.get("merged_items", [])

            # 3. 终审 (苍鹰) — 仅标准模式
            if req.mode == "standard" and items:
                emitter.emit("final_reviewer_started")
                try:
                    goshawk_result = await advisor_review_async(
                        client, enhanced_prd, items, req.wiki_pages
                    )
                    from goshawk_advisor import apply_advisor_result
                    items = apply_advisor_result(items, goshawk_result, wiki_pages=req.wiki_pages)
                    result["merged_items"] = items
                    result["goshawk"] = goshawk_result
                    emitter.emit("final_reviewer_done", data={
                        "false_positive": len(goshawk_result.get("flagged_as_false_positive", [])),
                        "additional": len(goshawk_result.get("additional_findings", [])),
                    })
                except Exception as e:
                    emitter.emit("final_reviewer_done", data={"error": str(e)[:200]})

        # 成本归因聚合 (CC cost-tracker querySource 模式)
        cost_breakdown = {}
        total_cost = 0.0
        for w in result.get("workers", []):
            dim = w.get("dimension", "unknown")
            c = w.get("cost_usd", 0.0)
            cost_breakdown[dim] = round(c, 6)
            total_cost += c
        # 苍鹰成本(从 goshawk result 的 usage 计算)
        goshawk_res = result.get("goshawk")
        if goshawk_res and goshawk_res.get("usage"):
            from api_adapter import compute_call_cost_usd
            gc = compute_call_cost_usd(
                goshawk_res.get("model_used", "claude-opus-4-6"),
                goshawk_res["usage"],
            )
            cost_breakdown["goshawk"] = round(gc, 6)
            total_cost += gc
        cost_breakdown["total"] = round(total_cost, 6)
        result["cost_breakdown"] = cost_breakdown

        # 3c: 结构化 telemetry 汇总 (CC telemetry 模式)
        import time as _time
        worker_telemetry = {}
        for w in result.get("workers", []):
            dim = w.get("dimension", "unknown")
            if w.get("telemetry"):
                worker_telemetry[dim] = w["telemetry"]
        result["telemetry"] = {
            "total_duration_ms": int((_time.time() - _pipeline_start) * 1000),
            "workers": worker_telemetry,
            "total_cost_usd": cost_breakdown.get("total", 0),
        }

        # 包装成 Opaque Handle (A14)
        review_result_handle = ReviewResult.create(
            reviewer=req.reviewer,
            workspace=req.workspace,
            prd_name=req.prd_name,
            mode=req.mode,
            merged_items=result.get("merged_items", []),
            workers=result.get("workers", []),
            usage=result.get("total_usage", {}),
            goshawk_summary=result.get("goshawk"),
            cost_breakdown=cost_breakdown,
        )
        return review_result_handle.model_dump()

    async def event_source():
        async for chunk in sse_review_pipeline(
            emitter,
            _pipeline(),
            is_disconnected=lambda: False,  # TODO: 接 request.is_disconnected()
        ):
            yield chunk

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # 禁 nginx 缓冲
            "Connection": "keep-alive",
        },
    )


# ============================================================
# Phase 3 确认 (Opaque Handle verify)
# ============================================================

@router.post("/review/confirm")
async def confirm_review(req: ConfirmRequest, user: dict = Depends(get_current_user)):
    """Phase 3 提交用户 Y/N/E 决策。先验证 signature 防篡改,再返回可生成报告的标志。

    真正的报告生成在 /api/reports/{workspace}/save-to-wiki 或前端直接拼接,
    这里只做 signature 校验 + 决策计数。
    """
    # Step 1: 验证 opaque handle signature
    verify_review_result(req.review_result)

    # Step 2: 统计决策
    decisions = req.decisions
    accepted = sum(1 for d in decisions.values() if d.get("action") == "accept")
    rejected = sum(1 for d in decisions.values() if d.get("action") == "reject")
    edited = sum(1 for d in decisions.values() if d.get("action") == "edit")

    items = req.review_result.get("items", [])
    pending = len(items) - len(decisions)

    return {
        "status": "confirmed",
        "review_id": req.review_result.get("review_id"),
        "accepted": accepted,
        "rejected": rejected,
        "edited": edited,
        "pending": pending,
        "total": len(items),
    }
