"""rule_perf_decay.py — 规则权重的时间衰减 + EMA 更新算法.

为什么做 (2026-04-23 #2 优化):
原 EMA `new = 0.15 * delta + 0.85 * old` 不感知时间 — 2 个月前 PM reject 的
规则和昨天 reject 的同权重. 真实场景下老数据应该慢慢回归"中性"(0.5),
让新数据占更高权重。

算法:
1. 计算上次更新距今的 dt_days
2. old_score 按半衰期往 neutral(0.5) 衰减: decayed_old = 0.5 + (old - 0.5) * 0.5^(dt/HL)
3. 再做 EMA: new = alpha * delta + (1 - alpha) * decayed_old

默认半衰期 90 天 (env: PECKER_RULE_HALF_LIFE_DAYS). 上线后按真实数据调.

为什么 decay 到 neutral=0.5 而不是 0:
- 0.5 = "不知道这条规则好不好" (中性)
- 0 = "明确坏规则" (PM 一直 reject)
- 老数据衰减后应该回到 "不知道", 不是假装 "坏"
"""
from __future__ import annotations

import os
import time


NEUTRAL_SCORE = 0.5


def _half_life_days() -> float:
    try:
        return float(os.environ.get("PECKER_RULE_HALF_LIFE_DAYS", "90") or 90)
    except ValueError:
        return 90.0


def decay_to_neutral(
    old_score: float,
    last_update_ts: float | None,
    now_ts: float | None = None,
    half_life_days: float | None = None,
    neutral: float = NEUTRAL_SCORE,
) -> float:
    """按距上次更新的时间, 把 old_score 往 neutral 衰减.

    dt=0  → 返回 old_score (不衰减)
    dt=HL → (old - neutral) 衰减 50%
    dt=5×HL → old 几乎等于 neutral
    """
    # 只防 None ("从未更新"的 sentinel). 实际 ts 数值不设下限 — 测试可能用
    # 相对时间戳 (dt=负数), 生产 unix 时间 >0, 两边都能工作.
    if last_update_ts is None:
        return old_score
    if now_ts is None:
        now_ts = time.time()
    if last_update_ts >= now_ts:
        return old_score  # 未来时间戳防御

    hl = half_life_days if half_life_days is not None else _half_life_days()
    if hl <= 0:
        return old_score  # HL=0 视为不衰减

    dt_days = (now_ts - last_update_ts) / 86400.0
    decay_factor = 0.5 ** (dt_days / hl)
    return neutral + (old_score - neutral) * decay_factor


def ema_with_time_decay(
    old_score: float,
    last_update_ts: float | None,
    delta: float,
    now_ts: float | None = None,
    alpha: float = 0.15,
    half_life_days: float | None = None,
    neutral: float = NEUTRAL_SCORE,
) -> float:
    """时间衰减版 EMA. 先 decay old, 再 alpha * delta + (1-alpha) * decayed.

    Args:
        old_score: 当前权重, 0-1
        last_update_ts: 上次更新时间 (unix epoch), None 视为从未更新
        delta: 本次决策的 signed impact (+1/+0.7/-0.5), 不做 clamp
        now_ts: 当前时间, 默认 time.time(), 测试可注入
        alpha: EMA 学习率
        half_life_days: 衰减半衰期, None 走 env/默认
        neutral: 衰减终点, 默认 0.5
    Returns:
        新权重, clamp 到 [0, 1]
    """
    decayed_old = decay_to_neutral(old_score, last_update_ts, now_ts, half_life_days, neutral)
    new_score = alpha * delta + (1 - alpha) * decayed_old
    return max(0.0, min(1.0, new_score))
