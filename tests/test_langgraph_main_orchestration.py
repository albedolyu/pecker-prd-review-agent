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
async def test_parallel_review_passes_langgraph_checkpoint_config(monkeypatch):
    import review.orchestration as orchestration

    checkpointer = object()
    captured = {}

    async def fake_langgraph_review(*_args, **kwargs):
        captured.update(kwargs)
        return {
            "workers": [],
            "merged_items": [],
            "total_usage": {"input_tokens": 0, "output_tokens": 0},
            "orchestrator": "langgraph",
        }

    monkeypatch.delenv("PECKER_REVIEW_ORCHESTRATOR", raising=False)
    monkeypatch.setattr(orchestration, "langgraph_parallel_review", fake_langgraph_review, raising=False)

    result = await orchestration.parallel_review(
        client=None,
        prd_content="prd",
        wiki_pages={},
        model_tiers={"sonnet": "test-model"},
        workspace="workspace",
        checkpointer=checkpointer,
        thread_id="review-job:rjob_123",
    )

    assert result["orchestrator"] == "langgraph"
    assert captured["checkpointer"] is checkpointer
    assert captured["thread_id"] == "review-job:rjob_123"


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


@pytest.mark.asyncio
async def test_langgraph_parallel_review_records_safe_langfuse_node_spans(monkeypatch):
    import json

    import review.langgraph_orchestration as langgraph_orchestration
    import review.orchestration as orchestration

    calls: list[dict] = []
    dimensions = {"structure": {"name": "业务完整性"}}

    class FakeObservation:
        def __init__(self, call):
            self.call = call

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def update(self, **kwargs):
            self.call.setdefault("updates", []).append(kwargs)

    class FakeLangfuse:
        def start_as_current_observation(self, **kwargs):
            calls.append(kwargs)
            return FakeObservation(calls[-1])

        def flush(self):
            calls.append({"flush": True})

    async def fake_run_worker_async(*args, **_kwargs):
        dim_key = args[1]
        return {
            "dimension": dim_key,
            "dimension_name": dimensions[dim_key]["name"],
            "items": [
                {
                    "id": "R-1",
                    "dimension": dim_key,
                    "location": "PRD",
                    "problem": "must not leak finding body",
                    "suggestion": "must not leak suggestion",
                    "severity": "must",
                }
            ],
            "usage": {"input_tokens": 7, "output_tokens": 11},
        }

    prd_body = "# PRD\n" + ("secret PRD body token=secret-token " * 10)

    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test-secret")
    monkeypatch.setenv("PECKER_LANGFUSE_ENABLED", "1")
    monkeypatch.setattr(orchestration, "get_review_dimensions", lambda: dimensions)
    monkeypatch.setattr(orchestration, "_run_worker_async", fake_run_worker_async)

    result = await langgraph_orchestration.langgraph_parallel_review(
        client=None,
        prd_content=prd_body,
        wiki_pages={"prd.md": "wiki page cookie=secret-cookie"},
        model_tiers={"sonnet": "test-model"},
        workspace="workspace",
        thread_id="review-job:rjob_langfuse",
        langfuse_client_factory=lambda: FakeLangfuse(),
    )

    names = [call["name"] for call in calls if "name" in call]
    assert names == [
        "pecker.langgraph.review",
        "pecker.langgraph.prepare_round",
        "pecker.langgraph.worker.structure",
        "pecker.langgraph.finalize_round",
        "pecker.langgraph.finalize_review",
    ]
    worker_call = next(
        call for call in calls if call.get("name") == "pecker.langgraph.worker.structure"
    )
    assert worker_call["as_type"] == "generation"
    assert worker_call["updates"][0]["usage_details"] == {"input": 7, "output": 11}
    serialized = json.dumps(calls, ensure_ascii=False)
    assert "secret PRD body" not in serialized
    assert "secret-token" not in serialized
    assert "secret-cookie" not in serialized
    assert "must not leak finding body" not in serialized
    assert "must not leak suggestion" not in serialized
    assert calls[-1] == {"flush": True}
    assert result["observability"]["langfuse"]["status"] == "done"
    assert result["observability"]["langfuse"]["configured"] is True
    assert result["observability"]["langfuse"]["session_id"] == "review-job:rjob_langfuse"
