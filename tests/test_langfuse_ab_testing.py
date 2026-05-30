import json


def test_goshawk_ab_comparison_builds_safe_metadata_and_scores():
    from review.langfuse_ab_testing import (
        build_goshawk_ab_score_payloads,
        compare_goshawk_ab_runs,
    )

    full = {
        "variant": "full",
        "elapsed_s": 20.0,
        "usage": {"input_tokens": 1000, "output_tokens": 120},
        "items": [
            {"id": "R-001", "rule_id": "V-05", "location": "sec 1", "issue": "same"},
            {"id": "R-002", "rule_id": "RC-004", "location": "sec 2", "issue": "only full"},
        ],
        "goshawk_result": {
            "flagged_as_false_positive": [{"item_id": "R-002"}],
            "additional_findings": [],
            "conflict_resolutions": [],
        },
    }
    compact = {
        "variant": "compact",
        "elapsed_s": 15.0,
        "usage": {"input_tokens": 600, "output_tokens": 110},
        "items": [
            {"id": "R-001", "rule_id": "V-05", "location": "sec 1", "issue": "same"},
            {"id": "R-003", "rule_id": "RC-008", "location": "sec 3", "issue": "only compact"},
        ],
        "goshawk_result": {
            "flagged_as_false_positive": [],
            "additional_findings": [{"rule_id": "RC-008"}],
            "conflict_resolutions": [],
        },
        "compaction": {
            "enabled": True,
            "budget_chars": 25000,
            "selected_count": 12,
            "worker_union_count": 5,
            "secret": "sk-should-not-leak",
        },
    }

    summary = compare_goshawk_ab_runs(
        batch_id="goshawk-ab-1",
        case_id="company-logo-upload",
        baseline=full,
        candidate=compact,
        source_items_count=2,
    )
    scores = build_goshawk_ab_score_payloads(
        summary,
        trace_id="abc123abc123abc123abc123abc123ab",
    )

    assert summary["metadata"]["ab_kind"] == "goshawk_final_only"
    assert summary["candidate"]["variant"] == "compact"
    assert summary["metrics"]["input_token_savings_ratio"] == 0.4
    assert summary["metrics"]["elapsed_savings_ratio"] == 0.25
    assert summary["metrics"]["final_rule_jaccard"] == 1 / 3
    assert summary["metrics"]["final_signature_jaccard"] == 1 / 3
    assert summary["candidate"]["compaction"] == {
        "enabled": True,
        "budget_chars": 25000,
        "selected_count": 12,
        "worker_union_count": 5,
    }

    names = {score["name"] for score in scores}
    assert "pecker.goshawk_ab.final_rule_jaccard" in names
    assert "pecker.goshawk_ab.final_signature_jaccard" in names
    assert "pecker.goshawk_ab.input_token_savings_ratio" in names
    assert "pecker.goshawk_ab.compact_pass" in names
    assert all(score["trace_id"] == "abc123abc123abc123abc123abc123ab" for score in scores)
    assert all(score["data_type"] == "NUMERIC" for score in scores)

    serialized = json.dumps(scores, ensure_ascii=False)
    assert "only full" not in serialized
    assert "only compact" not in serialized
    assert "sk-should-not-leak" not in serialized

