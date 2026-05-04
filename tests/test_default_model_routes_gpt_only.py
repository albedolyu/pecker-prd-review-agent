from __future__ import annotations


ACTIVE_ROUTE_IDS = [
    "worker.default",
    "worker.structure",
    "worker.compliance",
    "worker.data_quality",
    "worker.quality",
    "worker.consistency",
    "worker.ai_coding",
    "advisor.goshawk",
    "advisor.goshawk.recheck",
    "verify.nli",
    "eval.cuckoo",
]


def _load_default_config(monkeypatch):
    monkeypatch.delenv("PECKER_ROUTES_FILE", raising=False)
    monkeypatch.delenv("PECKER_MODEL_OVERRIDE", raising=False)

    import model_router
    from clients import factory

    model_router.reset_config_cache()
    factory.reset_clients()
    return model_router.get_route_config(force_reload=True)


def test_default_routes_use_gpt_only_active_routes(monkeypatch):
    cfg = _load_default_config(monkeypatch)

    for route_id in ACTIVE_ROUTE_IDS:
        route = cfg.resolve(route_id)
        assert route["enabled"] is True
        assert route["vendor"] == "openai", route_id
        assert route["transport"] == "cli", route_id
        assert route["model"].startswith("gpt-"), route_id


def test_default_routes_keep_smooth_gpt_tier_split(monkeypatch):
    cfg = _load_default_config(monkeypatch)

    expected_tiers = {
        "worker.default": "gpt54",
        "worker.structure": "gpt55",
        "worker.compliance": "gpt54",
        "worker.quality": "gpt55",
        "worker.data_quality": "gpt55",
        "worker.consistency": "gpt55",
        "worker.ai_coding": "gpt55",
        "advisor.goshawk": "gpt55",
        "advisor.goshawk.recheck": "gpt54",
        "verify.nli": "gpt54mini",
        "eval.cuckoo": "gpt54",
    }

    for route_id, tier in expected_tiers.items():
        route = cfg.resolve(route_id)
        assert route["tier"] == tier, route_id


def test_gpt_route_tier_aliases_have_cost_placeholders():
    from clients.token_tracker import compute_call_cost_usd

    usage = {"input_tokens": 100, "output_tokens": 50}
    assert compute_call_cost_usd("gpt55", usage) == 0.0
    assert compute_call_cost_usd("gpt54", usage) == 0.0
    assert compute_call_cost_usd("gpt54mini", usage) == 0.0


def test_default_routes_cover_actual_review_dimensions(monkeypatch):
    cfg = _load_default_config(monkeypatch)

    from review.dimensions import get_review_dimensions

    for dim_key in get_review_dimensions():
        route_id = f"worker.{dim_key}"
        route = cfg.resolve(route_id)
        assert route["route_id"] == route_id


def test_worker_context_uses_route_default_not_legacy_dimension_tier(monkeypatch):
    calls = []

    def fake_get_model_for_route(route_id, *, model_override=None):
        calls.append((route_id, model_override))
        return "gpt-5.5"

    monkeypatch.setattr("model_router.get_model_for_route", fake_get_model_for_route)

    from review.worker import _prepare_worker_context

    ctx = _prepare_worker_context(
        dim_key="ai_coding",
        model_tiers={"opus": "legacy-opus"},
        rule_perf_history=None,
        wiki_path=None,
        wiki_pages={},
        prd_content="PRD",
    )

    assert ctx["model"] == "gpt-5.5"
    assert calls == [("worker.ai_coding", None)]
