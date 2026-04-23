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
from api.budget_gate import budget_status_snapshot, check_budget, record_review_cost
from api.models import ConfirmRequest, ReviewResult, verify_review_result
from api.stream import ReviewProgressEmitter, sse_review_pipeline
from api.workspace_acl import require_workspace_access

# 预检 wiki scan 缓存(同一 workspace 10 分钟内复用)
_wiki_scan_cache: Dict[str, Any] = {}
_WIKI_CACHE_TTL = 600

from logger import get_logger
log = get_logger("review_api")

router = APIRouter(tags=["review"])


# ============================================================
# Phase 2 辅助: 全员失败分类(P0-1,抽出来便于单测)
# ============================================================

def classify_worker_failures(workers_list: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """检查 workers 结果列表,如果全员失败返回 review_failed 的 payload,否则返回 None

    Returns:
        None: 没有全员失败(正常路径继续)
        dict: {
            "reason": "quota_exhausted" | "all_workers_failed",
            "message": 给用户看的中文消息,
            "failed_count": int,
            "total_count": int,
            "worker_errors": [{"dim": ..., "error": ...}, ...],
        }
    """
    if not workers_list:
        return None
    failed_workers = [w for w in workers_list if w.get("error")]
    failed_count = len(failed_workers)
    total_count = len(workers_list)
    if failed_count != total_count:
        return None  # 部分失败不是全员失败

    def _is_quota_err(w: Dict[str, Any]) -> bool:
        e = w.get("error") or ""
        return "hit your limit" in e or "配额" in e or "QuotaExhausted" in e

    all_quota = all(_is_quota_err(w) for w in failed_workers)
    reason = "quota_exhausted" if all_quota else "all_workers_failed"
    message = (
        "Claude CLI 配额已用完,请稍后重试或联系管理员"
        if all_quota
        else f"全部 {total_count} 个 worker 失败,请重试"
    )
    worker_errors_summary = [
        {"dim": w.get("dimension", "?"), "error": (w.get("error") or "")[:200]}
        for w in failed_workers
    ]
    return {
        "reason": reason,
        "message": message,
        "failed_count": failed_count,
        "total_count": total_count,
        "worker_errors": worker_errors_summary,
    }


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
    # 2026-04-23 C: prompt injection 扫描结果 (warn-only, 不阻塞评审)
    # 结构: {risk: bool, hit_count: int, unique_tags: int?, hits: [{tag, line, excerpt}]}
    injection_scan: Optional[Dict[str, Any]] = None


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
async def precheck(
    req: PrecheckRequest,
    project_root: Path = Depends(get_project_root),
    user: dict = Depends(get_current_user),
):
    """Phase 1 预检: wiki 扫描 + Claude 知识盲区分析。

    两步:
    1. 本地扫 wiki 目录(无 LLM 调用,<1s) — 10 分钟内复用缓存
    2. 调 Claude Sonnet 做知识盲区分析(~10s)

    预检不走 semaphore(短且只读),只对正式评审做并发保护。
    """
    import time as _time
    ws_dir = get_workspace_dir(req.workspace)
    require_workspace_access(ws_dir, user)
    wiki_path = ws_dir / "wiki"
    if not wiki_path.is_dir():
        wiki_path = project_root / "shared-wiki"

    # 预检缓存:同一 workspace 10 分钟内复用 wiki scan 结果
    cache_key = req.workspace
    cached = _wiki_scan_cache.get(cache_key)
    if cached and (_time.time() - cached["ts"]) < _WIKI_CACHE_TTL:
        wiki_scan = cached["result"]
    else:
        # wiki 扫描含 os.listdir + 多个 read_text, 放线程池避免阻塞 event loop
        wiki_scan = await asyncio.to_thread(_scan_wiki_for_prd, req.prd_content, wiki_path)
        _wiki_scan_cache[cache_key] = {"result": wiki_scan, "ts": _time.time()}

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

        # 预检成本计入每日预算(防 precheck 端点被无限刷 → 逃票)
        try:
            from api_adapter import compute_call_cost_usd
            _cost = compute_call_cost_usd(MODEL_TIERS["sonnet"], response.usage)
            record_review_cost(project_root, _cost, user.get("reviewer", ""))
        except Exception:
            pass  # 记账失败不阻塞预检
    except Exception as e:
        # 预检失败不阻塞流程,返回本地 wiki 扫描结果
        llm_result = {"strong": [], "weak": [], "gaps": [f"预检失败: {str(e)[:100]}"]}

    # 2026-04-23 C: 扫 PRD + raw_materials 里的 prompt injection pattern
    from prompt_injection_scanner import scan_inputs
    injection_scan = scan_inputs(req.prd_content, req.raw_materials)
    if injection_scan.get("risk"):
        log.warning(
            f"[precheck][{req.workspace}] 检测到 prompt injection 风险: "
            f"{injection_scan['hit_count']} 处命中 {injection_scan.get('unique_tags')} 种 pattern"
        )

    # 合并本地 + LLM 结果
    return PrecheckResponse(
        strong=wiki_scan["strong"] + llm_result.get("strong", []),
        weak=wiki_scan["weak"] + llm_result.get("weak", []),
        gaps=llm_result.get("gaps", []),
        wiki_pages=wiki_scan["wiki_pages"],
        injection_scan=injection_scan,
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
async def run_review(
    req: ReviewRequest,
    request: Request,
    user: dict = Depends(get_current_user),
):
    """Phase 2 评审 (SSE 流): 4 worker 并行 + 终审交叉校验。

    事件序列:
    - uploaded → wiki_scanned → workers_started
    - worker_done × 4 (15% → 70%)
    - final_reviewer_started → final_reviewer_done
    - result (最终 payload) 或 error

    客户端断开时 cancel 主任务,semaphore 在 finally 释放。
    """
    ws_dir = get_workspace_dir(req.workspace)  # 校验 workspace 合法
    require_workspace_access(ws_dir, user)

    # 预算卡: 超限直接 429 阻止新评审
    budget_status = check_budget(get_project_root())

    # 绝对路径作为 workspace 显式参数下传给 parallel_review, 不再写 os.environ.
    # 历史上用 env var 传递会让 2 个并发 review 互污染 rule_perf_history 查询
    # (dimensions._get_rule_perf_history_path 已改为优先读参数,env 作 CLI 回退).
    ws_abs_path = str(get_project_root() / req.workspace)

    emitter = ReviewProgressEmitter()
    client = get_client()

    async def _pipeline():
        """评审主任务:parallel_review + goshawk,完成后 return 最终 payload。"""
        import time as _time
        _pipeline_start = _time.time()

        from parallel_review import parallel_review, parallel_review_sync
        from goshawk_advisor import advisor_review_async
        from agent_config import MODEL_TIERS

        # Pattern 21: Session Event Sourcing — JSONL 追加写入事件溯源
        from event_store import EventStore
        import uuid
        review_id = f"rev_{int(_pipeline_start)}_{uuid.uuid4().hex[:6]}"
        evt = EventStore(workspace=ws_abs_path, review_id=review_id)
        # 2026-04-23 C: injection scan 写到 review_started event 做事后审计
        from prompt_injection_scanner import scan_inputs
        _inj = scan_inputs(req.prd_content, req.raw_materials, req.user_notes)
        if _inj.get("risk"):
            log.warning(
                f"[review][{req.workspace}] prompt injection risk on run: "
                f"{_inj['hit_count']} hits / {_inj.get('unique_tags')} tags"
            )
        evt.append("review_started", {
            "prd_name": req.prd_name,
            "mode": req.mode,
            "reviewer": req.reviewer,
            "wiki_pages_count": len(req.wiki_pages),
            "injection_scan": _inj,
        })

        # 1. 构建增强 PRD
        enhanced_prd = req.prd_content
        if req.raw_materials:
            enhanced_prd += "\n\n---\n## 补充业务资料\n\n" + "\n---\n".join(req.raw_materials)
        if req.user_notes:
            enhanced_prd += f"\n\n---\n## 评审人补充说明\n\n{req.user_notes}"

        emitter.emit("uploaded")
        emitter.emit("wiki_scanned", data={"page_count": len(req.wiki_pages)})
        emitter.emit("workers_started", data={"mode": req.mode})
        evt.append("workers_started", {"mode": req.mode})

        # 2. 并行评审 (semaphore 保护)
        async with review_semaphore:
            # Per-tool-call trace callback (2026-04-23 B 优化):
            # 每次 worker / goshawk 里的 client.create 返回后会调用, trace 写
            # EventStore 的 tool_call_done 事件, 给 stability_metrics 聚合用.
            def _on_tool_call(trace):
                try:
                    evt.append("tool_call_done", trace)
                except Exception:
                    pass

            if req.mode == "quick":
                # 快速模式:全 sonnet,不显示 per-worker 进度细节
                quick_tiers = {k: MODEL_TIERS["sonnet"] for k in MODEL_TIERS}
                import functools
                loop = asyncio.get_running_loop()
                result = await loop.run_in_executor(
                    None,
                    functools.partial(
                        parallel_review_sync, client, enhanced_prd,
                        req.wiki_pages, quick_tiers, workspace=ws_abs_path,
                        on_tool_call=_on_tool_call,
                    ),
                )
            else:
                def _on_worker_done(dim, r):
                    emitter.emit_worker_done(dim, r)
                    # Pattern 21: 记录每个 worker 完成事件 (P1-3 补 telemetry)
                    telemetry = r.get("telemetry") if isinstance(r, dict) else None
                    evt.append("worker_done", {
                        "dim": dim,
                        "items_count": len(r.get("items", [])) if isinstance(r, dict) else 0,
                        "error": str(r.get("error", ""))[:200] if isinstance(r, dict) and "error" in r else None,
                        # P1-3: 持久化 cost/时长/token 用量，支持事后成本分析和性能回归
                        "duration_ms": telemetry.get("duration_ms") if telemetry else None,
                        "input_tokens": telemetry.get("input_tokens") if telemetry else None,
                        "output_tokens": telemetry.get("output_tokens") if telemetry else None,
                        "cost_usd": telemetry.get("cost_usd") if telemetry else r.get("cost_usd") if isinstance(r, dict) else None,
                        "model": telemetry.get("model") if telemetry else r.get("model_used") if isinstance(r, dict) else None,
                        "degraded": telemetry.get("degraded") if telemetry else None,
                        # Round 2: 空提交重试分支 telemetry,后续由 generate_status 聚合
                        "empty_retry_used": telemetry.get("empty_retry_used") if telemetry else None,
                        "turns_used": telemetry.get("turns_used") if telemetry else None,
                    })

                result = await parallel_review(
                    client, enhanced_prd, req.wiki_pages, MODEL_TIERS,
                    on_worker_done=_on_worker_done, workspace=ws_abs_path,
                    on_tool_call=_on_tool_call,
                )

            items = result.get("merged_items", [])
            # Pattern 21: workers 全部完成后 checkpoint
            evt.append("checkpoint", {"workers_done": len(result.get("workers", [])), "items_count": len(items)})

            # P0-1: 全员失败 abort — 所有 worker 都出错时,发 review_failed 不走正常完成路径
            workers_list = result.get("workers", [])
            failure_payload = classify_worker_failures(workers_list)
            if failure_payload is not None:
                emitter.emit("review_failed", data=failure_payload)
                evt.append("review_failed", failure_payload)
                # 直接返回失败标记,不走 ReviewResult.create (避免用户基于 0-items 做下游决策)
                return {
                    "status": "failed",
                    **failure_payload,
                }

            # 部分失败 + 无 items 的降级提示(非 abort,仅告警)
            failed_count = sum(1 for w in workers_list if w.get("error"))
            total_count = len(workers_list)
            if failed_count > 0 and len(items) == 0:
                emitter.emit("review_degraded", data={
                    "failed_count": failed_count,
                    "total_count": total_count,
                    "message": f"部分 worker 失败({failed_count}/{total_count}),未获得任何评审项,建议重试",
                })
                evt.append("review_degraded", {
                    "failed_count": failed_count,
                    "total_count": total_count,
                })

            # 3. 终审 (苍鹰) — 仅标准模式
            if req.mode == "standard" and items:
                emitter.emit("final_reviewer_started")
                evt.append("final_reviewer_started", {"items_count": len(items)})
                try:
                    goshawk_result = await advisor_review_async(
                        client, enhanced_prd, items, req.wiki_pages,
                        on_tool_call=_on_tool_call,
                    )
                    from goshawk_advisor import apply_advisor_result
                    items = apply_advisor_result(items, goshawk_result, wiki_pages=req.wiki_pages, client=client)
                    result["merged_items"] = items
                    result["goshawk"] = goshawk_result
                    # Round 8: 把 goshawk verdict + retry 信号持久化到 jsonl,
                    # 让 STATUS 能聚合 SILENT/EMPTY_APPROVAL/REVIEWED 分布
                    emitter.emit("final_reviewer_done", data={
                        "false_positive": len(goshawk_result.get("flagged_as_false_positive", [])),
                        "additional": len(goshawk_result.get("additional_findings", [])),
                        "verdict": goshawk_result.get("verdict", "UNKNOWN"),
                    })
                    evt.append("final_reviewer_done", {
                        "false_positive": len(goshawk_result.get("flagged_as_false_positive", [])),
                        "additional": len(goshawk_result.get("additional_findings", [])),
                        "verdict": goshawk_result.get("verdict", "UNKNOWN"),
                        "confidence": goshawk_result.get("confidence", 0.0),
                        "empty_retry_used": goshawk_result.get("empty_retry_used", False),
                    })
                except Exception as e:
                    emitter.emit("final_reviewer_done", data={"error": str(e)[:200]})
                    evt.append("final_reviewer_done", {"error": str(e)[:200]})

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

        # 预算卡: append 本次实际成本到 logs/daily_cost_*.jsonl
        try:
            record_review_cost(get_project_root(), total_cost, req.reviewer)
        except Exception as _e:
            log.warning(f"[budget] record_review_cost 失败,不阻塞: {_e}")

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

        # Pattern 21: review 完成事件(带 result 摘要 + 预算状态,给运维/前端 visibility)
        _budget_after = budget_status_snapshot(get_project_root())
        evt.append("review_completed", {
            "review_id": review_result_handle.review_id,
            "items_count": len(result.get("merged_items", [])),
            "total_cost_usd": cost_breakdown.get("total", 0),
            "duration_ms": int((_time.time() - _pipeline_start) * 1000),
            "budget": _budget_after,
        })

        return review_result_handle.model_dump()

    async def event_source():
        async for chunk in sse_review_pipeline(
            emitter,
            _pipeline(),
            is_disconnected=request.is_disconnected,
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

def _update_rule_perf_from_decisions(
    items: List[Dict[str, Any]],
    decisions: Dict[str, Dict[str, Any]],
    workspace: str,
):
    """P0.1: 把 Web 端 Y/N/E 决策回流到 rule_performance_history.json

    遍历 items,只处理有 rule_id 的条目:
    - accept → confirmed +1
    - reject → rejected +1
    - edit   → confirmed +1 (编辑意味着认可问题但修改了措辞)

    无 rule_id 的 item 无法归因到具体规则,跳过。
    """
    from rule_perf_store import RulePerformanceHistoryStore
    store = RulePerformanceHistoryStore(get_project_root() / workspace)
    history_data: Dict[str, Any] = store.load()

    # 统计日志用计数器
    total_decisions = len(decisions)
    has_rule_id = 0
    updated_rules = 0

    # 建 item_id → item 的索引
    item_map = {item.get("id", ""): item for item in items}

    for item_id, decision in decisions.items():
        item = item_map.get(item_id)
        if not item:
            continue
        rule_id = (item.get("rule_id") or "").strip()
        if not rule_id:
            continue  # 没有 rule_id 无法归因,跳过
        has_rule_id += 1
        action = decision.get("action", "")

        # 初始化规则条目
        if rule_id not in history_data:
            history_data[rule_id] = {
                "name": item.get("dimension", ""),
                "history": [],
                "stats": {"confirmed": 0, "rejected": 0, "missed": 0, "total": 0},
                "rejection_rate": 0.0,
                "impact_score": 0.5,
                "is_noisy": False,
            }

        entry = history_data[rule_id]

        # 更新统计
        if action == "accept":
            entry["stats"]["confirmed"] += 1
        elif action == "reject":
            entry["stats"]["rejected"] += 1
        elif action == "edit":
            entry["stats"]["confirmed"] += 1  # 编辑 = 认可问题

        entry["stats"]["total"] += 1

        # EMA 更新 impact_score (时间衰减版 — 2026-04-23 #2)
        # 老数据按半衰期向 neutral(0.5) 回归, 让新数据权重更大
        from rule_perf_decay import ema_with_time_decay
        old_score = entry.get("impact_score", 0.5)
        last_ts = entry.get("last_update_ts")  # None 或 unix epoch
        if action == "accept":
            delta = 1.0
        elif action == "edit":
            delta = 0.7
        elif action == "reject":
            delta = -0.5
        else:
            delta = 0.0
        import time as _time
        now_ts = _time.time()
        new_score = ema_with_time_decay(old_score, last_ts, delta, now_ts=now_ts)
        entry["impact_score"] = round(new_score, 3)
        entry["last_update_ts"] = int(now_ts)

        # 更新驳回率和噪声标记
        total = entry["stats"]["total"]
        rejected_count = entry["stats"]["rejected"]
        entry["rejection_rate"] = round(rejected_count / total, 3) if total > 0 else 0.0
        entry["is_noisy"] = entry["rejection_rate"] > 0.4

        updated_rules += 1

    # 写回 (store.save 内部处理 mkdir + atomic write)
    if updated_rules > 0:
        store.save(history_data)

    log.info(
        f"[决策回流] 本次评审 {total_decisions} 条决策中 "
        f"{has_rule_id} 条有 rule_id,更新了 {updated_rules} 条规则的 impact_score"
    )


def _save_eval_ground_truth(
    items: List[Dict[str, Any]],
    decisions: Dict[str, Dict[str, Any]],
    workspace: str,
    reviewer: str,
):
    """把 Phase 3 的 Y/N/E 决策保存为 Eval ground truth

    格式: eval/ground_truth/{workspace}_{reviewer}_{timestamp}.json
    积累的人类标注可以直接喂给 cuckoo_eval.py 做回归测试。
    """
    import time as _time

    # 建 item_id -> item 索引
    item_map = {item.get("id", ""): item for item in items}

    gt_items = []
    for item_id, decision in decisions.items():
        item = item_map.get(item_id)
        if not item:
            continue
        action = decision.get("action", "")
        gt_items.append({
            "id": item_id,
            "rule_id": item.get("rule_id", ""),
            "location": item.get("location", ""),
            "severity": item.get("severity", ""),
            "action": action,
            "is_true_positive": action in ("accept", "edit"),
        })

    if not gt_items:
        return

    timestamp = int(_time.time())
    # 清理 workspace 名(去掉 workspace- 前缀方便文件名)
    ws_short = workspace.replace("workspace-", "") if workspace.startswith("workspace-") else workspace
    filename = f"{ws_short}_{reviewer}_{timestamp}.json"

    gt_dir = os.path.join(str(get_project_root()), "eval", "ground_truth")
    os.makedirs(gt_dir, exist_ok=True)

    gt_payload = {
        "workspace": workspace,
        "reviewer": reviewer,
        "timestamp": timestamp,
        "items": gt_items,
    }

    gt_path = os.path.join(gt_dir, filename)
    with open(gt_path, "w", encoding="utf-8") as f:
        json.dump(gt_payload, f, ensure_ascii=False, indent=2)

    log.info(f"[ground_truth] 保存 {len(gt_items)} 条标注到 {gt_path}")


@router.post("/review/confirm")
async def confirm_review(req: ConfirmRequest, user: dict = Depends(get_current_user)):
    """Phase 3 提交用户 Y/N/E 决策。先验证 signature 防篡改,再返回可生成报告的标志。

    真正的报告生成在 /api/reports/{workspace}/save-to-wiki 或前端直接拼接,
    这里只做 signature 校验 + 决策计数 + 规则历史回流。
    """
    # Step 1: 验证 opaque handle signature
    verify_review_result(req.review_result)

    # ACL: workspace 取自已签名的 review_result(signature 不覆盖 workspace,但 review_id 唯一性
    # + items 签名已挡住了"换一份 review 结果"的攻击; 这里只挡"换 workspace 写 rule_perf"的情况)
    _ws_name = (req.review_result.get("workspace") or "").strip()
    if _ws_name:
        _ws_dir = get_workspace_dir(_ws_name)
        require_workspace_access(_ws_dir, user)

    # Step 2: 统计决策
    decisions = req.decisions
    accepted = sum(1 for d in decisions.values() if d.get("action") == "accept")
    rejected = sum(1 for d in decisions.values() if d.get("action") == "reject")
    edited = sum(1 for d in decisions.values() if d.get("action") == "edit")

    items = req.review_result.get("items", [])
    pending = len(items) - len(decisions)

    # Step 3: P0.1 — 决策回流到 rule_performance_history
    # 这两个函数含同步文件 I/O (open/json.dump), 放线程池避免阻塞 event loop
    workspace = req.review_result.get("workspace", "")
    if workspace and decisions:
        try:
            await asyncio.to_thread(
                _update_rule_perf_from_decisions, items, decisions, workspace,
            )
        except Exception as e:
            log.warning(f"[决策回流] 写入失败,不阻塞确认流程: {e}")

    # Step 4: 保存 Eval ground truth(人类标注 -> 回归测试)
    reviewer = req.review_result.get("reviewer", "unknown")
    if workspace and decisions:
        try:
            await asyncio.to_thread(
                _save_eval_ground_truth, items, decisions, workspace, reviewer,
            )
        except Exception as e:
            log.warning(f"[ground_truth] 保存失败,不阻塞确认流程: {e}")

    return {
        "status": "confirmed",
        "review_id": req.review_result.get("review_id"),
        "accepted": accepted,
        "rejected": rejected,
        "edited": edited,
        "pending": pending,
        "total": len(items),
    }
