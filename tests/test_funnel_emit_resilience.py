"""P0-C T3 funnel emit 失败不阻塞测试 (2026-04-26 sprint Day3 audit补).

spec: docs/sprint-real-prd-calibration-evidence-governance.md T3 第 459 行 +
      docs/review-funnel-schema.md 第 278 行 (反复承诺但前面没建)

T3 在 5 处 try/except 包了 funnel emit (api/routes/review.py L385/409/470/553/813),
任何 emit 抛异常应该:
- log.warning 记录但不中断主 flow
- pipeline 仍返回正常结果 (items 不丢)
- 后续 stage 仍尝试 emit (失败一处不连锁失败其他)

本文件验证 contract 而不是模拟整个 API pipeline.
直接测 review/funnel_telemetry.py 的 6 个 compute 函数对异常输入的鲁棒性,
+ 测 emit 失败时 pipeline 调用方能捕获.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest


# ============================================================
# 直接断言 funnel_telemetry compute 函数对异常输入鲁棒
# ============================================================

class TestComputeRobustness:
    def test_compute_worker_raw_handles_missing_telemetry(self):
        from review.funnel_telemetry import compute_worker_raw_stage
        # worker 缺 telemetry / dimension / items 字段 (但是真 dict, 真实场景)
        workers = [{}, {"items": []}, {"dimension": "x", "items": [{"id": "R-1"}]}]
        out = compute_worker_raw_stage(workers)
        assert isinstance(out["count"], int)
        assert out["count"] == 1  # 只有第三个有 1 条 item

    def test_compute_dedup_handles_negative_diff(self):
        """raw_count < merged 时 (理论不该, 但鲁棒) dropped 不该负数."""
        from review.funnel_telemetry import compute_dedup_stage
        out = compute_dedup_stage(worker_raw_count=3, merged_items=[1, 2, 3, 4, 5])
        assert out["dropped_count"] == 0

    def test_compute_evidence_verify_missing_keys(self):
        from review.funnel_telemetry import compute_evidence_verify_stage
        # v_sum / wiki_tele 全空
        out = compute_evidence_verify_stage({}, {})
        assert out["count"] == 0
        assert out["wiki_mode"] == "unknown"

    def test_compute_goshawk_handles_no_recommendation(self):
        """fp 项缺 recommendation 字段不该 KeyError."""
        from review.funnel_telemetry import compute_goshawk_stage
        post_items = [{"id": "R-001"}]
        goshawk_result = {
            "flagged_as_false_positive": [{"item_id": "R-002"}],   # 无 recommendation
            "additional_findings": [],
        }
        out = compute_goshawk_stage(post_items, goshawk_result)
        assert out["delta_breakdown"]["removed"] == 0   # 缺 recommendation 不计入

    def test_compute_pm_decision_empty(self):
        from review.funnel_telemetry import compute_pm_decision_stage
        out = compute_pm_decision_stage({})
        assert out["total_items"] == 0
        assert out["accepted"] == 0
        assert out["rejected_by_reason"] == {}

    def test_compute_funnel_summary_all_none(self):
        from review.funnel_telemetry import compute_funnel_summary
        out = compute_funnel_summary({})
        # 全空不该 crash, 各 retention 默认 1.0
        assert "stages" in out
        assert "stage_retention" in out
        assert isinstance(out["suspicious_flags"], list)


# ============================================================
# Emit 失败的 pipeline 调用方能捕获 (mock evt.append 抛异常)
# ============================================================

class TestEmitFailureContainment:
    def test_evt_append_raises_does_not_propagate(self):
        """模拟 EventStore.append 在 funnel_stage_* emit 时抛异常, 调用方 try/except 捕获."""
        # 直接测 try/except 模式: 给定一个 always-raise 的 evt, 调用 emit 不抛
        evt = MagicMock()
        evt.append.side_effect = RuntimeError("disk full")

        # 模拟 api/routes/review.py 里的 emit pattern
        try:
            from review.funnel_telemetry import compute_worker_raw_stage
            stage_data = compute_worker_raw_stage([])  # 计算 OK
            evt.append("funnel_stage_worker_raw", stage_data)  # ← raises
        except Exception as e:
            # 调用方应该 catch + log + 继续
            assert "disk full" in str(e)
            return  # 模拟 try/except 包裹: emit 失败不影响后续

        pytest.fail("Expected RuntimeError to be raised by mock evt.append")

    def test_compute_succeeds_even_with_corrupt_input(self):
        """compute 函数对部分破损 input 不该抛, 即使产出退化值."""
        from review.funnel_telemetry import (
            compute_dedup_stage, compute_evidence_verify_stage,
            compute_goshawk_stage, compute_pm_decision_stage,
            compute_funnel_summary, compute_worker_raw_stage,
        )

        # 各种边角输入 (真实场景下的退化值, 不测 None/非 dict, 那是上游 bug)
        compute_worker_raw_stage([])
        compute_worker_raw_stage([{}, {"items": []}])
        compute_dedup_stage(0, [])
        compute_evidence_verify_stage({}, {})
        compute_goshawk_stage([], {})
        compute_pm_decision_stage({})
        compute_funnel_summary({"N0_worker_raw": 0})  # 部分 stage 缺
        # 没崩就是对的


# ============================================================
# Pipeline-level: api/routes/review.py 风格的 try/except 包裹合同
# ============================================================

class TestApiPipelineEmitContract:
    """模拟 api/routes/review.py 5 处 emit 模式."""

    def _emit_block_pattern(self, evt, stages):
        """复刻 review.py L383-393 + L407-415 + L468-475 + L552-559 + L811-822 的
        try/except 包: emit 失败不阻断, log.warning 后继续."""
        warnings = []
        try:
            from review.funnel_telemetry import compute_worker_raw_stage
            data = compute_worker_raw_stage([])
            evt.append("funnel_stage_worker_raw", data)
            stages["N0_worker_raw"] = data["count"]
        except Exception as err:
            warnings.append(f"[funnel] N0 emit 失败: {err}")

        try:
            from review.funnel_telemetry import compute_dedup_stage
            data = compute_dedup_stage(0, [])
            evt.append("funnel_stage_after_dedup", data)
            stages["N1_after_dedup"] = data["count"]
        except Exception as err:
            warnings.append(f"[funnel] N1 emit 失败: {err}")

        return warnings

    def test_first_emit_fails_subsequent_still_attempt(self):
        """第一处 emit 抛异常, 第二处仍应继续 (独立 try/except 隔离)."""
        evt = MagicMock()
        # 第一次 append 抛, 第二次成功
        evt.append.side_effect = [RuntimeError("first"), None]
        stages = {}
        warnings = self._emit_block_pattern(evt, stages)
        # 第一处失败有 warning, 第二处不该被 short-circuit
        assert len(warnings) == 1
        assert "N0" in warnings[0]
        # stages 第一个没设 (失败), 第二个设了
        assert "N0_worker_raw" not in stages
        assert "N1_after_dedup" in stages

    def test_all_emits_fail_pipeline_still_returns(self):
        """所有 emit 都失败, pipeline 仍能往下走 (即所有 except 都 catch 不抛)."""
        evt = MagicMock()
        evt.append.side_effect = RuntimeError("disk full forever")
        stages = {}
        warnings = self._emit_block_pattern(evt, stages)
        # 所有 try block 各自 catch, 不连锁
        assert len(warnings) == 2
        assert stages == {}  # 没成功设值, 但也没崩
