from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_parallel_review_uses_langgraph_orchestrator_by_default(monkeypatch):
    import review.orchestration as orchestration

    calls: list[str] = []

    async def fake_single_round(*_args, **_kwargs):
        calls.append("legacy")
        return [], [], 0, 0

    async def fake_langgraph_review(*_args, **_kwargs):
        calls.append("langgraph")
        return {
            "workers": [],
            "merged_items": [],
            "total_usage": {"input_tokens": 0, "output_tokens": 0},
            "orchestrator": "langgraph",
        }

    monkeypatch.delenv("PECKER_REVIEW_ORCHESTRATOR", raising=False)
    monkeypatch.setattr(orchestration, "_single_round_async", fake_single_round)
    monkeypatch.setattr(orchestration, "langgraph_parallel_review", fake_langgraph_review, raising=False)

    result = await orchestration.parallel_review(
        client=None,
        prd_content="prd",
        wiki_pages={},
        model_tiers={"sonnet": "test-model"},
        workspace="workspace",
    )

    assert calls == ["langgraph"]
    assert result["orchestrator"] == "langgraph"


@pytest.mark.asyncio
async def test_parallel_review_can_rollback_to_legacy_orchestrator(monkeypatch):
    import review.orchestration as orchestration

    calls: list[str] = []

    async def fake_single_round(*_args, **_kwargs):
        calls.append("legacy")
        return [], [], 0, 0

    async def fake_langgraph_review(*_args, **_kwargs):
        calls.append("langgraph")
        raise AssertionError("legacy rollback must not call LangGraph")

    monkeypatch.setenv("PECKER_REVIEW_ORCHESTRATOR", "legacy")
    monkeypatch.setattr(orchestration, "_single_round_async", fake_single_round)
    monkeypatch.setattr(orchestration, "langgraph_parallel_review", fake_langgraph_review, raising=False)

    result = await orchestration.parallel_review(
        client=None,
        prd_content="prd",
        wiki_pages={},
        model_tiers={"sonnet": "test-model"},
        workspace="workspace",
    )

    assert calls == ["legacy"]
    assert result["orchestrator"] == "legacy"


@pytest.mark.asyncio
async def test_langgraph_parallel_review_preserves_worker_callbacks_and_trace(monkeypatch):
    import review.langgraph_orchestration as langgraph_orchestration
    import review.orchestration as orchestration

    worker_done: list[str] = []
    dimensions = {"structure": {"name": "业务完整性"}}

    async def fake_run_worker_async(*args, **_kwargs):
        dim_key = args[1]
        return {
            "dimension": dim_key,
            "dimension_name": dimensions[dim_key]["name"],
            "items": [
                {
                    "id": "s-1",
                    "dimension": "structure",
                    "location": "PRD",
                    "issue": "same issue",
                    "suggestion": "fix it",
                    "severity": "must",
                }
            ],
            "usage": {"input_tokens": 3, "output_tokens": 5},
        }

    monkeypatch.setattr(orchestration, "get_review_dimensions", lambda: dimensions)
    monkeypatch.setattr(orchestration, "_run_worker_async", fake_run_worker_async)

    result = await langgraph_orchestration.langgraph_parallel_review(
        client=None,
        prd_content="prd",
        wiki_pages={},
        model_tiers={"sonnet": "test-model"},
        on_worker_done=lambda dim, _result: worker_done.append(dim),
        workspace="workspace",
    )

    assert worker_done == ["structure"]
    assert result["orchestrator"] == "langgraph"
    assert result["total_usage"] == {"input_tokens": 3, "output_tokens": 5}
    assert result["graph_trace"] == [
        "prepare_round:1",
        "worker:1:structure:success",
        "finalize_round:1",
        "finalize_review",
    ]


