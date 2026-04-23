"""Cluster D — 并行评审编排 (4 Worker 并发 + 多轮投票).

从 parallel_review.py 拆出 (2026-04-16 继续 SPLIT_PLAN 阶段 5):
- _single_round_async / _single_round_sync: 单轮 4 Worker 并行
- parallel_review / parallel_review_sync: 对外公共 API (支持 voting_rounds)

本模块是啄木鸟"4 Worker 并行 + 苍鹰仲裁"拓扑里的 Worker 层编排。依赖:
- review.worker: 单 Worker 执行
- review.aggregation: merge_and_deduplicate / majority_vote
- review.dimensions: 维度配置 + 反馈历史路径
"""

import asyncio
import json
import time

from io_utils import try_read_json
from logger import get_logger
from review.aggregation import majority_vote, merge_and_deduplicate
from review.dimensions import (
    _cn_label,
    _get_rule_perf_history_path,
    get_review_dimensions,
)
from review.types import ParallelReviewResult
from review.worker import _run_worker_async, _run_worker_sync

log = get_logger("parallel")


async def _single_round_async(client, prd_content, wiki_pages, model_tiers, wiki_path=None, diff_context=None, on_worker_done=None, workspace=None):
    """单轮并行评审（内部函数），返回 workers, merged_items, usage

    Args:
        on_worker_done: 可选 callback,签名为 (dim_key: str, result: dict) -> None
            每个 worker 完成时(成功或失败)都会调用,让上层(FastAPI SSE)感知进度。
            默认 None,保持向后兼容,CLI 现有流程零影响。
        workspace: 显式工作区路径(FastAPI 并发路径必传,否则 rule_perf_history 会
            从 os.environ["WORKSPACE"] 读,并发下会互污染)。CLI 模式为 None 回退读 env。
    """
    dimensions = get_review_dimensions()

    # 读一次 rule performance history，传给所有 worker（避免 4 次 I/O）
    rule_perf_history = try_read_json(_get_rule_perf_history_path(workspace), default=None)

    # 错峰启动: Windows 下 4 个 claude CLI 子进程同时启动会触发 Node.js libuv assertion
    # (UV_HANDLE_CLOSING / 0xC0000409 STATUS_STACK_BUFFER_OVERRUN),给每个 worker 加 stagger
    async def _staggered(idx, dim_key):
        await asyncio.sleep(idx * 0.3)  # 0.5→0.3: 省 0.8s 总启动时间
        try:
            result = await _run_worker_async(
                client, dim_key, prd_content, wiki_pages, model_tiers, rule_perf_history, wiki_path, diff_context
            )
            # 新增: worker 完成后通知外层(FastAPI SSE 用,CLI 模式下 callback 为 None 就跳过)
            if on_worker_done is not None:
                try:
                    on_worker_done(dim_key, result)
                except Exception:
                    pass  # callback 异常绝不影响主流程
            return result
        except Exception as e:
            # 失败也要通知,这样 UI 能显示 worker 失败状态而不是永远挂 pending
            if on_worker_done is not None:
                try:
                    on_worker_done(dim_key, {"error": str(e)[:200]})
                except Exception:
                    pass
            raise

    tasks = [
        _staggered(idx, dim_key)
        for idx, dim_key in enumerate(dimensions)
    ]

    # 总体超时兜底:即使单 Worker 超时被捕获,线程池层面仍可能因极端情况拖住
    from agent_config import TOTAL_REVIEW_TIMEOUT
    try:
        results = await asyncio.wait_for(
            asyncio.gather(*tasks, return_exceptions=True),
            timeout=TOTAL_REVIEW_TIMEOUT,
        )
    except asyncio.TimeoutError:
        # 外层 deadman switch 触发,把未完成的任务占位为 timeout 错误
        log.error(f"并行评审总体超时({TOTAL_REVIEW_TIMEOUT}s),强制结束")
        results = [
            asyncio.TimeoutError(f"总体超时({TOTAL_REVIEW_TIMEOUT}s)")
            for _ in tasks
        ]

    workers = []
    all_items = []
    total_input = 0
    total_output = 0

    failed_dims = []
    api_unavailable = False
    for dim_key, result in zip(dimensions, results):
        if isinstance(result, Exception):
            err_msg = str(result)
            log.warning(f"[{_cn_label(dim_key)}] Worker 失败: {err_msg[:80]}")
            failed_dims.append(dim_key)
            workers.append({
                "dimension": dim_key,
                "dimension_name": dimensions[dim_key]["name"],
                "error": err_msg,
                "items": [],
            })
            if "503" in err_msg or "No available account" in err_msg or "upstream_error" in err_msg:
                api_unavailable = True
        else:
            workers.append(result)
            all_items.extend(result["items"])
            total_input += result["usage"]["input_tokens"]
            total_output += result["usage"]["output_tokens"]

    # 断路器: 可配置的最大 worker 连续失败数 (CC circuit breaker 模式)
    from agent_config import MAX_CONSECUTIVE_WORKER_FAILURES

    # API 不可用时给出明确提示，不要报"过多 Worker 失败"
    if api_unavailable and len(failed_dims) > MAX_CONSECUTIVE_WORKER_FAILURES:
        raise RuntimeError(f"API 不可用（503），请检查中转站额度后重试")

    # 断路器触发: 失败 worker 数超过阈值
    if len(failed_dims) > MAX_CONSECUTIVE_WORKER_FAILURES:
        raise RuntimeError(f"断路器触发: Worker 失败 ({len(failed_dims)}/4) 超过阈值 {MAX_CONSECUTIVE_WORKER_FAILURES}: {failed_dims}")

    # Scratchpad：记录各 worker 发现的规则 ID（CC coordinatorMode.ts 的 scratchpad 模式）
    scratchpad = {}
    for w in workers:
        if "error" not in w or not w.get("error"):
            dim = w.get("dimension", "")
            scratchpad[dim] = {
                "found_rule_ids": w.get("found_rule_ids", []),
                "item_count": len(w.get("items", [])),
            }

    merged = merge_and_deduplicate(all_items)
    return workers, merged, total_input, total_output


