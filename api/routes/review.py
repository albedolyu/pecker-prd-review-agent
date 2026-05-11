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
    get_max_concurrent,
    get_project_root,
    get_workspace_dir,
    review_semaphore,
)
from api.budget_gate import budget_status_snapshot, check_budget, record_review_cost
from api.figma_context import enrich_figma_raw_materials
from api.models import ConfirmRequest, ReviewResult, verify_review_result
from api.sanitize import redact_text
from api.stream import ReviewProgressEmitter, emit_and_log, sse_review_pipeline
from api.workspace_acl import is_admin, require_workspace_access

# 预检 wiki scan 缓存(同一 workspace 10 分钟内复用)
_wiki_scan_cache: Dict[str, Any] = {}
_WIKI_CACHE_TTL = 600

from logger import get_logger
log = get_logger("review_api")

router = APIRouter(tags=["review"])


def _item_ids(items: Any) -> List[str]:
    if not isinstance(items, list):
        return []
    return [str(item.get("id")) for item in items if isinstance(item, dict) and item.get("id")]


def _recover_review_result_from_job_store(
    submitted_result: Dict[str, Any],
    *,
    user: dict,
) -> Optional[Dict[str, Any]]:
    """Recover a trusted result handle from the in-memory job store.

    This is intentionally narrow: if a reconnect draft carries a stale or
    browser-mutated handle, only a server-side completed job with the same
    review_id and item ids can be used as the source of truth.
    """
    review_id = str((submitted_result or {}).get("review_id") or "")
    if not review_id:
        return None

    try:
        from api.review_jobs import review_job_store

        jobs = review_job_store.list_jobs(
            owner=str((user or {}).get("reviewer") or ""),
            admin=is_admin(user),
            limit=200,
        )
    except Exception:
        return None

    submitted_ids = _item_ids((submitted_result or {}).get("items"))
    for job in jobs:
        if not isinstance(job, dict):
            continue
        if job.get("status") != "done":
            continue
        result = job.get("result")
        if not isinstance(result, dict):
            continue
        if result.get("review_id") != review_id:
            continue
        for key in ("workspace", "reviewer", "prd_name", "mode"):
            if submitted_result.get(key) and result.get(key) != submitted_result.get(key):
                return None
        recovered_ids = _item_ids(result.get("items"))
        if submitted_ids and recovered_ids != submitted_ids:
            return None
        return result
    return None


# ============================================================
# Phase 2 辅助: worker_done event payload 构造
# ============================================================

