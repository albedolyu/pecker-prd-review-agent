"""LangGraph-backed review orchestration.

This module is the production candidate for Pecker's main review flow. It keeps
the existing worker execution path intact, but wraps the review rounds,
aggregation, metrics, and trace in an explicit graph.
"""
from __future__ import annotations

import asyncio
import operator
import time
from typing import Annotated, Any, Dict, List, Optional, TypedDict

from langgraph.graph import END, StateGraph
from langgraph.types import Send

from io_utils import try_read_json
from logger import get_logger
from review.aggregation import majority_vote
from review.gateway_resilience import build_resilience_summary
from review.types import ParallelReviewResult

log = get_logger("parallel.langgraph")

try:
    from review.metrics_store import record_event as _metrics_record
except Exception:  # noqa: BLE001
    def _metrics_record(*_a, **_kw):  # type: ignore[no-redef]
        return False


class LangGraphMainReviewState(TypedDict, total=False):
    round_idx: int
    active_round: int
    rounds_merged: List[List[Dict[str, Any]]]
    last_workers: List[Dict[str, Any]]
    round_worker_results: Annotated[List[Dict[str, Any]], operator.add]
    total_input: int
    total_output: int
    workers: List[Dict[str, Any]]
    merged_items: List[Dict[str, Any]]
    total_usage: Dict[str, int]
    worker_node_statuses: List[Dict[str, Any]]
    resilience: Dict[str, Any]
    trace: Annotated[List[str], operator.add]


def build_langgraph_parallel_review_app(
    *,
    client,
    prd_content: str,
    wiki_pages: Dict[str, str],
    model_tiers: Dict[str, str],
    voting_rounds: int,
    wiki_path=None,
    diff_context=None,
    on_worker_done=None,
    workspace: Optional[str] = None,
    on_tool_call=None,
    round_delay_seconds: float = 5.0,
    checkpointer: Any = None,
):
    """Build the main review graph with observable per-worker nodes."""
    from review import orchestration as orchestration_mod

    total_rounds = max(1, int(voting_rounds or 1))
    dimensions = orchestration_mod.get_review_dimensions()
    dim_keys = list(dimensions)
    worker_batch_size = orchestration_mod._get_worker_batch_size(len(dim_keys))
    worker_slots = asyncio.Semaphore(worker_batch_size)
    rule_perf_history = try_read_json(
        orchestration_mod._get_rule_perf_history_path(workspace),
        default=None,
    )

    async def prepare_round(state: LangGraphMainReviewState) -> Dict[str, Any]:
        round_no = int(state.get("round_idx", 0)) + 1
        if round_no > 1:
            log.info("[langgraph] starting review round %s/%s after delay", round_no, total_rounds)
            await asyncio.sleep(round_delay_seconds)
        else:
            log.info("[langgraph] starting review round 1/%s", total_rounds)
        return {
            "active_round": round_no,
            "trace": [f"prepare_round:{round_no}"],
        }

    def fan_out_workers(state: LangGraphMainReviewState) -> List[Send]:
        round_no = int(state.get("active_round", 1))
        return [
            Send(
                "run_worker_node",
                {
                    "round_no": round_no,
                    "dim_key": dim_key,
                    "worker_index": idx,
                },
            )
            for idx, dim_key in enumerate(dim_keys)
        ]

    async def run_worker_node(state: Dict[str, Any]) -> Dict[str, Any]:
        round_no = int(state.get("round_no", 1))
        dim_key = str(state.get("dim_key"))
        worker_index = int(state.get("worker_index", 0))
        async with worker_slots:
            result = await orchestration_mod._run_dimension_worker_async(
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
                stagger_index=worker_index,
                dimensions=dimensions,
            )
        status = result.get("error_type") if result.get("error") else "success"
        return {
            "round_worker_results": [
                {
                    "round_no": round_no,
                    "worker_index": worker_index,
                    "dimension": dim_key,
                    "result": result,
                }
            ],
            "trace": [f"worker:{round_no}:{dim_key}:{status}"],
        }

    def finalize_round(state: LangGraphMainReviewState) -> Dict[str, Any]:
        round_no = int(state.get("active_round", 1))
        round_records = [
            record for record in state.get("round_worker_results", [])
            if int(record.get("round_no", 0)) == round_no
        ]
        round_records.sort(key=lambda record: int(record.get("worker_index", 0)))
        workers = [record.get("result", {}) for record in round_records]
        items: List[Dict[str, Any]] = []
        inp = 0
        out = 0
        for worker in workers:
            if not worker.get("error"):
                items.extend(worker.get("items") or [])
            usage = worker.get("usage") or {}
            inp += int(usage.get("input_tokens") or 0)
            out += int(usage.get("output_tokens") or 0)
        from review.aggregation import merge_and_deduplicate

        merged = merge_and_deduplicate(items)
        return {
            "round_idx": round_no,
            "rounds_merged": [*state.get("rounds_merged", []), merged],
            "last_workers": workers,
            "total_input": int(state.get("total_input", 0)) + inp,
            "total_output": int(state.get("total_output", 0)) + out,
            "trace": [f"finalize_round:{round_no}"],
        }

    def route_after_round(state: LangGraphMainReviewState) -> str:
        return "prepare_round" if int(state.get("round_idx", 0)) < total_rounds else "finalize_review"

    def finalize_review(state: LangGraphMainReviewState) -> Dict[str, Any]:
        rounds_merged = state.get("rounds_merged", [])
        if total_rounds <= 1:
            merged_items = rounds_merged[-1] if rounds_merged else []
        else:
            merged_items = majority_vote(rounds_merged, min_votes=2)
        total_usage = {
            "input_tokens": int(state.get("total_input", 0)),
            "output_tokens": int(state.get("total_output", 0)),
        }
        workers = state.get("last_workers", [])
        return {
            "workers": workers,
            "merged_items": merged_items,
            "total_usage": total_usage,
            "worker_node_statuses": [
                {
                    "dimension": worker.get("dimension", ""),
                    "status": worker.get("status") or ("failed" if worker.get("error") else "success"),
                    "error_type": worker.get("error_type", ""),
                }
                for worker in workers
            ],
            "resilience": build_resilience_summary(
                workers,
                current_batch_size=worker_batch_size,
                total_workers=len(dim_keys),
            ),
            "trace": ["finalize_review"],
        }

    graph = StateGraph(LangGraphMainReviewState)
    graph.add_node("prepare_round", prepare_round)
    graph.add_node("run_worker_node", run_worker_node)
    graph.add_node("finalize_round", finalize_round)
    graph.add_node("finalize_review", finalize_review)
    graph.set_entry_point("prepare_round")
    graph.add_conditional_edges(
        "prepare_round",
        fan_out_workers,
    )
    graph.add_edge("run_worker_node", "finalize_round")
    graph.add_conditional_edges(
        "finalize_round",
        route_after_round,
        {"prepare_round": "prepare_round", "finalize_review": "finalize_review"},
    )
    graph.add_edge("finalize_review", END)

    compile_kwargs: Dict[str, Any] = {}
    if checkpointer is not None:
        compile_kwargs["checkpointer"] = checkpointer
    return graph.compile(**compile_kwargs)


