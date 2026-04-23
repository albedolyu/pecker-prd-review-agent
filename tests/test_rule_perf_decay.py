"""rule_perf_decay 时间衰减算法测试 (#2 优化)."""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from rule_perf_decay import (
    NEUTRAL_SCORE,
    decay_to_neutral,
    ema_with_time_decay,
)


def test_no_last_ts_returns_old_unchanged():
    """从未更新过 (last_ts=None) 不衰减。"""
    assert decay_to_neutral(0.9, None) == 0.9
    assert decay_to_neutral(0.1, None) == 0.1


def test_dt_zero_does_not_decay():
    """dt=0 返回原值。"""
    now = 1000000.0
    assert decay_to_neutral(0.9, now, now_ts=now) == 0.9


def test_dt_one_half_life_decays_50pct():
    """dt=半衰期 → (old - neutral) 衰减一半。"""
    now = 1000000.0
    one_hl_ago = now - 90 * 86400.0
    # old=0.9, neutral=0.5 → (0.9-0.5)=0.4 → 衰减到 0.2 → 结果 0.7
    assert abs(decay_to_neutral(0.9, one_hl_ago, now_ts=now, half_life_days=90) - 0.7) < 1e-6


def test_dt_five_half_lives_near_neutral():
    """dt=5×HL, (old-neutral) 衰减到 ~3% → 接近 neutral。"""
    now = 1000000.0
    five_hl_ago = now - 5 * 90 * 86400.0
    result = decay_to_neutral(0.9, five_hl_ago, now_ts=now, half_life_days=90)
    # 0.5^5 ≈ 0.03125, 0.5 + 0.4 * 0.03125 ≈ 0.5125
    assert abs(result - 0.5125) < 0.01


def test_future_ts_defensive_returns_old():
    """last_ts 在未来时返回 old (防御时钟倒流)。"""
    now = 1000000.0
    future = now + 1000
    assert decay_to_neutral(0.9, future, now_ts=now) == 0.9


def test_negative_half_life_no_decay():
    """HL<=0 视为不衰减 (env 坏值防御)。"""
    now = 1000000.0
    one_year_ago = now - 365 * 86400.0
    assert decay_to_neutral(0.9, one_year_ago, now_ts=now, half_life_days=0) == 0.9
    assert decay_to_neutral(0.9, one_year_ago, now_ts=now, half_life_days=-5) == 0.9


def test_decay_from_below_neutral_goes_up():
    """old<neutral 时, 衰减应往 neutral 回升 (不会越衰减越低)."""
    now = 1000000.0
    one_hl_ago = now - 90 * 86400.0
    # old=0.1, neutral=0.5 → (0.1-0.5)=-0.4 → 衰减到 -0.2 → 结果 0.3 > 0.1
    result = decay_to_neutral(0.1, one_hl_ago, now_ts=now, half_life_days=90)
    assert abs(result - 0.3) < 1e-6
    assert result > 0.1  # 往 neutral 回升


def test_ema_fresh_update_equals_classic_ema():
    """last_ts=None 时 (新规则), 退化为原 EMA 公式。"""
    # alpha=0.15, delta=1.0, old=0.5 → new = 0.15 + 0.425 = 0.575
    result = ema_with_time_decay(0.5, None, 1.0, alpha=0.15)
    assert abs(result - 0.575) < 1e-6


def test_ema_old_data_decays_before_update():
    """老数据 EMA 前先衰减, 相比新数据同 delta 应有不同结果."""
    now = 1000000.0
    old_score = 0.9
    one_hl_ago = now - 90 * 86400.0

    # 新数据 (无衰减): new = 0.15 * (-0.5) + 0.85 * 0.9 = 0.69
    new = ema_with_time_decay(old_score, now, -0.5, now_ts=now, half_life_days=90)
    # 老数据 (先衰减 0.9 → 0.7, 再 EMA): new = 0.15 * (-0.5) + 0.85 * 0.7 = 0.52
    old_decayed = ema_with_time_decay(
        old_score, one_hl_ago, -0.5, now_ts=now, half_life_days=90,
    )
    assert abs(new - 0.69) < 1e-6
    assert abs(old_decayed - 0.52) < 1e-6
    assert old_decayed < new  # 老数据衰减后 reject 冲击相对更弱


def test_ema_clamps_to_unit_interval():
    """结果 clamp 到 [0, 1]."""
    # 极端正 delta + old=1.0 → 最多 1.0
    assert ema_with_time_decay(1.0, None, 10.0, alpha=0.5) == 1.0
    # 极端负 delta + old=0 → 最少 0
    assert ema_with_time_decay(0.0, None, -10.0, alpha=0.5) == 0.0


def test_env_half_life_override(monkeypatch):
    """PECKER_RULE_HALF_LIFE_DAYS env 可覆盖默认 90。"""
    monkeypatch.setenv("PECKER_RULE_HALF_LIFE_DAYS", "30")
    now = 1000000.0
    thirty_days_ago = now - 30 * 86400.0
    # HL=30 + dt=30 → 衰减 50%, old=0.9 → 0.7
    result = decay_to_neutral(0.9, thirty_days_ago, now_ts=now)
    assert abs(result - 0.7) < 1e-6