def _summarize_wiki_selection(telemetry: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Extract compact wiki selection telemetry for event_store.

    The full telemetry can include a per-page list. worker_done events only need
    aggregate counts for latency/cost correlation, so keep the payload small.
    """
    if not isinstance(telemetry, dict):
        return None
    wiki_selection = telemetry.get("wiki_selection")
    if not isinstance(wiki_selection, dict):
        return None
    return {
        "selected_count": wiki_selection.get("selected_count", 0),
        "omitted_count": wiki_selection.get("omitted_count", 0),
        "total_chars_before": wiki_selection.get("total_chars_before", 0),
        "total_chars_after": wiki_selection.get("total_chars_after", 0),
    }


def _build_worker_done_event_payload(dim: str, result: Dict[str, Any]) -> Dict[str, Any]:
    """Build the worker_done event_store payload used by /review/run."""
    telemetry = result.get("telemetry") if isinstance(result, dict) else None
    payload = {
        "dim": dim,
        "items_count": len(result.get("items", [])) if isinstance(result, dict) else 0,
        "error": str(result.get("error", ""))[:200] if isinstance(result, dict) and "error" in result else None,
        # P1-3: 持久化 cost/时长/token 用量，支持事后成本分析和性能回归
        "duration_ms": telemetry.get("duration_ms") if telemetry else None,
        "input_tokens": telemetry.get("input_tokens", telemetry.get("tokens_in")) if telemetry else None,
        "output_tokens": telemetry.get("output_tokens", telemetry.get("tokens_out")) if telemetry else None,
        "cost_usd": telemetry.get("cost_usd") if telemetry else result.get("cost_usd") if isinstance(result, dict) else None,
        "model": telemetry.get("model") if telemetry else result.get("model_used") if isinstance(result, dict) else None,
        "degraded": telemetry.get("degraded") if telemetry else None,
        # Round 2: 空提交重试分支 telemetry,后续由 generate_status 聚合
        "empty_retry_used": telemetry.get("empty_retry_used") if telemetry else None,
        "turns_used": telemetry.get("turns_used") if telemetry else None,
        "empty_submission_confirmed": telemetry.get("empty_submission_confirmed") if telemetry else None,
        "empty_submission_reason": telemetry.get("empty_submission_reason") if telemetry else None,
    }
    wiki_selection = _summarize_wiki_selection(telemetry)
    if wiki_selection is not None:
        payload["wiki_selection"] = wiki_selection
    return payload


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
        "评审额度已用完,请联系维护人补充额度后再重新评审"
        if all_quota
        else f"全部 {total_count} 个评审方向都没有完整返回,请重新评审或联系维护人排查"
    )
    worker_errors_summary = [
        {"dim": w.get("dimension", "?"), "error": redact_text(str(w.get("error") or ""))[:200]}
        for w in failed_workers
    ]
    return {
        "reason": reason,
        "message": message,
        "failed_count": failed_count,
        "total_count": total_count,
        "worker_errors": worker_errors_summary,
    }


def build_worker_degraded_payload(
    workers_list: List[Dict[str, Any]],
    *,
    items_count: int,
) -> Optional[Dict[str, Any]]:
    """Build a non-fatal degraded review payload when some workers failed."""
    if not workers_list:
        return None
    failed_workers = [w for w in workers_list if w.get("error")]
    failed_count = len(failed_workers)
    total_count = len(workers_list)
    if failed_count == 0 or failed_count == total_count:
        return None

    if items_count > 0:
        message = (
            f"部分方向未完整返回({failed_count}/{total_count}),"
            f"已保留 {items_count} 条可用意见；可以先继续确认,如需完整结果请重新评审。"
        )
    else:
        message = (
            f"部分方向未完整返回({failed_count}/{total_count}),"
            "本轮未获得可用意见,请重新评审或联系维护人排查。"
        )

    return {
        "failed_count": failed_count,
        "total_count": total_count,
        "items_count": items_count,
        "message": message,
    }


# ============================================================
# 预检 (Phase 1): 扫 wiki + LLM 知识盲区分析
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


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)) or default)
    except ValueError:
        return default


def _copy_request_with_raw_materials(req: Any, raw_materials: List[str]) -> Any:
    if list(req.raw_materials) == list(raw_materials):
        return req
    try:
        return req.model_copy(update={"raw_materials": raw_materials})
    except AttributeError:
        return req.copy(update={"raw_materials": raw_materials})


def _call_precheck_gaps(req: PrecheckRequest):
    context = f"PRD 内容:\n{req.prd_content[:3000]}"
    if req.raw_materials:
        context += "\n\n补充资料:\n" + "\n---\n".join(t[:1000] for t in req.raw_materials)

    from model_router import route_call
    response = route_call(
        "precheck.gaps",
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
    return llm_result, response


@router.post("/review/precheck", response_model=PrecheckResponse)
async def precheck(
    req: PrecheckRequest,
    project_root: Path = Depends(get_project_root),
    user: dict = Depends(get_current_user),
):
    """Phase 1 预检: wiki 扫描 + LLM 知识盲区分析。

    两步:
    1. 本地扫 wiki 目录(无 LLM 调用,<1s) — 10 分钟内复用缓存
    2. 走 model_routes.yaml 调轻量模型做知识盲区分析

    预检不走 semaphore(短且只读),只对正式评审做并发保护。
    """
    import time as _time
    ws_dir = get_workspace_dir(req.workspace)
    require_workspace_access(ws_dir, user)
    enriched_raw_materials = await asyncio.to_thread(enrich_figma_raw_materials, req.raw_materials)
    req = _copy_request_with_raw_materials(req, enriched_raw_materials)
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

    # 预检也走 model_routes.yaml, 避免 Web 团队版回落到个人 Claude/OAT 会话。
    # LLM 盲区分析是增强项: 超时或失败时只返回本地 wiki 扫描,不把技术错误暴露给 PM。
    try:
        llm_result, response = await asyncio.wait_for(
            asyncio.to_thread(_call_precheck_gaps, req),
            timeout=max(0.1, _env_float("PECKER_PRECHECK_TIMEOUT", 90.0)),
        )

        # 预检成本计入每日预算(防 precheck 端点被无限刷 → 逃票)
        try:
            from api_adapter import compute_call_cost_usd
            _cost = compute_call_cost_usd(getattr(response, "model", ""), response.usage)
            record_review_cost(project_root, _cost, user.get("reviewer", ""))
        except Exception:
            pass  # 记账失败不阻塞预检
    except asyncio.TimeoutError:
        log.warning(
            f"[precheck][{req.workspace}] LLM 预检超过 "
            f"{_env_float('PECKER_PRECHECK_TIMEOUT', 90.0):.0f}s,已降级为本地资料库扫描"
        )
        llm_result = {"strong": [], "weak": [], "gaps": []}
    except Exception as e:
        log.warning(f"[precheck][{req.workspace}] LLM 预检失败,已降级为本地资料库扫描: {str(e)[:120]}")
        llm_result = {"strong": [], "weak": [], "gaps": []}

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
    # reviewer 字段保留供前端 draft 兼容, 但后端统一以 JWT 里的 user["reviewer"] 为准,
    # 不信任这里的值(2026-04-24 P1 修复: 防 alice 登录后在 body 里写 bob 伪造署名).
    reviewer: str = "unknown"
    mode: str = Field("standard", pattern="^(standard|quick)$")
    wiki_pages: Dict[str, str] = Field(default_factory=dict)
    session_tags: List[str] = Field(default_factory=list)


def _normalize_session_tag(tag: Any) -> str:
    text = str(tag or "").strip().lower()
    aliases = {
        "load-test": "stress",
        "load_test": "stress",
        "pressure-test": "stress",
        "pressure_test": "stress",
        "压测": "stress",
    }
    return aliases.get(text, text)


def _derive_session_tags(req: ReviewRequest, reviewer: str) -> List[str]:
    tags: List[str] = []
    for tag in req.session_tags:
        normalized = _normalize_session_tag(tag)
        if normalized and normalized not in tags:
            tags.append(normalized)

    prd_name = (req.prd_name or "").strip().lower()
    reviewer_name = (reviewer or "").strip().lower()
    if (
        prd_name.startswith("team-beta-stress-")
        or reviewer_name.startswith("stress-pm-")
    ) and "stress" not in tags:
        tags.append("stress")
    return tags


@router.post("/review/run")
async def run_review(
    req: ReviewRequest,
    request: Request,
    user: dict = Depends(get_current_user),
):
    """Phase 2 评审 (SSE 流): 4 worker 并行 + 终审交叉校验。

    事件序列:
    - uploaded → wiki_scanned → review_queued → workers_started
    - worker_done × 4 (15% → 70%)
    - final_reviewer_started → final_reviewer_done
    - result (最终 payload) 或 error

    客户端断开时 cancel 主任务,semaphore 在 finally 释放。
    """
    ws_dir = get_workspace_dir(req.workspace)  # 校验 workspace 合法
    require_workspace_access(ws_dir, user)
    enriched_raw_materials = await asyncio.to_thread(enrich_figma_raw_materials, req.raw_materials)
    req = _copy_request_with_raw_materials(req, enriched_raw_materials)

    # 预算卡: 超限直接 429 阻止新评审
    budget_status = check_budget(get_project_root(), reviewer=user["reviewer"])

    # 绝对路径作为 workspace 显式参数下传给 parallel_review, 不再写 os.environ.
    # 历史上用 env var 传递会让 2 个并发 review 互污染 rule_perf_history 查询
    # (dimensions._get_rule_perf_history_path 已改为优先读参数,env 作 CLI 回退).
    ws_abs_path = str(get_project_root() / req.workspace)

    emitter = ReviewProgressEmitter()
    # None is intentional: worker / NLI / goshawk use model_router.route_call.
    # Passing a legacy client here forces worker/evidence paths back to Claude/OAT.
    client = None

    async def _pipeline():
        """评审主任务:parallel_review + goshawk,完成后 return 最终 payload。"""
        import time as _time
        _pipeline_start = _time.time()

        from parallel_review import parallel_review
        # 修法 C (2026-04-26): 默认走 advisor_review_default_async → 内部 advisor_review_with_resampling
        # 让 sprint #2 多次重采样 + DAR 少数派保留 + sprint #6 NLI 真在 web 路径生效.
        # PM 可 PECKER_GOSHAWK_RESAMPLE=1 紧急回退老单次行为.
        from goshawk_advisor import advisor_review_default_async
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
        session_tags = _derive_session_tags(req, user["reviewer"])
        review_started_payload = {
            "prd_name": req.prd_name,
            "mode": req.mode,
            "reviewer": user["reviewer"],  # 2026-04-24 P1: 审计用 JWT 认证过的 reviewer, 非前端 body
            "wiki_pages_count": len(req.wiki_pages),
            "injection_scan": _inj,
        }
        if session_tags:
            review_started_payload["session_tags"] = session_tags
        if "stress" in session_tags:
            review_started_payload["session_kind"] = "stress"
        evt.append("review_started", review_started_payload)

        # 1. 构建增强 PRD
        enhanced_prd = req.prd_content
        if req.raw_materials:
            enhanced_prd += "\n\n---\n## 补充业务资料\n\n" + "\n---\n".join(req.raw_materials)
        if req.user_notes:
            enhanced_prd += f"\n\n---\n## 评审人补充说明\n\n{req.user_notes}"

        emitter.emit("uploaded")
        emitter.emit("wiki_scanned", data={"page_count": len(req.wiki_pages)})
        emitter.emit(
            "review_queued",
            data={
                "message": "已进入评审队列，等待空闲评审位",
                "max_concurrent": get_max_concurrent(),
            },
        )
        evt.append("review_queued", {"max_concurrent": get_max_concurrent()})

        # 2. 并行评审 (semaphore 保护)
        async with review_semaphore:
            emitter.emit("workers_started", data={"mode": req.mode})
            evt.append("workers_started", {"mode": req.mode})
            # Per-tool-call trace callback (2026-04-23 B 优化):
            # 每次 worker / goshawk 里的 client.create 返回后会调用, trace 写
            # EventStore 的 tool_call_done 事件, 给 stability_metrics 聚合用.
            def _on_tool_call(trace):
                try:
                    evt.append("tool_call_done", trace)
                except Exception:
                    pass

            if req.mode == "quick":
                # Quick also uses async workers so each model call keeps the
                # same timeout/degraded-return protection as standard review.
                quick_tiers = {k: MODEL_TIERS["sonnet"] for k in MODEL_TIERS}
                def _on_worker_done(dim, r):
                    emitter.emit_worker_done(dim, r)
                    evt.append("worker_done", _build_worker_done_event_payload(dim, r))

                result = await parallel_review(
                    client, enhanced_prd, req.wiki_pages, quick_tiers,
                    on_worker_done=_on_worker_done, workspace=ws_abs_path,
                    on_tool_call=_on_tool_call,
                )
            else:
                def _on_worker_done(dim, r):
                    emitter.emit_worker_done(dim, r)
                    # Pattern 21: 记录每个 worker 完成事件 (P1-3 补 telemetry)
                    evt.append("worker_done", _build_worker_done_event_payload(dim, r))

                result = await parallel_review(
                    client, enhanced_prd, req.wiki_pages, MODEL_TIERS,
                    on_worker_done=_on_worker_done, workspace=ws_abs_path,
                    on_tool_call=_on_tool_call,
                )

            items = result.get("merged_items", [])

            # T3 2026-04-24: funnel stage N0 (worker_raw) + N1 (after_dedup)
            # 失败不阻塞主 flow (try/except 包, log.warning 后继续)
            _funnel_stages = {}  # 收集各 stage count, 最后 funnel_summary 用
            try:
                from review.funnel_telemetry import compute_worker_raw_stage, compute_dedup_stage
                _worker_raw = compute_worker_raw_stage(result.get("workers", []))
                # 2026-04-28 step 1a: 双发 jsonl + SSE, 让前端 Phase2/4 拿到实时 funnel
                emit_and_log(emitter, evt, "funnel_stage_worker_raw", _worker_raw)
                _funnel_stages["N0_worker_raw"] = _worker_raw["count"]

                _after_dedup = compute_dedup_stage(_worker_raw["count"], items)
                emit_and_log(emitter, evt, "funnel_stage_after_dedup", _after_dedup)
                _funnel_stages["N1_after_dedup"] = _after_dedup["count"]
            except Exception as _fn_err:
                log.warning(f"[funnel] N0/N1 emit 失败不阻塞: {_fn_err}")

            # 2026-04-24 T0: API flow 统一走 verify_evidence,与 CLI (run_session.py:276) 对齐.
            # 之前 API 只靠 goshawk `_verify_wiki_evidence` 侧查代替, 少了:
            #   (1) B 类 rule_id 在 review-rules/ 的硬查
            #   (2) A 类 caveat + confidence × 0.7 降权 (2026-04-24 e3ea5c3 改进)
            #   (3) sparse/rich 模式切换 (模板/新业务 PRD 场景)
            # 现在统一 pipeline, 让 Web 用户也享受 evidence_verify 治理改进.
            try:
                from review.evidence_verify import verify_evidence, summarize_verification
                from review.funnel_telemetry import (
                    compute_evidence_verify_stage, get_wiki_telemetry,
                )
                # 2026-04-26 P1-B: 包 asyncio.to_thread 避免阻塞 event loop (与 L174/786/796 一致).
                # verify_evidence 内部 glob wiki + per-file open + parse, 同步执行会暂停 SSE 心跳.
                # 2026-04-26 Sprint #6 step 2: 注入 client + req.wiki_pages 启用 LLM NLI 升级.
                # NLI 内部 try/except 失败不破 main flow.
                verified = await asyncio.to_thread(
                    verify_evidence, items, ws_abs_path, client, req.wiki_pages,
                )
                items = [i for i in verified if i.get("status") != "RETRACTED"]
                v_sum = summarize_verification(verified)

                # T3: funnel stage N2 (after_evidence_verify) — 用扩展后的 v_sum + wiki telemetry
                _after_ev = None
                try:
                    wiki_tele = await asyncio.to_thread(get_wiki_telemetry, ws_abs_path)
                    _after_ev = compute_evidence_verify_stage(v_sum, wiki_tele)
                    # 2026-04-28 step 1a: 双发 jsonl + SSE
                    emit_and_log(emitter, evt, "funnel_stage_after_evidence_verify", _after_ev)
                    _funnel_stages["N2_after_evidence_verify"] = _after_ev["count"]
                except Exception as _fn_err2:
                    log.warning(f"[funnel] N2 emit 失败不阻塞: {_fn_err2}")

                # 2026-04-28 step 1a: evidence_verify_done SSE 升级 — audit 第 4 项
                # 老版只发 retracted+caveat, 前端 dashboard 拿不到 wiki authority/mode.
                # 现在合并 _after_ev 的 authority_distribution + wiki_mode 上车.
                _ev_done_payload = {
                    "retracted": v_sum.get("retracted", 0),
                    "caveat": v_sum.get("caveat", 0),
                }
                if _after_ev is not None:
                    _ev_done_payload["wiki_mode"] = _after_ev.get("wiki_mode", "unknown")
                    _ev_done_payload["authority_distribution"] = _after_ev.get("authority_distribution", {})
                emit_and_log(emitter, evt, "evidence_verify_done", _ev_done_payload)
            except Exception as _ev_err:
                # 失败不阻塞: items 不变, 行为等同本次修复前 (goshawk 侧查兜底)
                log.warning(f"[evidence_verify] API flow 失败回退到跳过模式: {_ev_err}")
                evt.append("evidence_verify_skipped", {"reason": str(_ev_err)[:200]})

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

            # 部分失败降级提示(非 abort):有可用意见时继续推进,但让 PM 知道本轮不完整。
            degraded_payload = build_worker_degraded_payload(workers_list, items_count=len(items))
            if degraded_payload is not None:
                emitter.emit("review_degraded", data=degraded_payload)
                evt.append("review_degraded", degraded_payload)

            # 3. 终审 (苍鹰) — 仅标准模式
            if req.mode == "standard" and items:
                emitter.emit("final_reviewer_started")
                evt.append("final_reviewer_started", {"items_count": len(items)})
                try:
                    goshawk_result = await advisor_review_default_async(
                        client, enhanced_prd, items, req.wiki_pages,
                        on_tool_call=_on_tool_call,
                    )
                    from goshawk_advisor import apply_advisor_result
                    items = apply_advisor_result(items, goshawk_result, wiki_pages=req.wiki_pages, client=client)
                    result["merged_items"] = items
                    result["goshawk"] = goshawk_result

                    # T3 2026-04-24: funnel stage N3 (after_goshawk)
                    try:
                        from review.funnel_telemetry import compute_goshawk_stage
                        _after_g = compute_goshawk_stage(items, goshawk_result)
                        # 2026-04-28 step 1a: 双发 jsonl + SSE
                        emit_and_log(emitter, evt, "funnel_stage_after_goshawk", _after_g)
                        _funnel_stages["N3_after_goshawk"] = _after_g["count"]
                    except Exception as _fn_err3:
                        log.warning(f"[funnel] N3 emit 失败不阻塞: {_fn_err3}")
                    # Round 8: 把 goshawk verdict + retry 信号持久化到 jsonl,
                    # 让 STATUS 能聚合 SILENT/EMPTY_APPROVAL/REVIEWED 分布
                    # 修法 C (2026-04-26): 附带 DAR retention_kind / n_samples 分布
                    from goshawk_advisor import summarize_resample_telemetry
                    _resample_dim = summarize_resample_telemetry(goshawk_result)
                    # 2026-04-28 step 1a: SSE/jsonl payload 统一 (老版 SSE 短/jsonl 长, 前端
                    # 拿不到 confidence + empty_retry_used). 现在两边都走 _final_evt_full.
                    _final_evt_full = {
                        "false_positive": len(goshawk_result.get("flagged_as_false_positive", [])),
                        "additional": len(goshawk_result.get("additional_findings", [])),
                        "verdict": goshawk_result.get("verdict", "UNKNOWN"),
                        "confidence": goshawk_result.get("confidence", 0.0),
                        "empty_retry_used": goshawk_result.get("empty_retry_used", False),
                    }
                    _final_evt_full.update(_resample_dim)
                    emit_and_log(emitter, evt, "final_reviewer_done", _final_evt_full)
                except Exception as e:
                    emit_and_log(emitter, evt, "final_reviewer_done", {"error": str(e)[:200]})

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
                goshawk_res.get("model_used", "gpt-5.5"),
                goshawk_res["usage"],
            )
            cost_breakdown["goshawk"] = round(gc, 6)
            total_cost += gc
        cost_breakdown["total"] = round(total_cost, 6)
        result["cost_breakdown"] = cost_breakdown

        # 预算卡: append 本次实际成本到 logs/daily_cost_*.jsonl
        # 2026-04-24 P1: 成本归因用 JWT 里的 reviewer, 防前端 body 改 reviewer 伪造成本
        try:
            record_review_cost(get_project_root(), total_cost, user["reviewer"])
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
        # 2026-04-24 P1: reviewer 来自 JWT 认证, 不是 body. 绑入 HMAC v2 签名里,
        # 防前端把 review_result 提交 confirm 时伪造 reviewer 换人归因.
        review_result_handle = ReviewResult.create(
            reviewer=user["reviewer"],
            workspace=req.workspace,
            prd_name=req.prd_name,
            mode=req.mode,
            merged_items=result.get("merged_items", []),
            workers=result.get("workers", []),
            usage=result.get("total_usage", {}),
            goshawk_summary=result.get("goshawk"),
            cost_breakdown=cost_breakdown,
            telemetry=result.get("telemetry"),
        )

        # T3 2026-04-24: funnel_summary — PM decision (N4) 在 confirm_review 走另一条 path, 这里
        # 先发无 N4 的 summary, 只覆盖 N0-N3. confirm_review 里会再发 funnel_stage_after_pm_decision,
        # 聚合时 scripts/funnel_report.py 会把 N4 合并进 summary.
        try:
            from review.funnel_telemetry import compute_funnel_summary
            _summary = compute_funnel_summary(_funnel_stages)
            # 2026-04-28 step 1a: 双发 jsonl + SSE
            emit_and_log(emitter, evt, "funnel_summary", _summary)
        except Exception as _fn_err4:
            log.warning(f"[funnel] summary emit 失败不阻塞: {_fn_err4}")

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
        # 2026-04-24 T2: reject 7 分类, 缺失默认 model_noise (兼容老 payload 不阻塞)
        from models import rule_quality_reason_for_decision
        business_decision = str(decision.get("business_decision") or "").strip()
        reason_category = rule_quality_reason_for_decision(decision)

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
            # 2026-04-24 T2: 按 reason 分桶, 让 scripts/rule_lifecycle 能区分
            # "50% reject 但 90% 是 rule_too_strict → 改写规则"
            # vs "90% 是 false_positive → 规则降级"
            if business_decision:
                valuable_but_skipped = entry["stats"].setdefault("valuable_but_skipped", {})
                valuable_but_skipped[business_decision] = valuable_but_skipped.get(business_decision, 0) + 1
            if reason_category:
                reject_by_reason = entry["stats"].setdefault("reject_by_reason", {})
                reject_by_reason[reason_category] = reject_by_reason.get(reason_category, 0) + 1
        elif action == "edit":
            entry["stats"]["confirmed"] += 1  # 编辑 = 认可问题

        entry["stats"]["total"] += 1

        # EMA 更新 impact_score (时间衰减版 — 2026-04-23 #2)
        # 老数据按半衰期向 neutral(0.5) 回归, 让新数据权重更大
        from rule_perf_decay import ema_with_time_decay
        old_score = entry.get("impact_score", 0.5)
        last_ts = entry.get("last_update_ts")  # None 或 unix epoch
        should_update_impact = True
        if action == "accept":
            delta = 1.0
        elif action == "edit":
            delta = 0.7
        elif action == "reject":
            # 2026-04-24 T2: 按 reason 分档, 不让 wiki_missing 把好规则打成 noisy
            from models import reject_delta_for_decision
            if not reason_category:
                should_update_impact = False
            delta = reject_delta_for_decision(decision)
        else:
            delta = 0.0
        import time as _time
        if should_update_impact:
            now_ts = _time.time()
            new_score = ema_with_time_decay(old_score, last_ts, delta, now_ts=now_ts)
            entry["impact_score"] = round(new_score, 3)
            entry["last_update_ts"] = int(now_ts)

        # 更新驳回率和噪声标记
        total = entry["stats"]["total"]
        reject_by_reason = entry["stats"].get("reject_by_reason", {})
        rejected_count = sum(reject_by_reason.values()) if isinstance(reject_by_reason, dict) else entry["stats"]["rejected"]
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
    prd_name: str = "",
    review_id: str = "",
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
        correctness_reason = str(decision.get("correctness_reason") or "").strip()
        business_decision = str(decision.get("business_decision") or "").strip()
        gt_items.append({
            "id": item_id,
            "rule_id": item.get("rule_id", ""),
            "dimension": item.get("dimension", ""),
            "location": item.get("location", ""),
            "severity": item.get("severity", ""),
            "action": action,
            # 2026-04-24 T2: 7 分类 reason, 让 calibration_runner 按 reason 切分布
            "reason_category": decision.get("reason_category", ""),
            "correctness_reason": correctness_reason,
            "business_decision": business_decision,
            "reason_note": redact_text(
                (decision.get("reason_note", "") or decision.get("reason", ""))[:200]
            ),
            # admin feedback 看板只展示短摘要,不保存/展示 PRD 正文或原始材料。
            "problem": redact_text((item.get("problem", "") or "")[:300]),
            "suggestion": redact_text((item.get("suggestion", "") or "")[:300]),
            "is_true_positive": action in ("accept", "edit") or (bool(business_decision) and not correctness_reason),
        })

    if not gt_items:
        return

    timestamp = int(_time.time())
    # 清理 workspace 名(去掉 workspace- 前缀方便文件名)
    ws_short = workspace.replace("workspace-", "") if workspace.startswith("workspace-") else workspace
    filename = (
        f"{_safe_ground_truth_filename_part(ws_short)}_"
        f"{_safe_ground_truth_filename_part(reviewer)}_"
        f"{timestamp}.json"
    )

    gt_dir = os.path.join(str(get_project_root()), "eval", "ground_truth")
    os.makedirs(gt_dir, exist_ok=True)

    gt_payload = {
        "workspace": redact_text(str(workspace)),
        "reviewer": redact_text(str(reviewer)),
        "prd_name": redact_text(str(prd_name)),
        "review_id": redact_text(str(review_id)),
        "timestamp": timestamp,
        "items": gt_items,
    }

    gt_path = os.path.join(gt_dir, filename)
    with open(gt_path, "w", encoding="utf-8") as f:
        json.dump(gt_payload, f, ensure_ascii=False, indent=2)

    log.info(f"[ground_truth] 保存 {len(gt_items)} 条标注到 {gt_path}")


def _safe_ground_truth_filename_part(value: Any) -> str:
    safe_source = redact_text(str(value or "unknown").strip())
    safe = re.sub(r'[\\/:*?"<>|\s\.]+', "_", safe_source)[:60]
    return safe.strip("_") or "unknown"


@router.post("/review/confirm")
async def confirm_review(req: ConfirmRequest, user: dict = Depends(get_current_user)):
    """Phase 3 提交用户 Y/N/E 决策。先验证 signature 防篡改,再返回可生成报告的标志。

    真正的报告生成在 /api/reports/{workspace}/save-to-wiki 或前端直接拼接,
    这里只做 signature 校验 + 决策计数 + 规则历史回流。
    """
    # Step 1: 验证 opaque handle signature
    review_result = req.review_result
    try:
        verify_review_result(review_result)
    except HTTPException as exc:
        if exc.status_code != 403:
            raise
        recovered_result = _recover_review_result_from_job_store(review_result, user=user)
        if recovered_result is None:
            raise
        review_result = recovered_result

    # ACL: workspace/reviewer 已绑入 signature v2 (2026-04-24 收紧), 这里用于 ACL 二道防线 —
    # signature 挡前端篡改, ACL 挡"合法用户误写他人 workspace"(如 admin 共享 cookie 场景)
    _ws_name = (review_result.get("workspace") or "").strip()
    if _ws_name:
        _ws_dir = get_workspace_dir(_ws_name)
        require_workspace_access(_ws_dir, user)

    # Step 2: 统计决策
    decisions = req.decisions
    items = review_result.get("items", [])
    from review.post_review_contract import build_confirm_report_markdown, summarize_decisions
    decision_stats = summarize_decisions(items, decisions)
    report_markdown = build_confirm_report_markdown(review_result, decisions)

    # Step 3: P0.1 — 决策回流到 rule_performance_history
    # 这两个函数含同步文件 I/O (open/json.dump), 放线程池避免阻塞 event loop
    workspace = review_result.get("workspace", "")
    if workspace and decisions:
        try:
            await asyncio.to_thread(
                _update_rule_perf_from_decisions, items, decisions, workspace,
            )
        except Exception as e:
            log.warning(f"[决策回流] 写入失败,不阻塞确认流程: {e}")

    # Step 4: 保存 Eval ground truth(人类标注 -> 回归测试)
    reviewer = review_result.get("reviewer", "unknown")
    if workspace and decisions:
        try:
            await asyncio.to_thread(
                _save_eval_ground_truth,
                items,
                decisions,
                workspace,
                reviewer,
                review_result.get("prd_name", ""),
                review_result.get("review_id", ""),
            )
        except Exception as e:
            log.warning(f"[ground_truth] 保存失败,不阻塞确认流程: {e}")

    # Step 5: T3 2026-04-24 — funnel stage N4 (after_pm_decision) 写回对应 review_id 的 jsonl
    # 失败不阻塞 confirm (反正已 return 的前提)
    # 2026-04-28 step 1a 注: confirm_review 是独立 POST endpoint, 无 SSE 流 (Phase 2 的 emitter
    # 在 /run 完成时已 close). 前端拿 N4 数据通过 confirm 返回 body 或后续轮询 jsonl.
    # 因此本处 evt.append 单发是 by-design, 不是 step 1a 双发遗漏.
    review_id = review_result.get("review_id", "")
    if workspace and review_id and decisions:
        try:
            from event_store import EventStore
            from review.funnel_telemetry import compute_pm_decision_stage
            ws_abs = str(get_project_root() / workspace)
            evt = EventStore(workspace=ws_abs, review_id=review_id)
            pm_stage = compute_pm_decision_stage(decisions)
            evt.append("funnel_stage_after_pm_decision", pm_stage)
        except Exception as e:
            log.warning(f"[funnel] N4 emit 失败不阻塞: {e}")

    return {
        "status": "confirmed",
        "review_id": review_result.get("review_id"),
        "accepted": decision_stats["accepted"],
        "rejected": decision_stats["rejected"],
        "edited": decision_stats["edited"],
        "pending": decision_stats["pending"],
        "total": decision_stats["total"],
        "report_markdown": report_markdown,
    }