@pytest.mark.asyncio
async def test_langgraph_parallel_review_exposes_worker_nodes_and_resilience(monkeypatch):
    import review.langgraph_orchestration as langgraph_orchestration
    import review.orchestration as orchestration

    dimensions = {
        "structure": {"name": "业务完整性"},
        "quality": {"name": "使用体验"},
    }
    worker_done: list[tuple[str, str]] = []

    async def fast_sleep(_seconds: float):
        return None

    async def fake_run_worker_async(*args, **_kwargs):
        dim_key = args[1]
        if dim_key == "quality":
            raise RuntimeError("Cloudflare 524: a timeout occurred")
        return {
            "dimension": dim_key,
            "dimension_name": dimensions[dim_key]["name"],
            "items": [
                {
                    "id": f"{dim_key}-1",
                    "dimension": dim_key,
                    "location": "PRD",
                    "issue": "same issue",
                    "suggestion": "fix it",
                    "severity": "should",
                }
            ],
            "usage": {"input_tokens": 2, "output_tokens": 3},
        }

    monkeypatch.setenv("PECKER_WORKER_BATCH_SIZE", "2")
    monkeypatch.setattr(orchestration, "get_review_dimensions", lambda: dimensions)
    monkeypatch.setattr(orchestration, "_run_worker_async", fake_run_worker_async)
    monkeypatch.setattr(orchestration.asyncio, "sleep", fast_sleep)

    result = await langgraph_orchestration.langgraph_parallel_review(
        client=None,
        prd_content="prd",
        wiki_pages={},
        model_tiers={"sonnet": "test-model"},
        on_worker_done=lambda dim, payload: worker_done.append((dim, payload.get("status") or "success")),
        workspace="workspace",
    )

    assert worker_done == [("structure", "success"), ("quality", "timeout")]
    assert result["graph_trace"] == [
        "prepare_round:1",
        "worker:1:structure:success",
        "worker:1:quality:gateway_timeout",
        "finalize_round:1",
        "finalize_review",
    ]
    assert [worker["dimension"] for worker in result["workers"]] == ["structure", "quality"]
    assert result["workers"][1]["error_type"] == "gateway_timeout"
    assert result["resilience"]["recommended_batch_size"] == 1


@pytest.mark.asyncio
async def test_langgraph_parallel_review_supports_majority_vote_rounds(monkeypatch):
    import review.langgraph_orchestration as langgraph_orchestration
    import review.orchestration as orchestration

    round_calls = 0
    dimensions = {"structure": {"name": "业务完整性"}}

    async def fake_run_worker_async(*args, **_kwargs):
        nonlocal round_calls
        round_calls += 1
        dim_key = args[1]
        return {
            "dimension": dim_key,
            "dimension_name": dimensions[dim_key]["name"],
            "items": [
                {
                    "id": f"round-{round_calls}",
                    "dimension": "structure",
                    "location": "PRD",
                    "issue": "same issue",
                    "suggestion": f"round {round_calls}",
                    "severity": "must",
                    "rule_id": "V-01",
                }
            ],
            "usage": {"input_tokens": 1, "output_tokens": 2},
        }

    async def fast_sleep(_seconds: float):
        return None

    monkeypatch.setattr(orchestration, "get_review_dimensions", lambda: dimensions)
    monkeypatch.setattr(orchestration, "_run_worker_async", fake_run_worker_async)
    monkeypatch.setattr(langgraph_orchestration.asyncio, "sleep", fast_sleep)
    monkeypatch.setattr(orchestration.asyncio, "sleep", fast_sleep)

    result = await langgraph_orchestration.langgraph_parallel_review(
        client=None,
        prd_content="prd",
        wiki_pages={},
        model_tiers={"sonnet": "test-model"},
        voting_rounds=2,
        workspace="workspace",
    )

    assert round_calls == 2
    assert result["total_usage"] == {"input_tokens": 2, "output_tokens": 4}
    assert len(result["merged_items"]) == 1
    assert result["merged_items"][0]["id"] == "R-001"
    assert result["graph_trace"] == [
        "prepare_round:1",
        "worker:1:structure:success",
        "finalize_round:1",
        "prepare_round:2",
        "worker:2:structure:success",
        "finalize_round:2",
        "finalize_review",
    ]
