"""ReviewProgressEmitter — SSE 进度推送桥接 helper。

核心任务:把 `parallel_review(on_worker_done=...)` 的回调和 FastAPI 的
`StreamingResponse` 异步生成器连接起来。用 asyncio.Queue 作为消息管道。

设计:
- 主评审 task 运行 `parallel_review(...)` 后台 await,per-worker 完成时往 queue 推
- SSE generator 从 queue 消费,yield event: 数据包到 HTTP 响应
- 完成(或失败)时用 sentinel 标志通知 generator 退出
- 客户端断连 (`request.is_disconnected()`) 时 cancel 主 task

8 个 milestone 见 plan 文件 Streaming 策略 section。
"""
from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional, Union

from api.sanitize import redact_prd_payload, redact_sensitive, redact_text
from logger import get_logger

log = get_logger("sse_stream")


# ============================================================
# Milestone 定义 (进度 0% → 100%)
# ============================================================

MILESTONES = {
    "preliminary_result":     {"progress": 75,  "label": "初稿可查看"},
    "goshawk_patch":          {"progress": 98,  "label": "终审补充已生成"},
    "uploaded":              {"progress": 0,   "label": "已接收"},
    "wiki_scanned":          {"progress": 10,  "label": "资料库读取完成"},
    "review_queued":         {"progress": 12,  "label": "等待空闲评审位"},
    "workers_started":       {"progress": 15,  "label": "评审启动"},
    "worker_done":           {"progress": None, "label": "评审方向完成"},  # 动态 15→70
    "final_reviewer_started":{"progress": 70,  "label": "终审开始"},
    "final_reviewer_done":   {"progress": 95,  "label": "终审完成"},
    "result":                {"progress": 100, "label": "完成"},
    "error":                 {"progress": None, "label": "失败"},
    # 2026-04-28 step 1b: funnel telemetry 不占主进度刻度 (progress=None),
    # 但显式登记后前端 useReviewStream 能在 union type 里识别, dashboard
    # 可以根据 event 名挂面板而不是按 progress% 跳站.
    # 七位 telemetry event 对应 review/funnel_telemetry.py 各 compute_* + evidence_verify_done 升级.
    "funnel_stage_worker_raw":            {"progress": None, "label": "初步意见已汇总"},
    "funnel_stage_after_dedup":           {"progress": None, "label": "重复意见已合并"},
    "funnel_stage_after_evidence_verify": {"progress": None, "label": "依据校验完成"},
    "funnel_stage_after_goshawk":         {"progress": None, "label": "交叉校验完成"},
    "funnel_stage_after_pm_decision":     {"progress": None, "label": "PM 决策已记录"},
    "funnel_summary":                     {"progress": None, "label": "处理结果汇总"},
    "evidence_verify_done":               {"progress": None, "label": "依据校验完成"},
}

# 每个 worker 占 (70 - 15) / 4 = 13.75%,从 15% 递增到 70%
WORKER_PROGRESS_STEP = (70 - 15) / 4  # 13.75


