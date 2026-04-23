"""DeadlineCoordinator — 给带内部 retry 的长任务做"剩余时间预算"协调.

解决的问题: 外层用 asyncio.wait_for 切超时是粗暴的(线程里的同步代码不响应 cancel),
而内部 retry 分支(sleep + API call)不感知剩余时间时,会在时间不够的情况下还硬做
一轮 retry,导致外层 wait_for 触发时内层状态不可控。

本 class 让 retry 决策方主动问"我还够不够做一次 retry" 而不是"任其 sleep 完被 kill".

典型用法(见 goshawk_advisor.py):
    coord = DeadlineCoordinator(deadline=time.monotonic() + 300, min_per_retry=8.0)
    for attempt in range(3):
        try:
            return do_call()
        except TransientError:
            if not coord.can_afford_retry():
                raise  # 时间不够, 让上层知道降级
            time.sleep(backoff)
    # 结束后可以查 coord.was_hit 给上层标记 truncated_by_deadline
"""
from __future__ import annotations

import time
from typing import Optional


class DeadlineCoordinator:
    """检查剩余时间预算 + 记忆是否因为 deadline 跳过 retry."""

    def __init__(self, deadline: Optional[float] = None, min_per_retry: float = 8.0):
        """deadline: time.monotonic() 绝对时间戳, None 表示无限(CLI 模式)。
        min_per_retry: 估计一次 retry 分支最坏耗时(包含 sleep + API call)。
        """
        self.deadline = deadline
        self.min_per_retry = min_per_retry
        self._was_hit = False

    def time_left(self) -> float:
        """返回剩余秒数, 无 deadline 时返回 +inf。"""
        if self.deadline is None:
            return float("inf")
        return max(0.0, self.deadline - time.monotonic())

    def can_afford_retry(self) -> bool:
        """True 表示剩余时间 >= min_per_retry, 可以安全再跑一次 retry。
        False 会把 was_hit 标记为 True, 上层可在结果里带 truncated_by_deadline=True。
        """
        if self.time_left() < self.min_per_retry:
            self._was_hit = True
            return False
        return True

    @property
    def was_hit(self) -> bool:
        """有过 can_afford_retry() 返回 False 的情况吗? 上层用来判断降级标记。"""
        return self._was_hit
