"""review/ 子包的结构化契约 (TypedDict).

为什么做 (2026-04-23 #3/#6 refactor): worker 和 parallel_review 返回裸 dict,
下游 api/routes/review.py 有 7 处 `isinstance(r, dict)` + `.get()` 链, 新增
字段时 IDE 无法自动补全, 演变 kwargs 易产生 KeyError.

TypedDict 在 runtime 不强制 (仍是 dict), 只给 IDE / mypy 提供静态检查. value
不变, 不破坏现有代码. 想强约束再升 Pydantic.

字段的 required / optional 规则:
- total=False 让所有字段 optional, 允许 failure 分支缺字段
- 工程约定: 成功路径必返 dimension/items/usage/cost_usd/model_used
- 失败路径 (worker 抛异常被 orchestration 兜底) 返 dimension/error/items=[]
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, TypedDict


class WorkerUsage(TypedDict):
    """单 worker / goshawk 的 token 用量."""
    input_tokens: int
    output_tokens: int


class WorkerTelemetry(TypedDict, total=False):
    """Round 2 新增的结构化 telemetry, 给成本分析 + 性能回归用."""
    duration_ms: int
    cost_usd: float
    model: str
    input_tokens: int
    output_tokens: int
    degraded: bool           # worker 是否走了降级分支(空提交兜底 / 解析失败等)
    empty_retry_used: bool   # 是否触发了空提交 re-prompt
    turns_used: int          # model 在 worker 里实际走了几轮对话


class WorkerResult(TypedDict, total=False):
    """review/worker.py:_worker_core 返回.

    成功: dimension + items + usage + cost_usd + model_used + telemetry
    失败: dimension + error + items=[] (被 orchestration 的 except 分支包住, worker
          内部原本的 try/except 逻辑会填更完整的 error 字段)
    """
    # 成功 + 失败都必返
    dimension: str
    items: List[Dict[str, Any]]
    # 成功路径必返
    usage: WorkerUsage
    cost_usd: float
    model_used: str
    telemetry: WorkerTelemetry
    # 失败路径
    error: str


class ParallelReviewResult(TypedDict, total=False):
    """review/orchestration.py:parallel_review / parallel_review_sync 返回.

    api/routes/review.py 再往下会加 cost_breakdown / goshawk / telemetry /
    truncated_by_deadline 等路由层字段, 这个 TypedDict 只描述 orchestration 层的
    契约, api 层有自己的 superset (未来可再加 ReviewPipelineResult TypedDict).
    """
    workers: List[WorkerResult]
    merged_items: List[Dict[str, Any]]
    total_usage: WorkerUsage
    # voting_rounds>=2 时由 majority_vote 覆盖 merged_items, 不加新字段
