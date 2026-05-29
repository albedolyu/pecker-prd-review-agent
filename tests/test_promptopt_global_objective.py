from __future__ import annotations


def _result(items, *, input_tokens=1000, output_tokens=100, elapsed_s=10.0, false_positive=0):
    return {
        "items": items,
        "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
        "elapsed_s": elapsed_s,
        "false_positive": false_positive,
        "final_items": len(items),
    }


def test_promptopt_global_objective_passes_stable_multi_case_candidate():
    from eval.promptopt_global_objective import score_promptopt_suite

    cases = [
        {
            "case_id": "risk-alert",
            "baseline": _result(
                [
                    {"id": "A", "rule_id": "R1", "location": "2.1", "issue": "missing field"},
                    {"id": "B", "rule_id": "R2", "location": "3.1", "issue": "unclear state"},
                ],
                input_tokens=1000,
                elapsed_s=10.0,
            ),
            "candidate": _result(
                [
                    {"id": "A2", "rule_id": "R1", "location": "2.1", "issue": "missing field"},
                    {"id": "B2", "rule_id": "R2", "location": "3.1", "issue": "unclear state"},
                ],
                input_tokens=820,
                elapsed_s=8.5,
            ),
        },
        {
            "case_id": "complaint-email",
            "baseline": _result(
                [{"rule_id": "R3", "location": "4", "issue": "copy lacks boundary"}],
                input_tokens=900,
                elapsed_s=9.0,
            ),
            "candidate": _result(
                [{"rule_id": "R3", "location": "4", "issue": "copy lacks boundary"}],
                input_tokens=760,
                elapsed_s=7.0,
            ),
        },
        {
            "case_id": "backend-contract",
            "baseline": _result(
                [
                    {"rule_id": "R4", "location": "api", "issue": "request schema missing"},
                    {"rule_id": "R5", "location": "api", "issue": "error code missing"},
                    {"rule_id": "R6", "location": "data", "issue": "ddl mismatch"},
                ],
                input_tokens=1200,
                elapsed_s=12.0,
            ),
            "candidate": _result(
                [
                    {"rule_id": "R4", "location": "api", "issue": "request schema missing"},
                    {"rule_id": "R5", "location": "api", "issue": "error code missing"},
                    {"rule_id": "R6", "location": "data", "issue": "ddl mismatch"},
                ],
                input_tokens=1000,
                elapsed_s=10.0,
                false_positive=1,
            ),
        },
    ]

    result = score_promptopt_suite(cases, prompt_variant="compact-v2", batch_id="batch-1")

    assert result["pass"] is True
    assert result["global_score"] >= 0.80
    assert result["summary"]["case_count"] == 3
    assert result["summary"]["mean_signature_jaccard"] == 1.0
    assert result["summary"]["mean_input_token_savings_ratio"] > 0.15
    assert result["fail_reasons"] == []


def test_promptopt_global_objective_fails_single_case_overfit():
    from eval.promptopt_global_objective import score_promptopt_suite

    cases = [
        {
            "case_id": "good-a",
            "baseline": _result([{"rule_id": "R1", "location": "1", "issue": "same"}]),
            "candidate": _result([{"rule_id": "R1", "location": "1", "issue": "same"}], input_tokens=800),
        },
        {
            "case_id": "good-b",
            "baseline": _result([{"rule_id": "R2", "location": "2", "issue": "same"}]),
            "candidate": _result([{"rule_id": "R2", "location": "2", "issue": "same"}], input_tokens=800),
        },
        {
            "case_id": "collapsed",
            "baseline": _result(
                [
                    {"rule_id": "R3", "location": "3.1", "issue": "schema missing"},
                    {"rule_id": "R4", "location": "3.2", "issue": "state missing"},
                    {"rule_id": "R5", "location": "3.3", "issue": "risk missing"},
                ]
            ),
            "candidate": _result(
                [{"rule_id": "R9", "location": "9", "issue": "unrelated"}],
                input_tokens=700,
                false_positive=2,
            ),
        },
    ]

    result = score_promptopt_suite(cases, prompt_variant="overfit", batch_id="batch-2")

    assert result["pass"] is False
    assert result["summary"]["min_signature_jaccard"] == 0.0
    assert any("collapsed" in reason for reason in result["fail_reasons"])
    assert any("signature_jaccard" in reason for reason in result["fail_reasons"])
    assert any("false_positive_rate" in reason for reason in result["fail_reasons"])