@dataclass
class ReviewProgressEmitter:
    """Emitter 对象,持有一个 asyncio.Queue 作为事件管道。

    用法:
        emitter = ReviewProgressEmitter()

        async def review_task():
            emitter.emit("uploaded")
            # ...
            result = await parallel_review(
                ..., on_worker_done=lambda dim, r: emitter.emit_worker_done(dim, r)
            )
            emitter.emit("result", data=result)
            emitter.close()

        task = asyncio.create_task(review_task())
        async for event_str in emitter.stream():
            yield event_str  # 给 FastAPI StreamingResponse
    """
    queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=50))
    _workers_done_count: int = 0
    _closed: bool = False

    def emit(self, event: str, data: Optional[Dict[str, Any]] = None):
        """同步入队一个 milestone 事件。主评审任务可在任意 coroutine 里调用。"""
        if self._closed:
            return
        milestone = MILESTONES.get(event, {"progress": None, "label": event})
        # contract: NoPRDBody
        safe_data = redact_sensitive(redact_prd_payload(data or {}))
        payload = {
            "event": event,
            "progress": milestone.get("progress"),
            "label": milestone.get("label"),
            **safe_data,
        }
        try:
            self.queue.put_nowait(payload)
        except asyncio.QueueFull:
            # 队列满说明消费端卡了,丢弃进度事件避免阻塞主评审
            pass

    def emit_worker_done(self, dim_key: str, result: Dict[str, Any]):
        """parallel_review 的 on_worker_done callback 专用入口。

        动态计算进度: 15% + (已完成 worker 数) * 13.75%
        3b: 透传 worker telemetry 到 SSE payload
        """
        self._workers_done_count += 1
        progress = int(15 + self._workers_done_count * WORKER_PROGRESS_STEP)
        payload = {
            "event": "worker_done",
            "progress": progress,
            "label": f"评审方向 {self._workers_done_count}/4 完成",
            "dim_key": dim_key,
            "success": "error" not in result,
            "items_count": len(result.get("items", [])) if "items" not in ("error",) else 0,
            "dim_name": result.get("dimension_name", dim_key),
        }
        if "error" in result:
            payload["error"] = redact_text(str(result["error"]))[:200]
        else:
            payload["items_count"] = len(result.get("items", []))
        # 3b: 透传 worker telemetry (duration_ms, tokens, cost, degraded 等)
        if result.get("telemetry"):
            payload["telemetry"] = redact_sensitive(result["telemetry"])
        try:
            self.queue.put_nowait(payload)
        except asyncio.QueueFull:
            pass

    def emit_error(self, error: str):
        """主任务失败时调用,触发前端显示错误状态。"""
        self.emit("error", data={"message": redact_text(str(error))[:500]})

    def close(self):
        """结束流,SSE generator 会收到 sentinel 后退出。"""
        if self._closed:
            return
        self._closed = True
        try:
            self.queue.put_nowait(None)  # sentinel
        except asyncio.QueueFull:
            pass

    async def stream(self, heartbeat_seconds: Optional[float] = None):
        """异步生成器,从 queue 产出 SSE 格式的字符串。

        FastAPI 的 StreamingResponse 直接 async for 这个就行。
        每个事件格式: `event: <event_name>\\ndata: <json>\\n\\n`
        """
        if heartbeat_seconds is None:
            try:
                heartbeat_seconds = float(os.environ.get("PECKER_SSE_HEARTBEAT_SECONDS", "15"))
            except ValueError:
                heartbeat_seconds = 15.0
        while True:
            try:
                if heartbeat_seconds and heartbeat_seconds > 0:
                    item = await asyncio.wait_for(self.queue.get(), timeout=heartbeat_seconds)
                else:
                    item = await self.queue.get()
            except asyncio.TimeoutError:
                yield 'event: heartbeat\ndata: {"event": "heartbeat"}\n\n'
                continue
            if item is None:  # sentinel
                return
            event_name = item.get("event", "message")
            data_json = json.dumps(item, ensure_ascii=False)
            yield f"event: {event_name}\ndata: {data_json}\n\n"


def emit_and_log(emitter: "ReviewProgressEmitter", evt, event_type: str, data: Dict[str, Any]) -> None:
    """funnel telemetry 双发: jsonl (evt.append) + SSE (emitter.emit).

    背景 (2026-04-28 audit_frontend_sync): review.py 8 个 funnel event 历史只 evt.append
    写 jsonl, 不走 emitter.emit 推 SSE → 前端 Phase2/4 即使后端 telemetry 完整也拿不到
    实时数据. 双发模式让老 jsonl 路径不破 + 前端实时能看到漏斗.

    Args:
        emitter: ReviewProgressEmitter 实例 (走 SSE)
        evt: EventStore 实例 (走 jsonl)
        event_type: 事件名 (如 "funnel_stage_worker_raw")
        data: 事件 payload

    任一失败不阻塞另一个: evt.append OSError 已在 EventStore 内部 swallow,
    emitter.emit 队列满会 silently drop. 调用方仍应外包 try/except 防 compute 抛.
    """
    evt.append(event_type, data)
    emitter.emit(event_type, data=data)


async def sse_review_pipeline(
    emitter: ReviewProgressEmitter,
    review_coro,
    is_disconnected: Optional[Callable[[], Union[bool, Awaitable[bool]]]] = None,
    heartbeat_seconds: Optional[float] = None,
):
    """把 review_coro (parallel_review + goshawk) 包装成 SSE pipeline。

    Args:
        emitter: ReviewProgressEmitter 实例
        review_coro: 一个 coroutine,执行完整评审 + emit 各 milestone,返回最终 result
        is_disconnected: 可选,检测客户端是否断开的 callable
            支持两种签名: () -> bool 或 () -> Awaitable[bool]
            (starlette Request.is_disconnected 是 async; 测试里常用 sync lambda)

    Yields:
        SSE 格式字符串
    """
    # 启动后台评审 task
    async def _runner():
        try:
            result = await review_coro
            emitter.emit("result", data={"payload": result})
        except Exception as e:
            emitter.emit_error(str(e))
        finally:
            emitter.close()

    task = asyncio.create_task(_runner())

    try:
        async for chunk in emitter.stream(heartbeat_seconds=heartbeat_seconds):
            # 检查客户端是否断开(兼容 sync/async 两种实现)
            if is_disconnected is not None:
                result = is_disconnected()
                if asyncio.iscoroutine(result):
                    result = await result
                if result:
                    task.cancel()
                    break
            yield chunk
    finally:
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass  # 取消是预期路径, 不用日志
            except Exception as e:
                # 主评审 task 异常结束 — 保留运维可见性, 不吞错
                log.warning(f"SSE pipeline 主任务异常: {type(e).__name__}: {redact_text(str(e))[:100]}")
