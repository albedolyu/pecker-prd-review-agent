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
        """4/4 都标 R-001 误报 → 保留, frequency=1.0, retention_kind=unanimous."""
        from goshawk_advisor import _aggregate_advisor_results
        results = [_make_result(flagged=[_fp("R-001")]) for _ in range(4)]
        agg = _aggregate_advisor_results(results, n_samples=4)
        assert len(agg["flagged_as_false_positive"]) == 1
        fp = agg["flagged_as_false_positive"][0]
        assert fp["item_id"] == "R-001"
        assert fp["verdict_distribution"]["frequency"] == 1.0
        assert fp["verdict_distribution"]["appearances"] == 4
        assert fp["verdict_distribution"]["retention_kind"] == "unanimous"

    def test_majority_fp_kept_at_threshold(self):
        """N=4, threshold=2. 2/4 同意 → 保留 retention_kind=majority."""
        from goshawk_advisor import _aggregate_advisor_results
        results = [
            _make_result(flagged=[_fp("R-001")]),
            _make_result(flagged=[_fp("R-001")]),
            _make_result(),
            _make_result(),
        ]
        agg = _aggregate_advisor_results(results, n_samples=4)
        assert len(agg["flagged_as_false_positive"]) == 1
        fp = agg["flagged_as_false_positive"][0]
        assert fp["verdict_distribution"]["frequency"] == 0.5
        assert fp["verdict_distribution"]["retention_kind"] == "majority"

    def test_minority_fp_kept_with_label(self):
        """DAR (2026-04-26): N=4, 1/4 同意 → 仍保留 retention_kind=minority (老逻辑过滤)."""
        from goshawk_advisor import _aggregate_advisor_results
        results = [
            _make_result(flagged=[_fp("R-001")]),
            _make_result(),
            _make_result(),
            _make_result(),
        ]
        agg = _aggregate_advisor_results(results, n_samples=4)
        # DAR: 不再过滤 minority, 而是标 retention_kind 让 PM 看
        assert len(agg["flagged_as_false_positive"]) == 1
        fp = agg["flagged_as_false_positive"][0]
        assert fp["verdict_distribution"]["frequency"] == 0.25
        assert fp["verdict_distribution"]["retention_kind"] == "minority"

    def test_zero_appearance_filtered(self):
        """从未出现的 item 不保留."""
        from goshawk_advisor import _aggregate_advisor_results
        results = [_make_result() for _ in range(4)]   # 4 次都没 fp
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
# DAR retention_kind 边界 (2026-04-26 新增)
# ============================================================

class TestRetentionKind:
    @pytest.mark.parametrize("count,n,expected", [
        (0, 4, "filtered"),
        (1, 4, "minority"),    # ceil(4/2)=2, count<2 → minority
        (2, 4, "majority"),    # = threshold
        (3, 4, "majority"),
        (4, 4, "unanimous"),
        (1, 3, "minority"),    # ceil(3/2)=2, count<2 → minority
        (2, 3, "majority"),
        (3, 3, "unanimous"),
        (1, 2, "majority"),    # ceil(2/2)=1, count==1 → majority (n=2 时 minority 不存在)
        (2, 2, "unanimous"),
        (1, 1, "unanimous"),   # 单次 = unanimous
    ])
    def test_retention_kind_edge_cases(self, count, n, expected):
        from goshawk_advisor import _retention_kind
        assert _retention_kind(count, n) == expected, \
            f"count={count}, n={n} 应返 {expected}"


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


# ============================================================
# 修法 C (2026-04-26): production default 入口测试
# ============================================================