async def parallel_review(client, prd_content, wiki_pages, model_tiers, voting_rounds=1, wiki_path=None, diff_context=None, on_worker_done=None, workspace=None) -> ParallelReviewResult:
    """
    并行执行 4 个评审维度的 worker，合并结果
    - client: anthropic.Anthropic 实例
    - prd_content: PRD 全文字符串
    - wiki_pages: dict {页面标题: 页面内容}，可为空 dict
    - model_tiers: {"opus": "claude-opus-4-6", "sonnet": "claude-sonnet-4-6", "haiku": "claude-haiku-4-5"}
    - voting_rounds: 评审轮次，1=单次（默认），>=2 时启用多数投票
    - on_worker_done: 可选 callback (dim_key, result_dict) -> None,
      每个 worker 完成时调用,给 FastAPI SSE 层推进度。默认 None 保持 CLI 兼容。
    - workspace: 显式工作区路径,FastAPI 并发路径必传(否则 rule_perf_history
      会从 os.environ["WORKSPACE"] 读,多并发下互污染). CLI 模式 None 回退 env.
    返回: {"workers": [...], "merged_items": [...], "total_usage": {...}}
    """
    if voting_rounds <= 1:
        # 单轮评审，保持原有行为
        workers, merged, total_input, total_output = await _single_round_async(
            client, prd_content, wiki_pages, model_tiers, wiki_path, diff_context,
            on_worker_done=on_worker_done, workspace=workspace,
        )
        return {
            "workers": workers,
            "merged_items": merged,
            "total_usage": {
                "input_tokens": total_input,
                "output_tokens": total_output,
            },
        }

    # 多轮评审 + 多数投票
    all_rounds_merged = []  # 每轮的 merged_items
    last_workers = []
    total_input = 0
    total_output = 0

    for round_idx in range(voting_rounds):
        if round_idx > 0:
            log.info(f"[majority_vote] 第 {round_idx + 1}/{voting_rounds} 轮评审，等待 5 秒...")
            await asyncio.sleep(5)

        log.info(f"[majority_vote] 开始第 {round_idx + 1}/{voting_rounds} 轮评审")
        workers, merged, inp, out = await _single_round_async(
            client, prd_content, wiki_pages, model_tiers, wiki_path, diff_context,
            on_worker_done=on_worker_done, workspace=workspace,
        )
        all_rounds_merged.append(merged)
        last_workers = workers
        total_input += inp
        total_output += out
        log.info(f"[majority_vote] 第 {round_idx + 1} 轮完成，发现 {len(merged)} 条改进项")

    # 多数投票筛选
    voted_items = majority_vote(all_rounds_merged, min_votes=2)
    log.info(f"[majority_vote] 投票完成：{sum(len(m) for m in all_rounds_merged)} 条 → {len(voted_items)} 条")

    return {
        "workers": last_workers,
        "merged_items": voted_items,
        "total_usage": {
            "input_tokens": total_input,
            "output_tokens": total_output,
        },
    }


