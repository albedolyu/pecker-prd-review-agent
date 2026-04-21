"""
SPLIT_PLAN 触发条件守卫 — parallel_review.py 接近 2000 行时强制提示

docs/SPLIT_PLAN.md 第八节明确触发条件:"新增功能让 parallel_review.py 突破 2000 行"。
本测试在仍可主动决策的临界点(1900 行)开始 fail,逼迫执行拆分而不是继续在单文件
里堆代码。如果到了 2000 行才看到,通常意味着 PR 已经合入,拆分变成被动。
"""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TARGET_FILE = PROJECT_ROOT / "parallel_review.py"
SOFT_LIMIT = 1900   # 软警告:距离 SPLIT_PLAN 触发线 100 行,提前预警
HARD_LIMIT = 2000   # 硬触发:SPLIT_PLAN.md 第八节明确写的执行触发条件


def test_parallel_review_under_split_threshold():
    """parallel_review.py 行数守卫,逼近触发线时强制 fail。

    超过 1900 行 → 警告(test fail),给团队时间安排拆分
    超过 2000 行 → 硬阻止 commit,必须执行 docs/SPLIT_PLAN.md
    """
    assert TARGET_FILE.exists(), f"找不到 {TARGET_FILE}"
    line_count = sum(1 for _ in TARGET_FILE.open("r", encoding="utf-8"))

    if line_count >= HARD_LIMIT:
        raise AssertionError(
            f"parallel_review.py = {line_count} 行 >= 硬触发 {HARD_LIMIT}。"
            f"必须按 docs/SPLIT_PLAN.md 拆为 6 个子模块,不允许继续在单文件追加。"
        )
    if line_count >= SOFT_LIMIT:
        raise AssertionError(
            f"parallel_review.py = {line_count} 行 >= 软触发 {SOFT_LIMIT}。"
            f"距硬触发 {HARD_LIMIT} 还剩 {HARD_LIMIT - line_count} 行,"
            f"在合并下一个 PR 前先按 docs/SPLIT_PLAN.md 阶段 1 (Cluster A → config.py) 启动拆分。"
        )
