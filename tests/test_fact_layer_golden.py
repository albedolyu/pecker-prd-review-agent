from __future__ import annotations

import json
from pathlib import Path


def test_fact_layer_golden_builds_active_cases_from_human_labelled_sources():
    from eval.fact_layer_golden import build_fact_layer_golden

    payload = build_fact_layer_golden()

    assert payload["active_case_count"] >= 10
    active = [case for case in payload["cases"] if case["activation"] == "active"]
    assert any(case["source"]["source_id"] == "BUG-001" for case in active)
    assert all(case["family"] == "fact_layer_lookup" for case in active)
    assert all(case["expect"]["include_fact_layer"] is True for case in active)
    assert all(case["expected_sources"][0]["path_contains"] for case in active)


def test_fact_layer_golden_keeps_inline_minimal_cases_as_candidates():
    from eval.fact_layer_golden import build_fact_layer_golden

    payload = build_fact_layer_golden()
    candidates = [case for case in payload["cases"] if case["activation"] == "candidate"]

    assert payload["candidate_case_count"] == len(candidates)
    assert candidates
    assert all(case["source"]["authority"] == "seed_needs_pm_review" for case in candidates)
    assert all("待 PM 后续标注" in case["source"]["activation_reason"] for case in candidates)


def test_fact_layer_golden_uses_only_pm_decisions_with_answer_notes():
    from eval.fact_layer_golden import build_fact_layer_golden

    payload = build_fact_layer_golden()
    pm_cases = [
        case
        for case in payload["cases"]
        if case["source"]["kind"] == "pm_decision_ground_truth"
    ]

    assert pm_cases
    assert all(case["source"]["authority"] == "pm_confirmed_true_positive" for case in pm_cases)
    assert all(case["standard_answer"]["issue"] for case in pm_cases)
    assert not any(case["source"]["path"].endswith("sample_claude-test_1776822462.json") for case in pm_cases)


def test_fact_layer_golden_cli_writes_json(tmp_path):
    from eval.fact_layer_golden import write_fact_layer_golden

    output = tmp_path / "fact_layer.json"
    payload = write_fact_layer_golden(output)
    written = json.loads(output.read_text(encoding="utf-8"))

    assert written["active_case_count"] == payload["active_case_count"]
    assert written["candidate_case_count"] == payload["candidate_case_count"]
    assert written["cases"][0]["id"].startswith("FLGT-")


def test_checked_in_fact_layer_golden_matches_generator_counts():
    from eval.fact_layer_golden import build_fact_layer_golden

    project_root = Path(__file__).resolve().parents[1]
    checked_in = json.loads(
        (project_root / "eval" / "golden" / "fact_layer_ground_truth_samples.json").read_text(
            encoding="utf-8"
        )
    )
    generated = build_fact_layer_golden()

    assert checked_in["version"] == generated["version"]
    assert checked_in["active_case_count"] == generated["active_case_count"]
    assert checked_in["candidate_case_count"] == generated["candidate_case_count"]
    assert len(checked_in["cases"]) == len(generated["cases"])