def _single_round_sync(client, prd_content, wiki_pages, model_tiers, wiki_path=None, diff_context=None, workspace=None):
    """单轮顺序评审（内部函数），返回 workers, merged_items, usage

    workspace: 显式工作区路径,FastAPI 并发路径必传(见 _single_round_async 注释).
    """
    dimensions = get_review_dimensions()

    # 读一次 rule performance history，传给所有 worker（避免 4 次 I/O）
    rule_perf_history = try_read_json(_get_rule_perf_history_path(workspace), default=None)

    workers = []
    all_items = []
    total_input = 0
    total_output = 0
    failed_dims = []

    for dim_key in dimensions:
        try:
            result = _run_worker_sync(client, dim_key, prd_content, wiki_pages, model_tiers, rule_perf_history, wiki_path, diff_context)
            workers.append(result)
            all_items.extend(result["items"])
            total_input += result["usage"]["input_tokens"]
            total_output += result["usage"]["output_tokens"]
        except Exception as e:
            err_msg = str(e)
            log.warning(f"[{_cn_label(dim_key)}] Worker 失败: {err_msg[:80]}")
            failed_dims.append(dim_key)
            workers.append({
                "dimension": dim_key,
                "dimension_name": dimensions[dim_key]["name"],
                "error": err_msg,
                "items": [],
            })
            # API 不可用（503/账户耗尽）时直接中断，不浪费后续 worker 的调用
            if "503" in err_msg or "No available account" in err_msg or "upstream_error" in err_msg:
                log.warning(f"API 不可用，跳过剩余 worker")
                for remaining_key in list(dimensions.keys()):
                    if remaining_key not in [w.get("dimension") for w in workers]:
                        failed_dims.append(remaining_key)
                        workers.append({
                            "dimension": remaining_key,
                            "dimension_name": dimensions[remaining_key]["name"],
                            "error": "跳过（API 不可用）",
                            "items": [],
                        })
                break

    # 断路器: 可配置的最大 worker 连续失败数 (CC circuit breaker 模式)
    from agent_config import MAX_CONSECUTIVE_WORKER_FAILURES
    if len(failed_dims) > MAX_CONSECUTIVE_WORKER_FAILURES:
        raise RuntimeError(f"断路器触发: Worker 失败 ({len(failed_dims)}/4) 超过阈值 {MAX_CONSECUTIVE_WORKER_FAILURES}: {failed_dims}")

    # Scratchpad：记录各 worker 发现的规则 ID
    scratchpad = {}
    for w in workers:
        if "error" not in w or not w.get("error"):
            dim = w.get("dimension", "")
            scratchpad[dim] = {
                "found_rule_ids": w.get("found_rule_ids", []),
                "item_count": len(w.get("items", [])),
            }

    merged = merge_and_deduplicate(all_items)
    return workers, merged, total_input, total_output


def parallel_review_sync(client, prd_content, wiki_pages, model_tiers, voting_rounds=1, wiki_path=None, diff_context=None, workspace=None) -> ParallelReviewResult:
    """
    同步版本：顺序执行 4 个 worker（给不方便用 async 的场景）
    接口和返回值与 parallel_review 一致
    - voting_rounds: 评审轮次，1=单次（默认），>=2 时启用多数投票
    - workspace: 显式工作区,FastAPI 并发路径必传(见 parallel_review docstring)
    """
    if voting_rounds <= 1:
        workers, merged, total_input, total_output = _single_round_sync(
            client, prd_content, wiki_pages, model_tiers, wiki_path, diff_context,
            workspace=workspace,
        )
        return {
            "workers": workers,
            "merged_items": merged,
            "total_usage": {
                "input_tokens": total_input,
                "output_tokens": total_output,
            },
        }

    # 多轮评审 + 多数投票
    all_rounds_merged = []
    last_workers = []
    total_input = 0
    total_output = 0

    for round_idx in range(voting_rounds):
        if round_idx > 0:
            log.info(f"[majority_vote] 第 {round_idx + 1}/{voting_rounds} 轮评审，等待 5 秒...")
            time.sleep(5)

        log.info(f"[majority_vote] 开始第 {round_idx + 1}/{voting_rounds} 轮评审")
        workers, merged, inp, out = _single_round_sync(
            client, prd_content, wiki_pages, model_tiers, wiki_path, diff_context,
            workspace=workspace,
        )
        all_rounds_merged.append(merged)
        last_workers = workers
        total_input += inp
        total_output += out
        log.info(f"[majority_vote] 第 {round_idx + 1} 轮完成，发现 {len(merged)} 条改进项")

    voted_items = majority_vote(all_rounds_merged, min_votes=2)
    log.info(f"[majority_vote] 投票完成：{sum(len(m) for m in all_rounds_merged)} 条 → {len(voted_items)} 条")

    return {
        "workers": last_workers,
        "merged_items": voted_items,
        "total_usage": {
            "input_tokens": total_input,
            "output_tokens": total_output,
        },
    }
