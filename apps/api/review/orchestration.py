"""Cluster D — 并行评审编排 (4 Worker 并发 + 多轮投票).

从 parallel_review.py 拆出 (2026-04-16 继续 SPLIT_PLAN 阶段 5):
- _single_round_async / _single_round_sync: 单轮 4 Worker 并行
- parallel_review / parallel_review_sync: 对外公共 API (支持 voting_rounds)

本模块是Pecker"4 Worker 并行 + 苍鹰仲裁"拓扑里的 Worker 层编排。依赖:
- review.worker: 单 Worker 执行
- review.aggregation: merge_and_deduplicate / majority_vote
- review.dimensions: 维度配置 + 反馈历史路径
"""

import asyncio
import json
import os
import time

from io_utils import try_read_json
from logger import get_logger
from review.aggregation import majority_vote, merge_and_deduplicate
from review.dimensions import (
    _cn_label,
    _get_rule_perf_history_path,
    get_review_dimensions,
)
from review.gateway_resilience import (
    classify_worker_error,
    is_transient_error_type,
)
from review.types import ParallelReviewResult
from review.worker import _run_worker_async, _run_worker_sync

# Metrics 埋点 (零开销 — 失败 silent skip, 不阻 review 主流程)
try:
    from review.metrics_store import record_event as _metrics_record
except Exception:  # noqa: BLE001
    def _metrics_record(*_a, **_kw):  # type: ignore[no-redef]
        return False

log = get_logger("parallel")


def _get_review_orchestrator_mode() -> str:
    raw = os.environ.get("PECKER_REVIEW_ORCHESTRATOR", "langgraph").strip().lower()
    aliases = {
        "0": "legacy",
        "off": "legacy",
        "old": "legacy",
        "rollback": "legacy",
        "legacy": "legacy",
        "1": "langgraph",
        "on": "langgraph",
        "graph": "langgraph",
        "langgraph": "langgraph",
    }
    mode = aliases.get(raw)
    if mode is None:
        log.warning("Invalid PECKER_REVIEW_ORCHESTRATOR=%r; using langgraph", raw)
        return "langgraph"
    return mode


def _get_worker_batch_size(total_workers: int) -> int:
    raw = os.environ.get("PECKER_WORKER_BATCH_SIZE", "").strip()
    if not raw:
        return max(1, total_workers)
    try:
        value = int(raw)
    except ValueError:
        log.warning("Invalid PECKER_WORKER_BATCH_SIZE=%r; using full parallel workers", raw)
        return max(1, total_workers)
    if value <= 0:
        log.warning("Invalid PECKER_WORKER_BATCH_SIZE=%r; using full parallel workers", raw)
        return max(1, total_workers)
    return max(1, min(value, total_workers))


def _worker_error_result(dim_key, dimensions, error) -> dict:
    err_msg = str(error)
    err_type = classify_worker_error(error)
    status = "timeout" if err_type in {"timeout", "gateway_timeout"} else "failed"
    return {
        "dimension": dim_key,
        "dimension_name": dimensions.get(dim_key, {}).get("name", dim_key),
        "error": err_msg,
        "error_type": err_type,
        "items": [],
        "usage": {"input_tokens": 0, "output_tokens": 0},
        "status": status,
    }


def _normalize_worker_result(dim_key, dimensions, result) -> dict:
    if isinstance(result, Exception):
        return _worker_error_result(dim_key, dimensions, result)
    if not isinstance(result, dict):
        return _worker_error_result(dim_key, dimensions, RuntimeError(f"invalid worker result: {type(result).__name__}"))
    result.setdefault("dimension", dim_key)
    result.setdefault("dimension_name", dimensions.get(dim_key, {}).get("name", dim_key))
    result.setdefault("items", [])
    result.setdefault("usage", {"input_tokens": 0, "output_tokens": 0})
    if result.get("error"):
        result.setdefault("error_type", classify_worker_error(result.get("error")))
        result.setdefault("status", "timeout" if result["error_type"] in {"timeout", "gateway_timeout"} else "failed")
    else:
        result.setdefault("status", "success")
    return result


