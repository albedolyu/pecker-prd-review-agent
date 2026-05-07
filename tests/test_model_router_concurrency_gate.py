from __future__ import annotations

import threading
import time
from types import SimpleNamespace


def test_route_call_limits_concurrent_model_calls(monkeypatch):
    import model_router
    from clients import factory

    monkeypatch.setenv("PECKER_MAX_CONCURRENT_MODEL_CALLS", "2")
    model_router.reset_model_call_limiter()
    model_router.reset_config_cache()
    factory.reset_clients()

    active = 0
    peak = 0
    lock = threading.Lock()

    class FakeClient:
        def create(self, **_kwargs):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            time.sleep(0.05)
            with lock:
                active -= 1
            return SimpleNamespace(model="gpt-5.5")

    monkeypatch.setattr(factory, "get_client", lambda *_args, **_kwargs: FakeClient())

    threads = [
        threading.Thread(
            target=lambda: model_router.route_call(
                "worker.structure",
                system="system",
                messages=[{"role": "user", "content": "PRD"}],
            )
        )
        for _ in range(5)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=2)

    assert peak <= 2

