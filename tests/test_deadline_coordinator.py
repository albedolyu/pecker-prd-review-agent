"""DeadlineCoordinator 单测 (2026-04-23 #5 refactor)."""
from __future__ import annotations

import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from deadline_coordinator import DeadlineCoordinator


def test_no_deadline_always_allows_retry():
    coord = DeadlineCoordinator(deadline=None, min_per_retry=8.0)
    assert coord.time_left() == float("inf")
    for _ in range(5):
        assert coord.can_afford_retry() is True
    assert coord.was_hit is False


def test_sufficient_time_allows_retry():
    """剩余远大于 min_per_retry 时允许。"""
    coord = DeadlineCoordinator(
        deadline=time.monotonic() + 60,
        min_per_retry=8.0,
    )
    assert coord.can_afford_retry() is True
    assert coord.was_hit is False


def test_insufficient_time_blocks_retry_and_marks_hit():
    """剩余小于 min_per_retry 时拒绝 + 记忆 was_hit。"""
    coord = DeadlineCoordinator(
        deadline=time.monotonic() + 2,  # 只剩 2s
        min_per_retry=8.0,
    )
    assert coord.can_afford_retry() is False
    assert coord.was_hit is True


def test_was_hit_sticky_after_one_false():
    """一次 was_hit 即使后续 can_afford 又变 True, was_hit 应保持 True."""
    coord = DeadlineCoordinator(
        deadline=time.monotonic() + 1,
        min_per_retry=8.0,
    )
    coord.can_afford_retry()  # 第一次 False → was_hit=True
    coord.deadline = time.monotonic() + 60  # 手动续期
    assert coord.can_afford_retry() is True  # 现在够
    assert coord.was_hit is True  # 但历史标记保留


def test_time_left_clamps_to_zero():
    """deadline 已过时 time_left 不返回负数。"""
    coord = DeadlineCoordinator(
        deadline=time.monotonic() - 5,
        min_per_retry=8.0,
    )
    assert coord.time_left() == 0.0
    assert coord.can_afford_retry() is False
