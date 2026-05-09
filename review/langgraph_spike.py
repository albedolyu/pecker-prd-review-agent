"""Experimental LangGraph review orchestration spike.

This module intentionally does not replace the production review pipeline. It
captures the smallest useful graph shape for Pecker: isolated workers, merge,
and a conditional advisor gate.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, TypedDict

from langgraph.graph import END, StateGraph


class LangGraphReviewState(TypedDict, total=False):
    prd_content: str
    wiki_pages: Dict[str, str]
    workers: Dict[str, Dict[str, Any]]
    worker_errors: Dict[str, str]
    merged_items: List[Dict[str, Any]]
    should_run_advisor: bool
    advisor_ran: bool
    advisor_result: Optional[Dict[str, Any]]
    advisor_error: str
    trace: List[str]


WorkerRunner = Callable[[str, LangGraphReviewState], Dict[str, Any]]
MergeFn = Callable[[List[Dict[str, Any]], LangGraphReviewState], List[Dict[str, Any]]]
AdvisorRunner = Callable[[List[Dict[str, Any]], LangGraphReviewState], Dict[str, Any]]
AdvisorPolicy = Callable[[LangGraphReviewState], bool]


def _append_trace(state: LangGraphReviewState, step: str) -> List[str]:
    return [*state.get("trace", []), step]


def _default_merge(items: List[Dict[str, Any]], _state: LangGraphReviewState) -> List[Dict[str, Any]]:
    return items


def _default_advisor_policy(state: LangGraphReviewState) -> bool:
    return any(item.get("severity") == "must" for item in state.get("merged_items", []))


def _default_advisor_runner(
    items: List[Dict[str, Any]],
    _state: LangGraphReviewState,
) -> Dict[str, Any]:
    return {"verdict": "SKIPPED", "checked": len(items)}


def build_langgraph_review_spike(
    *,
    dimensions: List[str],
    worker_runner: WorkerRunner,
    merge_fn: Optional[MergeFn] = None,
    advisor_runner: Optional[AdvisorRunner] = None,
    advisor_policy: Optional[AdvisorPolicy] = None,
    checkpointer: Any = None,
):
    """Build a minimal LangGraph app for review-flow experimentation.

    The graph is deliberately injectable so tests can exercise orchestration
    behavior without live LLM calls.
    """
    merge_items_fn = merge_fn or _default_merge
    run_advisor_fn = advisor_runner or _default_advisor_runner
    should_run_advisor_fn = advisor_policy or _default_advisor_policy

    def run_workers(state: LangGraphReviewState) -> Dict[str, Any]:
        workers: Dict[str, Dict[str, Any]] = {}
        worker_errors: Dict[str, str] = {}
        for dim_key in dimensions:
            try:
                result = dict(worker_runner(dim_key, state))
                result.setdefault("dimension", dim_key)
                result.setdefault("items", [])
                workers[dim_key] = result
            except Exception as exc:  # noqa: BLE001 - spike captures failed worker state
                worker_errors[dim_key] = str(exc)
                workers[dim_key] = {
                    "dimension": dim_key,
                    "items": [],
                    "error": str(exc),
                }
        return {
            "workers": workers,
            "worker_errors": worker_errors,
            "trace": _append_trace(state, "run_workers"),
        }

    def merge_items(state: LangGraphReviewState) -> Dict[str, Any]:
        items: List[Dict[str, Any]] = []
        for dim_key in dimensions:
            worker = state.get("workers", {}).get(dim_key, {})
            items.extend(worker.get("items", []) or [])
        return {
            "merged_items": merge_items_fn(items, state),
            "trace": _append_trace(state, "merge_items"),
        }

    def decide_advisor(state: LangGraphReviewState) -> Dict[str, Any]:
        should_run = bool(should_run_advisor_fn(state))
        step = "decide_advisor:run" if should_run else "decide_advisor:skip"
        return {
            "should_run_advisor": should_run,
            "advisor_ran": False,
            "trace": _append_trace(state, step),
        }

    def route_after_advisor_decision(state: LangGraphReviewState) -> str:
        return "run_advisor" if state.get("should_run_advisor") else END

    def run_advisor(state: LangGraphReviewState) -> Dict[str, Any]:
        try:
            advisor_result = run_advisor_fn(state.get("merged_items", []), state)
            return {
                "advisor_ran": True,
                "advisor_result": advisor_result,
                "trace": _append_trace(state, "run_advisor"),
            }
        except Exception as exc:  # noqa: BLE001 - advisor should degrade without erasing workers
            return {
                "advisor_ran": False,
                "advisor_error": str(exc),
                "trace": _append_trace(state, "run_advisor:error"),
            }

    graph = StateGraph(LangGraphReviewState)
    graph.add_node("run_workers", run_workers)
    graph.add_node("merge_items", merge_items)
    graph.add_node("decide_advisor", decide_advisor)
    graph.add_node("run_advisor", run_advisor)
    graph.set_entry_point("run_workers")
    graph.add_edge("run_workers", "merge_items")
    graph.add_edge("merge_items", "decide_advisor")
    graph.add_conditional_edges(
        "decide_advisor",
        route_after_advisor_decision,
        {"run_advisor": "run_advisor", END: END},
    )
    graph.add_edge("run_advisor", END)
    compile_kwargs: Dict[str, Any] = {}
    if checkpointer is not None:
        compile_kwargs["checkpointer"] = checkpointer
    return graph.compile(**compile_kwargs)
