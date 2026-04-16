"""R22: 单测 P0-1 的 classify_worker_failures 辅助函数

覆盖全员失败 abort 规则: 配额 vs 其他 vs 部分失败 vs 全绿。
"""
import pytest

from api.routes.review import classify_worker_failures


# -------------------------------------------------
# 正常路径（不触发 abort）
# -------------------------------------------------

def test_empty_list_returns_none():
    assert classify_worker_failures([]) is None


def test_all_success_returns_none():
    workers = [
        {"dimension": "structure", "items": [1, 2]},
        {"dimension": "quality", "items": [3]},
    ]
    assert classify_worker_failures(workers) is None


def test_partial_failure_returns_none():
    """部分失败不是全员失败,不应触发 abort"""
    workers = [
        {"dimension": "structure", "error": "hit your limit"},
        {"dimension": "quality", "items": [1]},
    ]
    assert classify_worker_failures(workers) is None


# -------------------------------------------------
# 全员失败场景
# -------------------------------------------------

def test_all_quota_exhausted_classifies_as_quota():
    workers = [
        {"dimension": "structure", "error": "claude -p 退出码 1: hit your limit — resets 8am"},
        {"dimension": "quality", "error": "claude -p 退出码 1: hit your limit"},
        {"dimension": "ai_coding", "error": "claude -p 退出码 1: hit your limit"},
        {"dimension": "data_quality", "error": "claude -p 退出码 1: hit your limit"},
    ]
    payload = classify_worker_failures(workers)
    assert payload is not None
    assert payload["reason"] == "quota_exhausted"
    assert payload["failed_count"] == 4
    assert payload["total_count"] == 4
    assert len(payload["worker_errors"]) == 4
    assert "配额" in payload["message"]


def test_all_worker_failed_mixed_reasons():
    """全员失败但不全是配额 → all_workers_failed,不是 quota_exhausted"""
    workers = [
        {"dimension": "structure", "error": "hit your limit"},
        {"dimension": "quality", "error": "some network error"},
        {"dimension": "ai_coding", "error": "timeout"},
        {"dimension": "data_quality", "error": "parse failed"},
    ]
    payload = classify_worker_failures(workers)
    assert payload["reason"] == "all_workers_failed"
    assert "全部 4 个" in payload["message"]


def test_quota_chinese_keyword_also_detected():
    """'配额' 中文关键词也能触发 quota 分类"""
    workers = [
        {"dimension": "structure", "error": "Claude CLI 配额已用完"},
        {"dimension": "quality", "error": "Claude CLI 配额已用完"},
    ]
    payload = classify_worker_failures(workers)
    assert payload["reason"] == "quota_exhausted"


def test_quota_exhausted_class_name_also_detected():
    """QuotaExhausted 类名在错误消息里也算配额"""
    workers = [
        {"dimension": "structure", "error": "QuotaExhaustedError: resets 8am"},
        {"dimension": "quality", "error": "QuotaExhaustedError: resets 8am"},
    ]
    payload = classify_worker_failures(workers)
    assert payload["reason"] == "quota_exhausted"


def test_worker_errors_payload_truncates_long_messages():
    """worker_errors[].error 应该被截到 200 字符"""
    long_err = "hit your limit " + "x" * 500
    workers = [
        {"dimension": "structure", "error": long_err},
        {"dimension": "quality", "error": long_err},
    ]
    payload = classify_worker_failures(workers)
    for we in payload["worker_errors"]:
        assert len(we["error"]) <= 200


def test_worker_errors_preserves_dim_field():
    workers = [
        {"dimension": "structure", "error": "hit your limit"},
        {"dimension": "ai_coding", "error": "hit your limit"},
    ]
    payload = classify_worker_failures(workers)
    dims = [we["dim"] for we in payload["worker_errors"]]
    assert "structure" in dims
    assert "ai_coding" in dims


def test_missing_dimension_fallback():
    """worker 缺 dimension 字段时用 '?' 占位,不崩"""
    workers = [
        {"error": "hit your limit"},  # 无 dimension
    ]
    payload = classify_worker_failures(workers)
    assert payload["worker_errors"][0]["dim"] == "?"
