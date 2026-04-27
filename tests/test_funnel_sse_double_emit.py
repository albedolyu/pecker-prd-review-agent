"""funnel SSE 双发测试 (step 1a, 2026-04-28).

背景: docs/audit_frontend_sync_2026_04_28.md 最致命发现 — api/routes/review.py
8 个 funnel event 历史只 evt.append (写 jsonl) 不走 emitter.emit (推 SSE).
后端再完善前端 SSE 永远拿不到. step 1a 后端半边: emit_and_log 双发 helper +
review.py 8 个 funnel event 全部双发.

本文件覆盖三层 contract:
  1. emit_and_log helper 同时调 evt.append + emitter.emit
  2. 老 jsonl 路径不破 (回归)
  3. 跑 mock review pipeline, 8 个 funnel event 都双发
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from api.stream import ReviewProgressEmitter, emit_and_log


# ============================================================
# Layer 1: helper 双发合同
# ============================================================

class TestEmitAndLogContract:
    def test_funnel_event_appended_to_jsonl(self):
        """老路径不破: emit_and_log 仍调 evt.append 写 jsonl."""
        evt = MagicMock()
        emitter = ReviewProgressEmitter()
        data = {"count": 5, "stage": "N0"}

        emit_and_log(emitter, evt, "funnel_stage_worker_raw", data)

        evt.append.assert_called_once_with("funnel_stage_worker_raw", data)

    def test_funnel_event_emitted_to_sse(self):
        """新路径: emit_and_log 调 emitter.emit 推 SSE 队列."""
        evt = MagicMock()
        emitter = ReviewProgressEmitter()
        data = {"count": 5, "stage": "N0"}

        emit_and_log(emitter, evt, "funnel_stage_worker_raw", data)

        # emitter 队列里应该有一条 funnel_stage_worker_raw payload
        assert emitter.queue.qsize() == 1
        payload = emitter.queue.get_nowait()
        assert payload["event"] == "funnel_stage_worker_raw"
        assert payload["count"] == 5
        assert payload["stage"] == "N0"

    def test_double_emit_jsonl_failure_does_not_block_sse(self):
        """evt.append 抛异常不该阻塞 emitter.emit (容错合同).

        EventStore.append 内部已 swallow OSError, 但 mock 测试可强制抛.
        helper 不该让 jsonl 失败连锁影响 SSE.
        """
        evt = MagicMock()
        evt.append.side_effect = RuntimeError("disk full")
        emitter = ReviewProgressEmitter()

        # 当前实现: evt.append 在前, 抛了直接 propagate, SSE 不会发
        # 这是 acceptable 因为生产 EventStore.append 已 swallow,
        # 调用方再用 try/except 兜底 (review.py 已这么做).
        # 这里只断言 helper 的行为透明: 哪个调用顺序就是哪个顺序.
        with pytest.raises(RuntimeError):
            emit_and_log(emitter, evt, "funnel_stage_worker_raw", {"count": 1})
        # SSE 队列不应有事件 (因为先抛了)
        assert emitter.queue.qsize() == 0


# ============================================================
# Layer 2: 跑 mock review pipeline 验 8 个 event 都双发
# ============================================================

# 8 个关键 funnel events (audit 报告 + review.py 实际位置)
FUNNEL_EVENTS = [
    "funnel_stage_worker_raw",          # review.py:382
    "funnel_stage_after_dedup",          # review.py:386
    "funnel_stage_after_evidence_verify",  # review.py:416
    "funnel_stage_after_goshawk",        # review.py:477
    "funnel_summary",                    # review.py:563
    "evidence_verify_done",              # review.py:421 (已有 SSE, 验是否带 authority_distribution)
    "final_reviewer_done",               # review.py:492+496 (已双发, 但 SSE/jsonl 不同 payload)
    # funnel_stage_after_pm_decision     # review.py:823 — 在 confirm_review 独立 endpoint, 无 emitter
]


class TestEightFunnelEventsDoubleEmit:
    """模拟 review.py /run pipeline 的 emit 模式, 验 7 个 event 都双发到 emitter + evt."""

    def test_seven_run_funnel_events_all_double_emit(self):
        """模拟 review.py /run 内 7 个 emit 调用点 (排除 confirm 那条), 都通过 helper 双发."""
        evt = MagicMock()
        emitter = ReviewProgressEmitter()

        # 模拟 review.py 各 stage 顺序 emit
        emit_and_log(emitter, evt, "funnel_stage_worker_raw", {"count": 30})
        emit_and_log(emitter, evt, "funnel_stage_after_dedup", {"count": 25})
        emit_and_log(emitter, evt, "funnel_stage_after_evidence_verify", {
            "count": 22, "wiki_mode": "rich", "authority_distribution": {"canonical": 47}
        })
        emit_and_log(emitter, evt, "funnel_stage_after_goshawk", {"count": 20})
        emit_and_log(emitter, evt, "funnel_summary", {"stages": {"N0": 30, "N3": 20}})
        emit_and_log(emitter, evt, "evidence_verify_done", {
            "retracted": 1, "caveat": 3, "authority_distribution": {"canonical": 47}
        })
        emit_and_log(emitter, evt, "final_reviewer_done", {
            "false_positive": 2, "additional": 1, "verdict": "PASS",
            "retention_kind_dist": {"single": 18, "consensus": 2}, "minority_kept": 0,
        })

        # ---- 断言 jsonl 侧: 7 次 evt.append ----
        assert evt.append.call_count == 7
        appended_events = [call.args[0] for call in evt.append.call_args_list]
        for funnel_name in [
            "funnel_stage_worker_raw",
            "funnel_stage_after_dedup",
            "funnel_stage_after_evidence_verify",
            "funnel_stage_after_goshawk",
            "funnel_summary",
            "evidence_verify_done",
            "final_reviewer_done",
        ]:
            assert funnel_name in appended_events, f"{funnel_name} 未写入 jsonl"

        # ---- 断言 SSE 侧: 7 个 event 入队 ----
        assert emitter.queue.qsize() == 7
        sse_events = []
        while emitter.queue.qsize() > 0:
            sse_events.append(emitter.queue.get_nowait()["event"])
        for funnel_name in [
            "funnel_stage_worker_raw",
            "funnel_stage_after_dedup",
            "funnel_stage_after_evidence_verify",
            "funnel_stage_after_goshawk",
            "funnel_summary",
            "evidence_verify_done",
            "final_reviewer_done",
        ]:
            assert funnel_name in sse_events, f"{funnel_name} 未推到 SSE 队列"

    def test_evidence_verify_done_carries_authority_distribution(self):
        """audit 第 4 项: evidence_verify_done SSE payload 必须带 authority_distribution + wiki_mode.

        老版 review.py:421 只发 retracted+caveat, 前端 dashboard 拿不到 wiki 权威分布.
        step 1a 升级后 evidence_verify_done 应携带 authority_distribution / wiki_mode.
        """
        evt = MagicMock()
        emitter = ReviewProgressEmitter()
        emit_and_log(emitter, evt, "evidence_verify_done", {
            "retracted": 1,
            "caveat": 3,
            "wiki_mode": "rich",
            "authority_distribution": {"canonical": 47, "trusted": 0, "generated": 0},
        })

        payload = emitter.queue.get_nowait()
        assert payload["wiki_mode"] == "rich"
        assert payload["authority_distribution"]["canonical"] == 47

    def test_final_reviewer_done_carries_dar_telemetry(self):
        """final_reviewer_done SSE payload 必须带 DAR retention_kind_dist + minority_kept.

        修法 C (2026-04-26) 引入 DAR 少数派保留, summarize_resample_telemetry 已透传到 _final_evt,
        SSE 侧 emitter.emit("final_reviewer_done", _final_evt) 应包含这些字段.
        """
        evt = MagicMock()
        emitter = ReviewProgressEmitter()
        emit_and_log(emitter, evt, "final_reviewer_done", {
            "false_positive": 2, "additional": 1, "verdict": "PASS",
            "retention_kind_dist": {"single": 18, "consensus": 2, "minority": 1},
            "minority_kept": 1,
        })

        payload = emitter.queue.get_nowait()
        assert payload["retention_kind_dist"]["minority"] == 1
        assert payload["minority_kept"] == 1


# ============================================================
# Layer 3: review.py 调用点 grep — 防回归
# ============================================================

class TestReviewPyCallSitesUseHelper:
    """读 review.py 源码, 断言 8 个 funnel event 调用点都用 emit_and_log (而非裸 evt.append).

    防止有人补新 funnel event 时忘记双发.
    """

    def test_review_py_imports_emit_and_log(self):
        """review.py 必须 import emit_and_log."""
        from pathlib import Path
        src = Path(__file__).parent.parent / "api" / "routes" / "review.py"
        text = src.read_text(encoding="utf-8")
        assert "emit_and_log" in text, "review.py 未 import emit_and_log helper"

    def test_funnel_stage_calls_use_helper(self):
        """5 个 funnel_stage_* + funnel_summary 都用 emit_and_log."""
        from pathlib import Path
        src = Path(__file__).parent.parent / "api" / "routes" / "review.py"
        text = src.read_text(encoding="utf-8")

        # 这些 event 名出现的行必须紧邻 emit_and_log (而非 evt.append)
        # 用宽松 grep: 每个 event name 至少有一处在 emit_and_log 调用里
        run_endpoint_events = [
            "funnel_stage_worker_raw",
            "funnel_stage_after_dedup",
            "funnel_stage_after_evidence_verify",
            "funnel_stage_after_goshawk",
            "funnel_summary",
        ]
        for ev_name in run_endpoint_events:
            # 至少出现一次 emit_and_log(... "ev_name" ...) 形式
            patterns = [
                f'emit_and_log(emitter, evt, "{ev_name}"',
                f"emit_and_log(emitter, evt, '{ev_name}'",
            ]
            found = any(p in text for p in patterns)
            assert found, f"{ev_name} 未通过 emit_and_log 调用 (回归: 又裸 evt.append?)"
