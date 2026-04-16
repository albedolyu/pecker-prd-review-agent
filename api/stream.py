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
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


# ============================================================
# Milestone 定义 (进度 0% → 100%)
# ============================================================

MILESTONES = {
    "uploaded":              {"progress": 0,   "label": "已接收"},
    "wiki_scanned":          {"progress": 10,  "label": "wiki 扫描完成"},
    "workers_started":       {"progress": 15,  "label": "评审启动"},
    "worker_done":           {"progress": None, "label": "worker 完成"},  # 动态 15→70
    "final_reviewer_started":{"progress": 70,  "label": "终审开始"},
    "final_reviewer_done":   {"progress": 95,  "label": "终审完成"},
    "result":                {"progress": 100, "label": "完成"},
    "error":                 {"progress": None, "label": "失败"},
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
        payload = {
            "event": event,
            "progress": milestone.get("progress"),
            "label": milestone.get("label"),
            **(data or {}),
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
            "label": f"worker {self._workers_done_count}/4 完成",
            "dim_key": dim_key,
            "success": "error" not in result,
            "items_count": len(result.get("items", [])) if "items" not in ("error",) else 0,
            "dim_name": result.get("dimension_name", dim_key),
        }
        if "error" in result:
            payload["error"] = str(result["error"])[:200]
        else:
            payload["items_count"] = len(result.get("items", []))
        # 3b: 透传 worker telemetry (duration_ms, tokens, cost, degraded 等)
        if result.get("telemetry"):
            payload["telemetry"] = result["telemetry"]
        try:
            self.queue.put_nowait(payload)
        except asyncio.QueueFull:
            pass

    def emit_error(self, error: str):
        """主任务失败时调用,触发前端显示错误状态。"""
        self.emit("error", data={"message": str(error)[:500]})

    def close(self):
        """结束流,SSE generator 会收到 sentinel 后退出。"""
        if self._closed:
            return
        self._closed = True
        try:
            self.queue.put_nowait(None)  # sentinel
        except asyncio.QueueFull:
            pass

    async def stream(self):
        """异步生成器,从 queue 产出 SSE 格式的字符串。

        FastAPI 的 StreamingResponse 直接 async for 这个就行。
        每个事件格式: `event: <event_name>\\ndata: <json>\\n\\n`
        """
        while True:
            item = await self.queue.get()
            if item is None:  # sentinel
                return
            event_name = item.get("event", "message")
            data_json = json.dumps(item, ensure_ascii=False)
            yield f"event: {event_name}\ndata: {data_json}\n\n"


async def sse_review_pipeline(
    emitter: ReviewProgressEmitter,
    review_coro,
    is_disconnected: Optional[Callable[[], bool]] = None,
):
    """把 review_coro (parallel_review + goshawk) 包装成 SSE pipeline。

    Args:
        emitter: ReviewProgressEmitter 实例
        review_coro: 一个 coroutine,执行完整评审 + emit 各 milestone,返回最终 result
        is_disconnected: 可选,检测客户端是否断开的 callable

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
        async for chunk in emitter.stream():
            # 检查客户端是否断开
            if is_disconnected and is_disconnected():
                task.cancel()
                break
            yield chunk
    finally:
        if not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
