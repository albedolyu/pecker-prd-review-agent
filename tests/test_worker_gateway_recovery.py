from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_run_dimension_worker_retries_gateway_error_in_recovery_mode(monkeypatch):
    import review.orchestration as orchestration

    calls: list[bool] = []

    async def fast_sleep(_seconds: float):
        return None

    async def fake_run_worker_async(*args, **kwargs):
        recovery_mode = bool(kwargs.get("recovery_mode"))
        calls.append(recovery_mode)
        dim_key = args[1]
        if not recovery_mode:
            raise RuntimeError("Cloudflare 524: a timeout occurred")
        return {
            "dimension": dim_key,
            "dimension_name": "业务完整性",
            "items": [{"id": "R-1", "dimension": dim_key}],
            "usage": {"input_tokens": 1, "output_tokens": 2},
        }

    monkeypatch.setenv("PECKER_ENABLE_WORKER_GATEWAY_RECOVERY", "1")
    monkeypatch.setattr(orchestration.asyncio, "sleep", fast_sleep)
    monkeypatch.setattr(orchestration, "_run_worker_async", fake_run_worker_async)

    result = await orchestration._run_dimension_worker_async(
        client=None,
        dim_key="structure",
        prd_content="prd",
        wiki_pages={},
        model_tiers={"sonnet": "test-model"},
        rule_perf_history=None,
        dimensions={"structure": {"name": "业务完整性"}},
    )

    assert calls == [False, True]
    assert result["status"] == "recovered"
    assert result["recovery"]["first_error_type"] == "gateway_timeout"
    assert result["items"] == [{"id": "R-1", "dimension": "structure"}]