def test_promptopt_global_objective_builds_langfuse_scores():
    from eval.promptopt_global_objective import (
        build_langfuse_score_payloads,
        score_promptopt_suite,
    )

    result = score_promptopt_suite(
        [
            {
                "case_id": "a",
                "baseline": _result([{"rule_id": "R1", "location": "1", "issue": "same"}]),
                "candidate": _result([{"rule_id": "R1", "location": "1", "issue": "same"}]),
            },
            {
                "case_id": "b",
                "baseline": _result([{"rule_id": "R2", "location": "2", "issue": "same"}]),
                "candidate": _result([{"rule_id": "R2", "location": "2", "issue": "same"}]),
            },
            {
                "case_id": "c",
                "baseline": _result([{"rule_id": "R3", "location": "3", "issue": "same"}]),
                "candidate": _result([{"rule_id": "R3", "location": "3", "issue": "same"}]),
            },
        ],
        prompt_variant="compact-v2",
        batch_id="batch-3",
    )

    scores = build_langfuse_score_payloads(
        result,
        trace_id="abc123abc123abc123abc123abc123ab",
    )

    names = [score["name"] for score in scores]
    assert "pecker.promptopt.global_score" in names
    assert "pecker.promptopt.global.mean_signature_jaccard" in names
    assert names.count("pecker.promptopt.case.signature_jaccard") == 3
    assert all(score["trace_id"] == "abc123abc123abc123abc123abc123ab" for score in scores)
    case_score = next(score for score in scores if score["name"] == "pecker.promptopt.case.signature_jaccard")
    assert case_score["metadata"]["batch_id"] == "batch-3"
    assert case_score["metadata"]["prompt_variant"] == "compact-v2"
    assert case_score["metadata"]["case_id"] in {"a", "b", "c"}


def test_promptopt_global_objective_reports_scenario_slices():
    from eval.promptopt_global_objective import (
        build_langfuse_score_payloads,
        score_promptopt_suite,
    )

    result = score_promptopt_suite(
        [
            {
                "case_id": "risk-a",
                "scenario": "risk",
                "baseline": _result([{"rule_id": "R1", "location": "1", "issue": "same"}]),
                "candidate": _result([{"rule_id": "R1", "location": "1", "issue": "same"}]),
            },
            {
                "case_id": "risk-b",
                "scenario": "risk",
                "baseline": _result([{"rule_id": "R2", "location": "2", "issue": "same"}]),
                "candidate": _result([{"rule_id": "R2", "location": "2", "issue": "same"}]),
            },
            {
                "case_id": "crm-a",
                "scenario": "crm",
                "baseline": _result([{"rule_id": "R3", "location": "3", "issue": "same"}]),
                "candidate": _result([{"rule_id": "R3", "location": "3", "issue": "same"}]),
            },
        ],
        prompt_variant="compact-v2",
        batch_id="batch-4",
    )

    assert result["summary"]["scenario_count"] == 2
    assert result["summary"]["by_scenario"]["risk"]["case_count"] == 2
    assert result["summary"]["by_scenario"]["crm"]["mean_signature_jaccard"] == 1.0

    scores = build_langfuse_score_payloads(result)
    scenario_scores = [
        score for score in scores if score["name"] == "pecker.promptopt.scenario.mean_signature_jaccard"
    ]
    assert {score["metadata"]["scenario"] for score in scenario_scores} == {"risk", "crm"}