class TestAdvisorReviewDefault:
    """advisor_review_default 是 run_session/api/routes 的 production caller,
    必须保证默认走 resampling, env=1/0 能 opt-out 老单次行为.
    """

    def test_default_no_env_uses_4_samples(self, monkeypatch):
        """没设 env → 默认 4 次采样."""
        monkeypatch.delenv("PECKER_GOSHAWK_RESAMPLE", raising=False)
        from goshawk_advisor import advisor_review_default
        with patch("goshawk_advisor.advisor_review") as mock_ar:
            mock_ar.return_value = _make_result()
            advisor_review_default(client=None, prd_content="prd", worker_results=[])
            assert mock_ar.call_count == 4

    def test_env_1_opts_out_to_single(self, monkeypatch):
        """PECKER_GOSHAWK_RESAMPLE=1 → 紧急回退老路径单次."""
        monkeypatch.setenv("PECKER_GOSHAWK_RESAMPLE", "1")
        from goshawk_advisor import advisor_review_default
        with patch("goshawk_advisor.advisor_review") as mock_ar:
            mock_ar.return_value = _make_result()
            advisor_review_default(client=None, prd_content="prd", worker_results=[])
            assert mock_ar.call_count == 1

    def test_env_0_treated_as_single(self, monkeypatch):
        """0 当 alias 也走单次, 防 PM 习惯写 0 disable."""
        monkeypatch.setenv("PECKER_GOSHAWK_RESAMPLE", "0")
        from goshawk_advisor import advisor_review_default
        with patch("goshawk_advisor.advisor_review") as mock_ar:
            mock_ar.return_value = _make_result()
            advisor_review_default(client=None, prd_content="prd", worker_results=[])
            assert mock_ar.call_count == 1

    def test_env_8_uses_8_samples(self, monkeypatch):
        """显式覆写也 OK."""
        monkeypatch.setenv("PECKER_GOSHAWK_RESAMPLE", "8")
        from goshawk_advisor import advisor_review_default
        with patch("goshawk_advisor.advisor_review") as mock_ar:
            mock_ar.return_value = _make_result()
            advisor_review_default(client=None, prd_content="prd", worker_results=[])
            assert mock_ar.call_count == 8

    def test_env_garbage_falls_back_to_default(self, monkeypatch):
        """非法 int → 默认 4 (容错), warn 不阻塞."""
        monkeypatch.setenv("PECKER_GOSHAWK_RESAMPLE", "not_an_int")
        from goshawk_advisor import advisor_review_default
        with patch("goshawk_advisor.advisor_review") as mock_ar:
            mock_ar.return_value = _make_result()
            advisor_review_default(client=None, prd_content="prd", worker_results=[])
            assert mock_ar.call_count == 4

    def test_output_schema_compatible_with_advisor_review(self, monkeypatch):
        """关键: 出参 schema 跟 advisor_review 一致, caller 不需要 adapter."""
        monkeypatch.setenv("PECKER_GOSHAWK_RESAMPLE", "1")
        from goshawk_advisor import advisor_review_default
        sample = _make_result(flagged=[_fp("R-001")], confidence=0.9, verdict="REVIEWED")
        with patch("goshawk_advisor.advisor_review", return_value=sample):
            r = advisor_review_default(client=None, prd_content="prd", worker_results=[])
        # 老 caller 用的关键 key 全在
        assert "flagged_as_false_positive" in r
        assert "additional_findings" in r
        assert "conflict_resolutions" in r
        assert "confidence" in r
        assert "verdict" in r


