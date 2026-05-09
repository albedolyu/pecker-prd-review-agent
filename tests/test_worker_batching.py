from __future__ import annotations

import asyncio

import pytest


@pytest.mark.asyncio
async def test_single_round_runs_workers_in_configured_batches(monkeypatch, tmp_path):
    import review.orchestration as orchestration

    dimensions = {
        "structure": {"name": "Structure"},
        "quality": {"name": "Quality"},
        "ai_coding": {"name": "AI Coding"},
        "data_quality": {"name": "Data Quality"},
    }
    monkeypatch.setenv("PECKER_WORKER_BATCH_SIZE", "2")
    monkeypatch.setattr(orchestration, "get_review_dimensions", lambda: dimensions)

    real_sleep = asyncio.sleep

    async def fast_sleep(_seconds: float):
        await real_sleep(0)

    monkeypatch.setattr(orchestration.asyncio, "sleep", fast_sleep)

    active_workers = 0
    max_active_workers = 0
    started: list[str] = []
    completed: list[str] = []
    third_start_completed_count: int | None = None

    async def fake_run_worker_async(*args, **kwargs):
        nonlocal active_workers, max_active_workers, third_start_completed_count

        dim_key = args[1]
        if len(started) == 2:
            third_start_completed_count = len(completed)
        started.append(dim_key)
        active_workers += 1
        max_active_workers = max(max_active_workers, active_workers)

        await real_sleep(0.02)

        active_workers -= 1
        completed.append(dim_key)
        return {
            "dimension": dim_key,
            "dimension_name": dimensions[dim_key]["name"],
            "items": [
                {
                    "id": f"{dim_key}-1",
                    "dimension": dim_key,
                    "location": "PRD",
                    "issue": f"{dim_key} issue",
                    "suggestion": "Fix it",
                    "severity": "should",
                }
            ],
            "usage": {"input_tokens": 1, "output_tokens": 1},
        }

    monkeypatch.setattr(orchestration, "_run_worker_async", fake_run_worker_async)

    workers, _merged_items, total_input, total_output = await orchestration._single_round_async(
        client=None,
        prd_content="prd",
        wiki_pages={},
        model_tiers={"sonnet": "test-model"},
        workspace=str(tmp_path),
    )

    assert [worker["dimension"] for worker in workers] == list(dimensions)
    assert total_input == 4
    assert total_output == 4
    assert max_active_workers == 2
    assert third_start_completed_count == 2


@pytest.mark.asyncio
async def test_single_round_keeps_partial_result_when_some_workers_succeed(monkeypatch, tmp_path):
    import review.orchestration as orchestration

    dimensions = {
        "structure": {"name": "Structure"},
        "quality": {"name": "Quality"},
        "ai_coding": {"name": "AI Coding"},
        "data_quality": {"name": "Data Quality"},
    }
    monkeypatch.setenv("PECKER_WORKER_BATCH_SIZE", "4")
    monkeypatch.setattr(orchestration, "get_review_dimensions", lambda: dimensions)

    async def fake_run_worker_async(*args, **kwargs):
        dim_key = args[1]
        if dim_key != "ai_coding":
            raise RuntimeError("Cloudflare 524: a timeout occurred")
        return {
            "dimension": dim_key,
            "dimension_name": dimensions[dim_key]["name"],
            "items": [
                {
                    "id": f"{dim_key}-1",
                    "dimension": dim_key,
                    "location": "PRD",
                    "issue": "AI coding issue",
                    "suggestion": "Fix it",
                    "severity": "must",
                }
            ],
            "usage": {"input_tokens": 2, "output_tokens": 3},
        }

    monkeypatch.setattr(orchestration, "_run_worker_async", fake_run_worker_async)

    workers, merged_items, total_input, total_output = await orchestration._single_round_async(
        client=None,
        prd_content="prd",
        wiki_pages={},
        model_tiers={"sonnet": "test-model"},
        workspace=str(tmp_path),
    )

    assert len(workers) == 4
    assert sum(1 for worker in workers if worker.get("error")) == 3
    assert [item["dimension"] for item in merged_items] == ["ai_coding"]
    assert merged_items[0]["issue"] == "AI coding issue"
    assert total_input == 2
    assert total_output == 3


@pytest.mark.asyncio
async def test_single_round_preserves_completed_batches_when_total_timeout_hits(monkeypatch, tmp_path):
    import agent_config
    import review.orchestration as orchestration

    dimensions = {
        "structure": {"name": "Structure"},
        "quality": {"name": "Quality"},
        "ai_coding": {"name": "AI Coding"},
        "data_quality": {"name": "Data Quality"},
    }
    monkeypatch.setenv("PECKER_WORKER_BATCH_SIZE", "2")
    monkeypatch.setattr(agent_config, "TOTAL_REVIEW_TIMEOUT", 0.36)
    monkeypatch.setattr(orchestration, "get_review_dimensions", lambda: dimensions)

    async def fake_run_worker_async(*args, **kwargs):
        dim_key = args[1]
        if dim_key in {"structure", "quality"}:
            await asyncio.sleep(0.01)
            return {
                "dimension": dim_key,
                "dimension_name": dimensions[dim_key]["name"],
                "items": [
                    {
                        "id": f"{dim_key}-1",
                        "dimension": dim_key,
                        "location": "PRD",
                        "issue": f"{dim_key} issue",
                        "suggestion": "Fix it",
                        "severity": "should",
                    }
                ],
                "usage": {"input_tokens": 1, "output_tokens": 1},
            }
        await asyncio.sleep(10)
        return {
            "dimension": dim_key,
            "dimension_name": dimensions[dim_key]["name"],
            "items": [],
            "usage": {"input_tokens": 0, "output_tokens": 0},
        }

    monkeypatch.setattr(orchestration, "_run_worker_async", fake_run_worker_async)

    workers, merged_items, total_input, total_output = await orchestration._single_round_async(
        client=None,
        prd_content="prd",
        wiki_pages={},
        model_tiers={"sonnet": "test-model"},
        workspace=str(tmp_path),
    )

    assert [worker["dimension"] for worker in workers] == list(dimensions)
    assert [worker.get("status") for worker in workers[:2]] == ["success", "success"]
    assert all(worker.get("status") == "timeout" for worker in workers[2:])
    assert [item["dimension"] for item in merged_items] == ["structure", "quality"]
    assert total_input == 2
    assert total_output == 2