async def langgraph_parallel_review(
    client,
    prd_content,
    wiki_pages,
    model_tiers,
    voting_rounds=1,
    wiki_path=None,
    diff_context=None,
    on_worker_done=None,
    workspace=None,
    on_tool_call=None,
    checkpointer: Any = None,
    thread_id: Optional[str] = None,
) -> ParallelReviewResult:
    """Public async entrypoint matching review.orchestration.parallel_review."""
    total_rounds = max(1, int(voting_rounds or 1))
    _metrics_record(
        "review.started",
        workspace=workspace,
        details={"voting_rounds": total_rounds, "orchestrator": "langgraph"},
    )
    started_at = time.time()
    try:
        app = build_langgraph_parallel_review_app(
            client=client,
            prd_content=prd_content,
            wiki_pages=wiki_pages,
            model_tiers=model_tiers,
            voting_rounds=total_rounds,
            wiki_path=wiki_path,
            diff_context=diff_context,
            on_worker_done=on_worker_done,
            workspace=workspace,
            on_tool_call=on_tool_call,
            checkpointer=checkpointer,
        )
        config = None
        if thread_id:
            config = {"configurable": {"thread_id": thread_id}}
        state = await app.ainvoke(
            {
                "round_idx": 0,
                "active_round": 0,
                "rounds_merged": [],
                "last_workers": [],
                "round_worker_results": [],
                "total_input": 0,
                "total_output": 0,
                "trace": [],
            },
            config=config,
        )
    except Exception as exc:
        _metrics_record(
            "review.failed",
            workspace=workspace,
            status="failed",
            duration_ms=int((time.time() - started_at) * 1000),
            details={"error": str(exc)[:200], "orchestrator": "langgraph"},
        )
        raise

    workers = state.get("workers", [])
    merged_items = state.get("merged_items", [])
    total_usage = state.get("total_usage", {"input_tokens": 0, "output_tokens": 0})
    _metrics_record(
        "review.completed",
        workspace=workspace,
        status="success",
        duration_ms=int((time.time() - started_at) * 1000),
        details={
            "merged_items": len(merged_items),
            "input_tokens": total_usage.get("input_tokens", 0),
            "output_tokens": total_usage.get("output_tokens", 0),
            "failed_workers": sum(1 for worker in workers if worker.get("error")),
            "orchestrator": "langgraph",
            "resilience": state.get("resilience", {}),
        },
    )
    return {
        "workers": workers,
        "merged_items": merged_items,
        "total_usage": total_usage,
        "orchestrator": "langgraph",
        "graph_trace": state.get("trace", []),
        "worker_node_statuses": state.get("worker_node_statuses", []),
        "resilience": state.get("resilience", {}),
    }