class TestSummarizeResampleTelemetry:
    """summarize_resample_telemetry 把 DAR retention_kind 分布抽出来,
    让 caller 写到 session jsonl, PM 可聚合 minority/majority/unanimous 占比.
    """

    def test_single_run_returns_empty_dict(self):
        """单轮 (n_samples 缺失 / =1) → 老行为, 不动 telemetry."""
        from goshawk_advisor import summarize_resample_telemetry
        assert summarize_resample_telemetry({"flagged_as_false_positive": []}) == {}
        assert summarize_resample_telemetry({"n_samples": 1}) == {}

    def test_multi_run_extracts_retention_kind_dist(self):
        from goshawk_advisor import summarize_resample_telemetry
        result = {
            "n_samples": 4,
            "n_samples_succeeded": 4,
            "flagged_as_false_positive": [
                {"item_id": "R-001", "verdict_distribution": {"retention_kind": "unanimous"}},
                {"item_id": "R-002", "verdict_distribution": {"retention_kind": "minority"}},
            ],
            "conflict_resolutions": [
                {"items": ["R-003", "R-004"], "verdict_distribution": {"retention_kind": "majority"}},
            ],
        }
        tel = summarize_resample_telemetry(result)
        assert tel["n_samples"] == 4
        assert tel["n_samples_succeeded"] == 4
        assert tel["retention_kind_dist"] == {"unanimous": 1, "minority": 1, "majority": 1}
        assert tel["minority_kept"] == 1

    def test_no_minority_returns_zero(self):
        from goshawk_advisor import summarize_resample_telemetry
        result = {
            "n_samples": 4,
            "flagged_as_false_positive": [
                {"item_id": "R-001", "verdict_distribution": {"retention_kind": "unanimous"}},
            ],
            "conflict_resolutions": [],
        }
        tel = summarize_resample_telemetry(result)
        assert tel["minority_kept"] == 0
        assert tel["retention_kind_dist"] == {"unanimous": 1}


# ============================================================
# P0 防回归: model=None 透传 bug (2026-04-26 修法 C 暴露; 2026-04-27 re-add
# 因 cherry-pick 漏拉测试代码导致 main 上 0 collected)
# ============================================================
#
# 历史 bug: 修法 C (commit fa4fcfe) 落地后真业务跑发现 advisor_review_default
# 默认 model=None, 透传到 advisor_review_with_resampling -> advisor_review
# -> client.create -> claude_cli._map_model(None) 返 None -> cmd 含 None
# -> subprocess.run 报 'expected str, bytes or os.PathLike object, not NoneType'.
# 苍鹰 4/4 重采样 + 1 fallback 全崩, 14.3s 全异常重试, DAR 0 emit, $3.52 / 0 价值.
#
# 单测 906 passed 没抓到 — Agent F 的 mock 都在 advisor_review 内部, 没下到
# subprocess argv 层. 加这两个测试防回归, 默认值 / 兜底层各一道锁.


class TestModelNoneProtection:
    """advisor_review_default + _with_resampling 默认 model 必须是 DEFAULT_MODEL,
    + claude_cli._map_model(None) 必须 fallback, 双保险防 None 进 subprocess argv.
    """

    def test_advisor_review_default_signature_uses_default_model(self):
        import inspect
        from goshawk_advisor import (
            advisor_review_default,
            advisor_review_with_resampling,
            DEFAULT_MODEL,
        )
        sig1 = inspect.signature(advisor_review_default)
        assert sig1.parameters["model"].default == DEFAULT_MODEL, (
            "advisor_review_default 默认 model 必须是 DEFAULT_MODEL "
            "(防 None 透传到 subprocess argv)"
        )
        sig2 = inspect.signature(advisor_review_with_resampling)
        assert sig2.parameters["model"].default == DEFAULT_MODEL, (
            "advisor_review_with_resampling 默认 model 必须是 DEFAULT_MODEL"
        )

    def test_claude_cli_map_model_none_fallbacks_to_sonnet(self):
        """P0 第二把锁: _map_model(None / '') 必须返 alias 而非 None."""
        from clients.claude_cli import ClaudeCodeCLIClient
        cc = ClaudeCodeCLIClient.__new__(ClaudeCodeCLIClient)  # 不跑 __init__ 避真去找 cli bin
        assert cc._map_model(None) == "sonnet"
        assert cc._map_model("") == "sonnet"
        # 已知别名仍按原逻辑
        assert cc._map_model("claude-opus-4-7") == "opus"
        assert cc._map_model("claude-sonnet-4-6") == "sonnet"
        assert cc._map_model("claude-haiku-4-5") == "haiku"
        # 含义不明的 model id 仍透传 (兼容 _create_once 直接给 CLI)
        assert cc._map_model("custom-model-id") == "custom-model-id"
