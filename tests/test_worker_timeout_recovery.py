from __future__ import annotations

import time


def test_run_worker_async_retries_timeout_with_recovery_budget(monkeypatch):
    import agent_config
    from review import worker as worker_mod

    monkeypatch.setattr(agent_config, "WORKER_TIMEOUT", 0.01)

    calls = []

    def fake_worker_core(*_args, **kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            time.sleep(0.05)
            return {
                "dimension": "structure",
                "items": [{"id": "late"}],
                "usage": {"input_tokens": 1, "output_tokens": 1},
            }
        return {
            "dimension": "structure",
            "items": [{"id": "recovered"}],
            "usage": {"input_tokens": 2, "output_tokens": 3},
            "model": "gpt-5.5",
            "telemetry": {"model": "gpt-5.5", "duration_ms": 5},
        }

    monkeypatch.setattr(worker_mod, "_worker_core", fake_worker_core)

    async def run():
        return await worker_mod._run_worker_async(
            None,
            "structure",
            "PRD" * 1000,
            {"wiki": "A" * 1000},
            {},
            wiki_path="C:/tmp/ws/wiki",
        )

    import asyncio

    result = asyncio.run(run())

    assert result["status"] == "recovered"
    assert result["items"] == [{"id": "recovered"}]
    assert result["recovery"]["attempts"] == 2
    assert result["recovery"]["first_error"].startswith("Worker")
    assert calls[0]["route_model_override"] is None
    assert calls[1]["route_model_override"] == "gpt55"
    assert calls[1]["recovery_mode"] is True
    assert calls[1]["wiki_budget_chars"] < calls[0]["wiki_budget_chars"]