def _gateway_recovery_enabled() -> bool:
    return os.environ.get("PECKER_ENABLE_WORKER_GATEWAY_RECOVERY", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


async def _retry_dimension_worker_recovery(
    client,
    dim_key,
    prd_content,
    wiki_pages,
    model_tiers,
    rule_perf_history,
    wiki_path=None,
    diff_context=None,
    on_tool_call=None,
    *,
    dimensions,
    first_result: dict,
):
    first_error = str(first_result.get("error") or "")
    first_error_type = str(first_result.get("error_type") or classify_worker_error(first_error))
    try:
        recovered = await _run_worker_async(
            client,
            dim_key,
            prd_content,
            wiki_pages,
            model_tiers,
            rule_perf_history,
            wiki_path,
            diff_context,
            on_tool_call,
            retry_on_timeout=False,
            recovery_mode=True,
        )
        recovered = _normalize_worker_result(dim_key, dimensions, recovered)
        recovery = dict(recovered.get("recovery") or {})
        recovery.update({
            "attempts": 2,
            "first_error": first_error[:200],
            "first_error_type": first_error_type,
            "mode": "gateway_recovery",
        })
        recovered["recovery"] = recovery
        if not recovered.get("error"):
            recovered["status"] = "recovered"
        else:
            recovered["recovery"]["recovery_error"] = str(recovered.get("error"))[:200]
        return recovered
    except Exception as recovery_exc:
        first_result["recovery"] = {
            "attempts": 2,
            "first_error": first_error[:200],
            "first_error_type": first_error_type,
            "mode": "gateway_recovery",
            "recovery_error": str(recovery_exc)[:200],
        }
        return first_result


async def _run_dimension_worker_async(
    client,
    dim_key,
    prd_content,
    wiki_pages,
    model_tiers,
    rule_perf_history,
    wiki_path=None,
    diff_context=None,
    on_worker_done=None,
    workspace=None,
    on_tool_call=None,
    *,
    stagger_index: int = 0,
    dimensions=None,
):
    dimensions = dimensions or get_review_dimensions()
    await asyncio.sleep(stagger_index * 0.3)
    _w_t0 = time.time()
    try:
        result = await _run_worker_async(
            client, dim_key, prd_content, wiki_pages, model_tiers,
            rule_perf_history, wiki_path, diff_context, on_tool_call,
        )
        result = _normalize_worker_result(dim_key, dimensions, result)
        if (
            result.get("error")
            and _gateway_recovery_enabled()
            and is_transient_error_type(str(result.get("error_type") or ""))
        ):
            result = await _retry_dimension_worker_recovery(
                client,
                dim_key,
                prd_content,
                wiki_pages,
                model_tiers,
                rule_perf_history,
                wiki_path,
                diff_context,
                on_tool_call,
                dimensions=dimensions,
                first_result=result,
            )
        if on_worker_done is not None:
            try:
                on_worker_done(dim_key, result)
            except Exception:
                pass
        _u = result.get("usage") or {}
        status = "failed" if result.get("error") else "success"
        _metrics_record(
            "worker.completed",
            workspace=workspace,
            duration_ms=int((time.time() - _w_t0) * 1000),
            model=(result.get("model") or model_tiers.get("sonnet")),
            cost_usd=result.get("cost_usd"),
            status=status,
            details={
                "dim_key": dim_key,
                "items": len(result.get("items") or []),
                "input_tokens": _u.get("input_tokens"),
                "output_tokens": _u.get("output_tokens"),
                "error_type": result.get("error_type"),
            },
        )
        return result
    except Exception as e:
        result = _worker_error_result(dim_key, dimensions, e)
        if _gateway_recovery_enabled() and is_transient_error_type(str(result.get("error_type") or "")):
            result = await _retry_dimension_worker_recovery(
                client,
                dim_key,
                prd_content,
                wiki_pages,
                model_tiers,
                rule_perf_history,
                wiki_path,
                diff_context,
                on_tool_call,
                dimensions=dimensions,
                first_result=result,
            )
        if on_worker_done is not None:
            try:
                on_worker_done(dim_key, result)
            except Exception:
                pass
        _metrics_record(
            "worker.completed",
            workspace=workspace,
            duration_ms=int((time.time() - _w_t0) * 1000),
            status="failed",
            details={"dim_key": dim_key, "error": str(e)[:200], "error_type": result.get("error_type")},
        )
        return result


async def _single_round_async(client, prd_content, wiki_pages, model_tiers, wiki_path=None, diff_context=None, on_worker_done=None, workspace=None, on_tool_call=None):
    """单轮并行评审（内部函数），返回 workers, merged_items, usage

    Args:
        on_worker_done: 可选 callback,签名为 (dim_key: str, result: dict) -> None
            每个 worker 完成时(成功或失败)都会调用,让上层(FastAPI SSE)感知进度。
            默认 None,保持向后兼容,CLI 现有流程零影响。
        workspace: 显式工作区路径(FastAPI 并发路径必传,否则 rule_perf_history 会
            从 os.environ["WORKSPACE"] 读,并发下会互污染)。CLI 模式为 None 回退读 env。
    """
    # dimensions 完全由 get_review_dimensions() 动态决定 (YAML 或默认 dict);
    # orchestration 层不写死 "4 worker"、不硬编码 dim_key. 新增维度只改
    # review/dimensions.py 的 YAML / 默认表, 本函数和 _single_round_sync 零改动.
    dimensions = get_review_dimensions()

    # 读一次 rule performance history，传给所有 worker（避免 N 次 I/O）
    rule_perf_history = try_read_json(_get_rule_perf_history_path(workspace), default=None)

    dim_keys = list(dimensions)
    worker_batch_size = _get_worker_batch_size(len(dim_keys))

    def _total_timeout_result(dim_key, timeout_seconds):
        result = _worker_error_result(
            dim_key,
            dimensions,
            asyncio.TimeoutError(f"总体超时({timeout_seconds}s)"),
        )
        if on_worker_done is not None:
            try:
                on_worker_done(dim_key, result)
            except Exception:
                pass
        return result

    async def _run_worker_batches_with_deadline(total_timeout):
        ordered_results = []
        deadline = time.monotonic() + max(0.1, float(total_timeout))
        for start in range(0, len(dim_keys), worker_batch_size):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                log.error("并行评审总体超时(%ss),剩余方向标记为超时", total_timeout)
                ordered_results.extend(
                    _total_timeout_result(dim_key, total_timeout)
                    for dim_key in dim_keys[start:]
                )
                break

            batch = dim_keys[start:start + worker_batch_size]
            tasks = {
                asyncio.create_task(
                    _run_dimension_worker_async(
                        client,
                        dim_key,
                        prd_content,
                        wiki_pages,
                        model_tiers,
                        rule_perf_history,
                        wiki_path,
                        diff_context,
                        on_worker_done=on_worker_done,
                        workspace=workspace,
                        on_tool_call=on_tool_call,
                        stagger_index=idx,
                        dimensions=dimensions,
                    )
                ): dim_key
                for idx, dim_key in enumerate(batch)
            }
            done, pending = await asyncio.wait(tasks.keys(), timeout=remaining)

            if pending:
                log.error(
                    "并行评审总体超时(%ss),已完成批次结果将保留,未完成方向标记为超时",
                    total_timeout,
                )
                for task in pending:
                    task.cancel()
                try:
                    await asyncio.wait_for(
                        asyncio.gather(*pending, return_exceptions=True),
                        timeout=0.5,
                    )
                except asyncio.TimeoutError:
                    pass

            batch_results = {}
            for task in done:
                dim_key = tasks[task]
                try:
                    batch_results[dim_key] = task.result()
                except Exception as exc:  # noqa: BLE001
                    batch_results[dim_key] = exc

            for dim_key in batch:
                if dim_key in batch_results:
                    ordered_results.append(batch_results[dim_key])
                else:
                    ordered_results.append(_total_timeout_result(dim_key, total_timeout))

            if pending:
                next_start = start + len(batch)
                ordered_results.extend(
                    _total_timeout_result(dim_key, total_timeout)
                    for dim_key in dim_keys[next_start:]
                )
                break
        return ordered_results

    # 总体超时兜底:即使单 Worker 超时被捕获,线程池层面仍可能因极端情况拖住
    from agent_config import TOTAL_REVIEW_TIMEOUT
    results = await _run_worker_batches_with_deadline(TOTAL_REVIEW_TIMEOUT)

    workers = []
    all_items = []
    total_input = 0
    total_output = 0

    failed_dims = []
    api_unavailable = False
    for dim_key, result in zip(dim_keys, results):
        result = _normalize_worker_result(dim_key, dimensions, result)
        if result.get("error"):
            err_msg = str(result.get("error") or "")
            log.warning(f"[{_cn_label(dim_key)}] Worker 失败: {err_msg[:80]}")
            failed_dims.append(dim_key)
            workers.append(result)
            if result.get("error_type") == "api_unavailable":
                api_unavailable = True
        else:
            workers.append(result)
            all_items.extend(result["items"])
            total_input += result["usage"]["input_tokens"]
            total_output += result["usage"]["output_tokens"]

    # 断路器: 可配置的最大 worker 连续失败数 (CC circuit breaker 模式)
    from agent_config import MAX_CONSECUTIVE_WORKER_FAILURES

    has_usable_items = len(all_items) > 0

    # API 不可用且没有任何有效产出时给出明确提示，不要报"过多 Worker 失败"
    if api_unavailable and len(failed_dims) > MAX_CONSECUTIVE_WORKER_FAILURES and not has_usable_items:
        raise RuntimeError(f"API 不可用（503），请检查中转站额度后重试")

    # 断路器触发: 失败 worker 数超过阈值且没有任何有效产出。
    # 如果至少有一个方向产出了意见，保留部分结果交给上层降级提示，避免 PM 因单次中转站抖动丢掉已完成工作。
    if len(failed_dims) > MAX_CONSECUTIVE_WORKER_FAILURES and not has_usable_items:
        raise RuntimeError(f"断路器触发: Worker 失败 ({len(failed_dims)}/4) 超过阈值 {MAX_CONSECUTIVE_WORKER_FAILURES}: {failed_dims}")
    if len(failed_dims) > MAX_CONSECUTIVE_WORKER_FAILURES and has_usable_items:
        log.warning(
            "Worker 失败数超过阈值但保留部分评审结果: failed=%s items=%s",
            failed_dims,
            len(all_items),
        )

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


async def _parallel_review_legacy(client, prd_content, wiki_pages, model_tiers, voting_rounds=1, wiki_path=None, diff_context=None, on_worker_done=None, workspace=None, on_tool_call=None) -> ParallelReviewResult:
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
        _metrics_record("review.started", workspace=workspace, details={"voting_rounds": 1})
        _t0 = time.time()
        try:
            workers, merged, total_input, total_output = await _single_round_async(
                client, prd_content, wiki_pages, model_tiers, wiki_path, diff_context,
                on_worker_done=on_worker_done, workspace=workspace, on_tool_call=on_tool_call,
            )
        except Exception as e:
            _metrics_record(
                "review.failed", workspace=workspace, status="failed",
                duration_ms=int((time.time() - _t0) * 1000),
                details={"error": str(e)[:200]},
            )
            raise
        _metrics_record(
            "review.completed", workspace=workspace, status="success",
            duration_ms=int((time.time() - _t0) * 1000),
            details={
                "merged_items": len(merged),
                "input_tokens": total_input,
                "output_tokens": total_output,
                "failed_workers": sum(1 for w in workers if w.get("error")),
            },
        )
        return {
            "workers": workers,
            "merged_items": merged,
            "total_usage": {
                "input_tokens": total_input,
                "output_tokens": total_output,
            },
            "orchestrator": "legacy",
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
            on_worker_done=on_worker_done, workspace=workspace, on_tool_call=on_tool_call,
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
        "orchestrator": "legacy",
    }


async def parallel_review(client, prd_content, wiki_pages, model_tiers, voting_rounds=1, wiki_path=None, diff_context=None, on_worker_done=None, workspace=None, on_tool_call=None, checkpointer=None, thread_id=None) -> ParallelReviewResult:
    """Run the review through the selected orchestration backend.

    Default is LangGraph so production gets checkpointable, inspectable flow.
    Roll back with PECKER_REVIEW_ORCHESTRATOR=legacy without changing code.
    """
    if _get_review_orchestrator_mode() == "legacy":
        return await _parallel_review_legacy(
            client, prd_content, wiki_pages, model_tiers,
            voting_rounds=voting_rounds,
            wiki_path=wiki_path,
            diff_context=diff_context,
            on_worker_done=on_worker_done,
            workspace=workspace,
            on_tool_call=on_tool_call,
        )

    graph_runner = globals().get("langgraph_parallel_review")
    if graph_runner is None:
        from review.langgraph_orchestration import langgraph_parallel_review as graph_runner
    return await graph_runner(
        client, prd_content, wiki_pages, model_tiers,
        voting_rounds=voting_rounds,
        wiki_path=wiki_path,
        diff_context=diff_context,
        on_worker_done=on_worker_done,
        workspace=workspace,
        on_tool_call=on_tool_call,
        checkpointer=checkpointer,
        thread_id=thread_id,
    )


def _single_round_sync(client, prd_content, wiki_pages, model_tiers, wiki_path=None, diff_context=None, workspace=None, on_tool_call=None):
    """单轮顺序评审（内部函数），返回 workers, merged_items, usage

    workspace: 显式工作区路径,FastAPI 并发路径必传(见 _single_round_async 注释).

    同 _single_round_async: dimensions 完全由 get_review_dimensions() 动态决定,
    orchestration 不写死 dim_key 数量.
    """
    dimensions = get_review_dimensions()

    # 读一次 rule performance history，传给所有 worker（避免 N 次 I/O）
    rule_perf_history = try_read_json(_get_rule_perf_history_path(workspace), default=None)

    workers = []
    all_items = []
    total_input = 0
    total_output = 0
    failed_dims = []

    for dim_key in dimensions:
        try:
            result = _run_worker_sync(client, dim_key, prd_content, wiki_pages, model_tiers, rule_perf_history, wiki_path, diff_context, on_tool_call)
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


def parallel_review_sync(client, prd_content, wiki_pages, model_tiers, voting_rounds=1, wiki_path=None, diff_context=None, workspace=None, on_tool_call=None) -> ParallelReviewResult:
    """
    同步版本：顺序执行 4 个 worker（给不方便用 async 的场景）
    接口和返回值与 parallel_review 一致
    - voting_rounds: 评审轮次，1=单次（默认），>=2 时启用多数投票
    - workspace: 显式工作区,FastAPI 并发路径必传(见 parallel_review docstring)
    """
    if voting_rounds <= 1:
        workers, merged, total_input, total_output = _single_round_sync(
            client, prd_content, wiki_pages, model_tiers, wiki_path, diff_context,
            workspace=workspace, on_tool_call=on_tool_call,
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
            workspace=workspace, on_tool_call=on_tool_call,
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
