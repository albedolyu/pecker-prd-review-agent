"""budget_gate 回归测试(配合 api/budget_gate.py 2026-04-23 落地的 5.6 gate)。

覆盖:
- PECKER_DAILY_BUDGET_USD=0 默认 off, 不抛
- 预算充足时通过, 返回结构正确
- spent + estimated > limit 抛 429
- warn 阈值触发
- record_review_cost 追加并被 compute_today_spend 读回
- budget_status_snapshot 不抛异常(纯查询)
- jsonl 坏行 tolerant 跳过
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from api.budget_gate import (
    budget_status_snapshot,
    check_budget,
    compute_today_spend,
    record_review_cost,
)


@pytest.fixture
def root(tmp_path, monkeypatch):
    """临时项目根目录,logs/ 子目录留给 daily_cost jsonl。"""
    (tmp_path / "logs").mkdir()
    # 清理环境变量,避免测试之间串扰
    for k in (
        "PECKER_DAILY_BUDGET_USD",
        "PECKER_BUDGET_WARN_PCT",
        "PECKER_REVIEW_HARD_CAP_USD",
        "PECKER_REVIEWER_DAILY_BUDGET_USD",
        "PECKER_MONTHLY_BUDGET_USD",
    ):
        monkeypatch.delenv(k, raising=False)
    return tmp_path


def test_off_by_default(root):
    """无 PECKER_DAILY_BUDGET_USD 环境变量时,check_budget 应直接通过不抛。"""
    status = check_budget(root)
    assert status["enabled"] is False
    assert status["limit"] == 0.0
    assert status["spent"] == 0.0
    assert status["warn"] is False


def test_record_then_compute_roundtrip(root):
    """record_review_cost 写入 jsonl, compute_today_spend 应正确求和。"""
    record_review_cost(root, 1.23, "alice")
    record_review_cost(root, 0.5, "bob")
    spent, count = compute_today_spend(root)
    assert abs(spent - 1.73) < 1e-6
    assert count == 2


def test_check_passes_under_limit(root, monkeypatch):
    """预算 10 USD, 已用 1, 预估 2.5 → 通过, 返回完整结构。"""
    monkeypatch.setenv("PECKER_DAILY_BUDGET_USD", "10")
    record_review_cost(root, 1.0, "alice")

    status = check_budget(root, estimated_usd=2.5)
    assert status["enabled"] is True
    assert status["limit"] == 10.0
    assert status["spent"] == 1.0
    assert abs(status["remaining"] - 9.0) < 1e-6
    assert status["today_count"] == 1


def test_check_429_when_projected_exceeds(root, monkeypatch):
    """spent + estimated > limit 必须抛 429, 不是静默通过。"""
    monkeypatch.setenv("PECKER_DAILY_BUDGET_USD", "5")
    record_review_cost(root, 4.0, "alice")

    with pytest.raises(HTTPException) as ei:
        check_budget(root, estimated_usd=2.0)  # 4 + 2 = 6 > 5
    assert ei.value.status_code == 429
    assert "预算" in ei.value.detail or "USD" in ei.value.detail


def test_single_review_hard_cap_blocks_expensive_review(root, monkeypatch):
    """单次评审预估成本超过 hard cap 时,应在发起前拒绝。"""
    monkeypatch.setenv("PECKER_REVIEW_HARD_CAP_USD", "1")

    with pytest.raises(HTTPException) as ei:
        check_budget(root, estimated_usd=2.0, reviewer="alice")

    assert ei.value.status_code == 429
    assert "单次评审额度" in ei.value.detail


def test_reviewer_daily_cap_is_per_person(root, monkeypatch):
    """单人日限额只拦超额 PM,不被其他人的成本误伤。"""
    monkeypatch.setenv("PECKER_REVIEWER_DAILY_BUDGET_USD", "3")
    record_review_cost(root, 2.5, "alice")
    record_review_cost(root, 0.5, "bob")

    with pytest.raises(HTTPException) as ei:
        check_budget(root, estimated_usd=1.0, reviewer="alice")
    assert ei.value.status_code == 429
    assert "个人今日额度" in ei.value.detail

    status = check_budget(root, estimated_usd=1.0, reviewer="bob")
    assert status["reviewer_daily"]["spent"] == 0.5


def test_warn_triggers_at_threshold(root, monkeypatch):
    """spent >= limit * warn_pct 时 warn=true, 但不抛(还没到 limit)。"""
    monkeypatch.setenv("PECKER_DAILY_BUDGET_USD", "10")
    monkeypatch.setenv("PECKER_BUDGET_WARN_PCT", "0.7")
    record_review_cost(root, 7.5, "alice")  # 75% > 70%

    status = check_budget(root, estimated_usd=0.1)  # 不会爆预算
    assert status["warn"] is True


def test_snapshot_never_raises_even_at_limit(root, monkeypatch):
    """budget_status_snapshot 是纯查询,即使预算爆了也不抛(给 review_completed SSE 用)。"""
    monkeypatch.setenv("PECKER_DAILY_BUDGET_USD", "1")
    record_review_cost(root, 100.0, "alice")  # 故意爆预算

    snap = budget_status_snapshot(root)
    assert snap["enabled"] is True
    assert snap["spent"] == 100.0
    assert snap["remaining"] == 0.0  # 不会负数
    assert snap["warn"] is True


def test_corrupted_jsonl_lines_skipped(root, monkeypatch):
    """jsonl 里有坏行应跳过,不让整个求和失败。"""
    from datetime import datetime
    today = datetime.now().strftime("%Y-%m-%d")
    log_path = root / "logs" / f"daily_cost_{today}.jsonl"
    log_path.write_text(
        '{"ts": 1, "cost_usd": 1.5}\n'
        'this is not json\n'
        '{"ts": 2, "cost_usd": 0.5}\n'
        '{"bad": "no cost field"}\n',  # 缺 cost_usd 视为 0
        encoding="utf-8",
    )
    spent, count = compute_today_spend(root)
    assert abs(spent - 2.0) < 1e-6  # 1.5 + 0.5, 坏行跳过, 缺字段算 0
    # count 会算所有非空行,包括坏的和缺字段的
    assert count >= 2


def test_off_snapshot_enabled_false(root, monkeypatch):
    """未启用预算卡时 snapshot 返回 enabled=False。"""
    monkeypatch.delenv("PECKER_DAILY_BUDGET_USD", raising=False)
    snap = budget_status_snapshot(root)
    assert snap["enabled"] is False
    assert snap["limit"] == 0.0
