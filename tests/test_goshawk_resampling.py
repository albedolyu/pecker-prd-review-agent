"""Sprint #2 苍鹰 verifier 多次重采样 + 频次聚合 (2026-04-26).

承接用户 GitHub 借鉴清单 #2 LLM-as-Verifier + AI Engineer feasibility 报告.
关键约束: Anthropic 不暴露 logprobs, 用蒙特卡洛 N 次重采样近似.

策略 (保守, 抑 sampling noise):
- n_samples=1 等价老 advisor_review (默认, 兼容)
- n_samples >= 2 → 并行 N 次, ceil(n/2) 多数同意才保留 finding
- additional_findings 取第一次 (避免 N 倍漏报上限)
- conflict_resolutions 多数同意 + MAX_CONFLICT_RESOLUTIONS=3 截断

测试聚合逻辑, mock advisor_review 返不同结果验证频次行为.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest


def _make_result(flagged=None, additional=None, conflicts=None, confidence=0.8, verdict="REVIEWED"):
    return {
        "flagged_as_false_positive": flagged or [],
        "additional_findings": additional or [],
        "conflict_resolutions": conflicts or [],
        "confidence": confidence,
        "verdict": verdict,
        "model_used": "claude-opus-4-6",
    }


def _fp(item_id, reason="过度解读", recommendation="降级为 should"):
    return {"item_id": item_id, "reason": reason, "recommendation": recommendation}


def _conflict(items, resolution="保留前者", reason="重复"):
    return {"items": items, "resolution": resolution, "reason": reason}


# ============================================================
# _aggregate_advisor_results 频次聚合
# ============================================================

class TestAggregate:
    def test_empty_results_returns_none(self):
        from goshawk_advisor import _aggregate_advisor_results
        assert _aggregate_advisor_results([], 4) is None

    def test_unanimous_fp_kept_with_full_frequency(self):
        """4/4 都标 R-001 误报 → 保留, frequency=1.0."""
        from goshawk_advisor import _aggregate_advisor_results
        results = [_make_result(flagged=[_fp("R-001")]) for _ in range(4)]
        agg = _aggregate_advisor_results(results, n_samples=4)
        assert len(agg["flagged_as_false_positive"]) == 1
        fp = agg["flagged_as_false_positive"][0]
        assert fp["item_id"] == "R-001"
        assert fp["verdict_distribution"]["frequency"] == 1.0
        assert fp["verdict_distribution"]["appearances"] == 4

    def test_majority_fp_kept_at_threshold(self):
        """N=4, threshold=2. 2/4 同意 → 保留."""
        from goshawk_advisor import _aggregate_advisor_results
        results = [
            _make_result(flagged=[_fp("R-001")]),
            _make_result(flagged=[_fp("R-001")]),
            _make_result(),
            _make_result(),
        ]
        agg = _aggregate_advisor_results(results, n_samples=4)
        assert len(agg["flagged_as_false_positive"]) == 1
        assert agg["flagged_as_false_positive"][0]["verdict_distribution"]["frequency"] == 0.5

    def test_minority_fp_filtered(self):
        """N=4, threshold=2. 1/4 同意 → 过滤."""
        from goshawk_advisor import _aggregate_advisor_results
        results = [
            _make_result(flagged=[_fp("R-001")]),
            _make_result(),
            _make_result(),
            _make_result(),
        ]
        agg = _aggregate_advisor_results(results, n_samples=4)
        assert agg["flagged_as_false_positive"] == []

    def test_additional_findings_uses_first_non_empty(self):
        """additional 取第一次有补充的, 不重采避免 N 倍漏报上限."""
        from goshawk_advisor import _aggregate_advisor_results
        finding_1 = {"rule_id": "RC-005", "location": "全文", "issue": "x", "suggestion": "y",
                     "severity": "must", "evidence_type": "B", "evidence_content": "RC-005"}
        finding_2 = {"rule_id": "RC-007", "location": "节 2", "issue": "z", "suggestion": "w",
                     "severity": "should", "evidence_type": "A", "evidence_content": "[[页]]"}
        results = [
            _make_result(),                              # 空, 跳过
            _make_result(additional=[finding_1]),        # 第一个有, 取这个
            _make_result(additional=[finding_2]),        # 不取
        ]
        agg = _aggregate_advisor_results(results, n_samples=3)
        assert len(agg["additional_findings"]) == 1
        assert agg["additional_findings"][0]["rule_id"] == "RC-005"

    def test_conflict_majority_kept_freq_recorded(self):
        """conflict_resolutions 按 frozen items set 聚合, 多数同意保留."""
        from goshawk_advisor import _aggregate_advisor_results
        results = [
            _make_result(conflicts=[_conflict(["R-001", "R-002"])]),
            _make_result(conflicts=[_conflict(["R-001", "R-002"])]),
            _make_result(conflicts=[_conflict(["R-001", "R-002"])]),
            _make_result(),   # 1/4 不出现 R-001/R-002 合并
        ]
        agg = _aggregate_advisor_results(results, n_samples=4)
        assert len(agg["conflict_resolutions"]) == 1
        cr = agg["conflict_resolutions"][0]
        assert cr["verdict_distribution"]["frequency"] == 0.75

    def test_conflict_min_filtered(self):
        """N=4, 1/4 同意 conflict → 过滤."""
        from goshawk_advisor import _aggregate_advisor_results
        results = [
            _make_result(conflicts=[_conflict(["R-001", "R-002"])]),
            _make_result(),
            _make_result(),
            _make_result(),
        ]
        agg = _aggregate_advisor_results(results, n_samples=4)
        assert agg["conflict_resolutions"] == []

    def test_conflict_cap_applied_after_aggregation(self):
        """聚合后即使多条多数同意, MAX_CONFLICT_RESOLUTIONS=3 仍截顶."""
        from goshawk_advisor import _aggregate_advisor_results, MAX_CONFLICT_RESOLUTIONS
        # 5 组不同 items 都 4/4 同意 → 聚合得 5 条, 应截到 3
        conflicts_per_run = [
            _conflict([f"R-{i:03d}", f"R-{i+1:03d}"], resolution=f"r{i}", reason=f"R{i}")
            for i in range(5)
        ]
        results = [_make_result(conflicts=conflicts_per_run) for _ in range(4)]
        agg = _aggregate_advisor_results(results, n_samples=4)
        assert len(agg["conflict_resolutions"]) == MAX_CONFLICT_RESOLUTIONS == 3

    def test_confidence_averaged(self):
        from goshawk_advisor import _aggregate_advisor_results
        results = [
            _make_result(confidence=0.6),
            _make_result(confidence=0.8),
            _make_result(confidence=1.0),
        ]
        agg = _aggregate_advisor_results(results, n_samples=3)
        assert agg["confidence"] == 0.8   # (0.6+0.8+1.0)/3

    def test_verdict_majority_wins(self):
        from goshawk_advisor import _aggregate_advisor_results
        results = [
            _make_result(verdict="REVIEWED"),
            _make_result(verdict="REVIEWED"),
            _make_result(verdict="UNCERTAIN"),
        ]
        agg = _aggregate_advisor_results(results, n_samples=3)
        assert agg["verdict"] == "REVIEWED"

    def test_n_samples_succeeded_reported(self):
        """聚合后报实际成功的采样数 (可能 < n_samples 因部分失败 skip)."""
        from goshawk_advisor import _aggregate_advisor_results
        # 模拟 n_samples=4 但只 3 个成功 (一个被外层 skip 没进 results)
        results = [_make_result()] * 3
        agg = _aggregate_advisor_results(results, n_samples=4)
        assert agg["n_samples"] == 4
        assert agg["n_samples_succeeded"] == 3


# ============================================================
# advisor_review_with_resampling wrapper
# ============================================================

class TestResamplingWrapper:
    def test_n_equals_1_calls_advisor_review_once(self):
        """n_samples=1 → 直接调 advisor_review, 等价老路径."""
        from goshawk_advisor import advisor_review_with_resampling
        with patch("goshawk_advisor.advisor_review") as mock_ar:
            mock_ar.return_value = _make_result()
            advisor_review_with_resampling(
                client=None, prd_content="prd", worker_results=[], n_samples=1,
            )
            assert mock_ar.call_count == 1

    def test_n_equals_4_calls_advisor_review_4_times_parallel(self):
        from goshawk_advisor import advisor_review_with_resampling
        with patch("goshawk_advisor.advisor_review") as mock_ar:
            mock_ar.return_value = _make_result(flagged=[_fp("R-001")])
            agg = advisor_review_with_resampling(
                client=None, prd_content="prd", worker_results=[], n_samples=4,
            )
            assert mock_ar.call_count == 4
            # 4 次都返 R-001 → 保留, frequency=1.0
            assert len(agg["flagged_as_false_positive"]) == 1

    def test_partial_failure_uses_succeeded_only(self):
        """4 次中 2 次抛异常 → succeeded=2, 用 2 个聚合."""
        from goshawk_advisor import advisor_review_with_resampling
        call_count = {"n": 0}

        def _maybe_fail(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] in (2, 4):   # 第 2/4 次失败
                raise RuntimeError("API timeout")
            return _make_result(flagged=[_fp("R-001")])

        with patch("goshawk_advisor.advisor_review", side_effect=_maybe_fail):
            agg = advisor_review_with_resampling(
                client=None, prd_content="prd", worker_results=[], n_samples=4,
            )
        # 2 成功 + 全同意 → 保留, frequency=1.0 (基于 2 次)
        assert agg["n_samples_succeeded"] == 2
        assert len(agg["flagged_as_false_positive"]) == 1

    def test_all_fail_falls_back_to_single_advisor_review(self):
        """全失败 → fallback 单次 advisor_review (raise 让上层处理)."""
        from goshawk_advisor import advisor_review_with_resampling
        call_count = {"n": 0}

        def _all_fail_then_succeed(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] <= 4:
                raise RuntimeError("flaky")
            # 第 5 次 (fallback) 成功
            return _make_result(verdict="FALLBACK")

        with patch("goshawk_advisor.advisor_review", side_effect=_all_fail_then_succeed):
            result = advisor_review_with_resampling(
                client=None, prd_content="prd", worker_results=[], n_samples=4,
            )
        # fallback 第 5 次返回的结果
        assert result.get("verdict") == "FALLBACK"
