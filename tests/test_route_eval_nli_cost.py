"""route_eval NLI cost accounting regressions."""
from __future__ import annotations


def test_nli_fast_path_does_not_create_negative_usage(monkeypatch):
    from eval.route_eval import runner
    import review.evidence_verify as evidence_verify

    def fake_score(**_kwargs):
        return {
            "entail_score": 0.0,
            "contradict_score": 1.0,
            "neutral_score": 0.0,
            "max_signal": 1.0,
            "n_samples_succeeded": -1,
        }

    monkeypatch.setattr(evidence_verify, "_llm_nli_score", fake_score)

    resp, error_type, fallback = runner._call_nli_pattern(
        "haiku",
        [
            {
                "id": "HAL-FAKE-001",
                "item": {"issue": "fake"},
                "wiki_pages": {},
                "is_hallucination": True,
            }
        ],
        max_cases=2,
    )

    assert error_type is None
    assert fallback is False
    assert resp.usage["input_tokens"] == 0
    assert resp.usage["output_tokens"] == 0
    assert resp.items[0]["scores"]["n_samples_succeeded"] == -1


def test_cost_latency_clamps_negative_accounting_records():
    from eval.route_eval.metrics import compute_cost_latency

    metrics = compute_cost_latency([
        {
            "latency_ms": 100,
            "input_tokens": -4000,
            "output_tokens": -800,
            "cost_usd": -0.024,
        }
    ])

    assert metrics["cost_usd_total"] == 0.0
    assert metrics["cost_usd_per_run"] == 0.0
    assert metrics["total_input_tokens"] == 0
    assert metrics["total_output_tokens"] == 0
