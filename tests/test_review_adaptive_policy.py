from __future__ import annotations


def test_large_prd_promotes_worker_to_gpt55():
    from review.adaptive import choose_worker_model_override

    override = choose_worker_model_override(
        "compliance",
        prd_content="x" * 35_000,
        wiki_pages={f"p{i}": "wiki" for i in range(60)},
    )

    assert override == "gpt55"


def test_recovery_budget_is_smaller_than_normal_budget():
    from review.adaptive import wiki_budget_for_dim

    normal = wiki_budget_for_dim(
        "quality",
        60_000,
        prd_content="x" * 35_000,
        wiki_pages={f"p{i}": "wiki" for i in range(60)},
    )
    recovery = wiki_budget_for_dim(
        "quality",
        60_000,
        prd_content="x" * 35_000,
        wiki_pages={f"p{i}": "wiki" for i in range(60)},
        recovery_mode=True,
    )

    assert normal == 30_000
    assert recovery == 24_000


def test_large_prd_reduces_heavy_worker_wiki_budget():
    from review.adaptive import wiki_budget_for_dim

    budget = wiki_budget_for_dim(
        "ai_coding",
        60_000,
        prd_content="x" * 35_000,
        wiki_pages={f"p{i}": "wiki" for i in range(60)},
    )

    assert budget == 45_000


def test_ai_coding_budget_is_capped_for_medium_wiki_cases():
    from review.adaptive import wiki_budget_for_dim

    budget = wiki_budget_for_dim(
        "ai_coding",
        60_000,
        prd_content="x" * 17_000,
        wiki_pages={f"p{i}": "wiki" for i in range(49)},
    )

    assert budget == 45_000


def test_small_prd_uses_compact_wiki_budget_even_with_many_wiki_pages():
    from review.adaptive import wiki_budget_for_dim

    budget = wiki_budget_for_dim(
        "data_quality",
        60_000,
        prd_content="x" * 5_000,
        wiki_pages={f"p{i}": "wiki" for i in range(60)},
    )

    assert budget == 19_800


def test_medium_prd_keeps_deep_review_budget():
    from review.adaptive import wiki_budget_for_dim

    ai_budget = wiki_budget_for_dim(
        "ai_coding",
        60_000,
        prd_content="x" * 10_000,
        wiki_pages={f"p{i}": "wiki" for i in range(60)},
    )
    structure_budget = wiki_budget_for_dim(
        "structure",
        60_000,
        prd_content="x" * 10_000,
        wiki_pages={f"p{i}": "wiki" for i in range(60)},
    )

    assert ai_budget == 45_000
    assert structure_budget == 27_000


def test_light_review_mode_caps_wiki_budget_base(monkeypatch):
    from review.adaptive import wiki_budget_for_dim

    monkeypatch.setenv("PECKER_REVIEW_MODE", "light")

    budget = wiki_budget_for_dim(
        "ai_coding",
        60_000,
        prd_content="x" * 20_000,
        wiki_pages={f"p{i}": "wiki" for i in range(60)},
    )

    assert budget == 27_000
