"""SSE pipeline 断连检测回归测试 — 防止 2026-04-23 修过的 sync/async 陷阱复发.

历史: 一开始把 is_disconnected=lambda: False 改成 starlette request.is_disconnected
(async method)时, stream.py 侧用 sync 调用 `if is_disconnected()` → 拿到 coroutine
对象, `if <coroutine>` 永远 truthy → 一上线所有 SSE 连接立刻被当断开. 修法是
asyncio.iscoroutine() + await 做 runtime dispatch, 兼容 sync 测试 lambda 和 async
生产代码.

本文件覆盖这个分支,防止同类 bug 复发.
"""
from __future__ import annotations

import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from api.stream import ReviewProgressEmitter, sse_review_pipeline


async def _collect(gen, max_chunks=50):
    """消费 async generator,最多 max_chunks 个,避免 hang。"""
    out = []
    async for c in gen:
        out.append(c)
        if len(out) >= max_chunks:
            break
    return out


async def _simple_review_coro():
    """模拟一次评审: 等少量时间后返回,期间 emitter 已被外部 emit 几个事件。"""
    await asyncio.sleep(0.05)
    return {"merged_items": [], "workers": []}


@pytest.mark.asyncio
async def test_no_is_disconnected_completes_normally():
    """不传 is_disconnected 时 pipeline 应正常跑完。"""
    emitter = ReviewProgressEmitter()

    async def coro():
        emitter.emit("uploaded")
        emitter.emit("workers_started", data={"mode": "standard"})
        await asyncio.sleep(0.01)
        return {"ok": True}

    chunks = await _collect(sse_review_pipeline(emitter, coro()))
    # 至少有 uploaded / workers_started / result 三个 SSE event
    text = "".join(chunks)
    assert "uploaded" in text
    assert "workers_started" in text


@pytest.mark.asyncio
async def test_sync_is_disconnected_false_does_not_cancel():
    """sync lambda 返回 False 时不应误判为断开, pipeline 正常跑完。

    这是回归 "sync lambda(False) 被 asyncio.iscoroutine 误判" 的防线。
    """
    emitter = ReviewProgressEmitter()

    async def coro():
        emitter.emit("uploaded")
        await asyncio.sleep(0.01)
        return {"ok": True}

    chunks = await _collect(
        sse_review_pipeline(emitter, coro(), is_disconnected=lambda: False),
    )
    text = "".join(chunks)
    assert "uploaded" in text


@pytest.mark.asyncio
async def test_sync_is_disconnected_true_breaks_early():
    """sync lambda 返回 True 时应立刻 break,不 yield 更多 chunk。"""
    emitter = ReviewProgressEmitter()

    async def coro():
        # 故意不 emit 任何事件 → 第一次从 queue.get() 就等着
        # 但 is_disconnected=True 会在 async for 循环第一次检查前被触发
        await asyncio.sleep(0.2)
        emitter.emit("too_late")
        return {"ok": True}

    chunks = await _collect(
        sse_review_pipeline(emitter, coro(), is_disconnected=lambda: True),
        max_chunks=10,
    )
    # 应该没消费到 too_late (真断开了 task 会被 cancel)
    text = "".join(chunks)
    assert "too_late" not in text


@pytest.mark.asyncio
async def test_async_is_disconnected_false_awaited_and_passes():
    """async def 签名 (starlette Request.is_disconnected 就是这种) 返回 False 时
    pipeline 应 await 结果后不 cancel 继续。这是上次 SSE bug 的回归测试核心。
    """
    emitter = ReviewProgressEmitter()

    async def not_disconnected():
        # 模拟 starlette request.is_disconnected 的 async 签名
        return False

    async def coro():
        emitter.emit("uploaded")
        await asyncio.sleep(0.01)
        return {"ok": True}

    chunks = await _collect(
        sse_review_pipeline(emitter, coro(), is_disconnected=not_disconnected),
    )
    text = "".join(chunks)
    assert "uploaded" in text  # 正常消费,没被误判断开


@pytest.mark.asyncio
async def test_async_is_disconnected_true_breaks():
    """async def 返回 True 时也能正确识别断开。"""
    emitter = ReviewProgressEmitter()

    async def disconnected():
        return True

    async def coro():
        await asyncio.sleep(0.2)
        emitter.emit("too_late")
        return {"ok": True}

    chunks = await _collect(
        sse_review_pipeline(emitter, coro(), is_disconnected=disconnected),
        max_chunks=10,
    )
    text = "".join(chunks)
    assert "too_late" not in text
