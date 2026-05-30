import json
import types


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
    assert summary["metrics"]["advisor_fp_jaccard"] == 0.0
    assert summary["metrics"]["false_positive_delta"] == -1
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
    assert "pecker.goshawk_ab.advisor_fp_jaccard" in names
    assert "pecker.goshawk_ab.false_positive_delta" in names
    assert "pecker.goshawk_ab.compact_pass" in names
    assert all(score["trace_id"] == "abc123abc123abc123abc123abc123ab" for score in scores)
    assert all(score["data_type"] == "NUMERIC" for score in scores)

    serialized = json.dumps(scores, ensure_ascii=False)
    assert "only full" not in serialized
    assert "only compact" not in serialized
    assert "sk-should-not-leak" not in serialized


def test_goshawk_ab_scores_prefer_trace_target_over_session_target():
    from review.langfuse_ab_testing import build_goshawk_ab_score_payloads

    summary = {
        "metadata": {"batch_id": "batch-1", "ab_kind": "goshawk_final_only"},
        "baseline": {"variant": "full", "elapsed_s": 2, "usage": {}, "items_count": 1},
        "candidate": {"variant": "compact", "elapsed_s": 1, "usage": {}, "items_count": 1},
        "metrics": {"compact_pass": True},
    }

    scores = build_goshawk_ab_score_payloads(
        summary,
        trace_id="abc123abc123abc123abc123abc123ab",
        session_id="batch-1",
    )

    assert scores
    assert all(score.get("trace_id") == "abc123abc123abc123abc123abc123ab" for score in scores)
    assert all("session_id" not in score for score in scores)


def test_goshawk_ab_suite_summary_keeps_compaction_disabled_when_any_run_fails():
    from review.langfuse_ab_testing import summarize_goshawk_ab_suite

    reports = [
        {
            "batch_id": "pass-1",
            "ab": {
                "metrics": {
                    "compact_pass": True,
                    "input_token_savings_ratio": 0.44,
                    "elapsed_savings_ratio": 0.1,
                    "final_rule_jaccard": 1.0,
                    "final_signature_jaccard": 0.93,
                    "false_positive_delta": -1,
                }
            },
        },
        {
            "batch_id": "fail-1",
            "ab": {
                "metrics": {
                    "compact_pass": False,
                    "input_token_savings_ratio": 0.44,
                    "elapsed_savings_ratio": -0.06,
                    "final_rule_jaccard": 0.86,
                    "final_signature_jaccard": 0.89,
                    "false_positive_delta": 1,
                }
            },
        },
    ]

    result = summarize_goshawk_ab_suite(reports, min_runs_for_canary=2)

    assert result["summary"]["run_count"] == 2
    assert result["summary"]["compact_pass_count"] == 1
    assert result["summary"]["compact_pass_rate"] == 0.5
    assert result["summary"]["median_input_token_savings_ratio"] == 0.44
    assert result["summary"]["min_final_signature_jaccard"] == 0.89
    assert result["summary"]["max_false_positive_delta"] == 1
    assert result["recommendation"]["action"] == "keep_disabled"
    assert result["failures"][0]["batch_id"] == "fail-1"
    assert "signature_below_threshold" in result["failures"][0]["reasons"]
    assert "false_positive_delta_positive" in result["failures"][0]["reasons"]


def test_goshawk_ab_suite_builds_langfuse_scores():
    from review.langfuse_ab_testing import build_goshawk_ab_suite_score_payloads

    suite = {
        "summary": {
            "run_count": 4,
            "compact_pass_rate": 0.75,
            "median_input_token_savings_ratio": 0.441,
            "median_elapsed_savings_ratio": -0.041,
            "min_final_rule_jaccard": 0.857,
            "min_final_signature_jaccard": 0.895,
            "max_false_positive_delta": 0,
        },
        "recommendation": {"action": "keep_disabled", "reason": "quality_gate_failed"},
        "failures": [{"batch_id": "fail-1", "reasons": ["signature_below_threshold"]}],
    }

    scores = build_goshawk_ab_suite_score_payloads(
        suite,
        session_id="goshawk-ab-suite-procli",
    )

    names = {score["name"] for score in scores}
    assert "pecker.goshawk_ab_suite.compact_pass_rate" in names
    assert "pecker.goshawk_ab_suite.keep_disabled" in names
    assert "pecker.goshawk_ab_suite.min_final_signature_jaccard" in names
    assert all(score["session_id"] == "goshawk-ab-suite-procli" for score in scores)
    assert all(score["data_type"] == "NUMERIC" for score in scores)
    assert scores[0]["metadata"]["recommendation_action"] == "keep_disabled"
    assert scores[0]["metadata"]["failure_count"] == 1


def test_goshawk_ab_suite_recording_creates_trace_for_queryable_scores(monkeypatch):
    import review.langfuse_observability as observability
    from review.langfuse_ab_testing import record_goshawk_ab_suite_scores

    calls = []

    class FakePropagationContext:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class FakeLangfuseModule:
        @staticmethod
        def propagate_attributes(**kwargs):
            calls.append({"propagate": kwargs})
            return FakePropagationContext()

    class FakeObservation:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def update(self, **kwargs):
            calls.append({"update": kwargs})

    class FakeIngestion:
        def batch(self, *, batch, metadata):
            calls.append({"batch": batch, "metadata": metadata})
            return types.SimpleNamespace(errors=[], successes=batch)

    class FakeLangfuse:
        def __init__(self):
            self.api = types.SimpleNamespace(ingestion=FakeIngestion())

        def create_trace_id(self, *, seed=None):
            calls.append({"create_trace_id": seed})
            if seed == "suite-1":
                return "abc123abc123abc123abc123abc123ab"
            return "def456def456def456def456def456de"

        def get_trace_url(self, *, trace_id=None):
            calls.append({"get_trace_url": trace_id})
            return f"https://langfuse.example/project/proj/traces/{trace_id}"

        def start_as_current_observation(self, **kwargs):
            calls.append({"observation": kwargs})
            return FakeObservation()

        def flush(self):
            calls.append({"flush": True})

    fake = FakeLangfuse()
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test-secret")
    monkeypatch.setenv("PECKER_LANGFUSE_ENABLED", "1")
    monkeypatch.setattr(
        observability.importlib,
        "import_module",
        lambda name: FakeLangfuseModule if name == "langfuse" else None,
    )

    result = record_goshawk_ab_suite_scores(
        {
            "summary": {
                "run_count": 4,
                "compact_pass_rate": 0.75,
                "median_input_token_savings_ratio": 0.44,
                "median_elapsed_savings_ratio": -0.04,
                "min_final_rule_jaccard": 0.86,
                "min_final_signature_jaccard": 0.89,
                "max_false_positive_delta": 0,
            },
            "recommendation": {"action": "keep_disabled", "reason": "quality_gate_failed"},
            "failures": [{"batch_id": "fail-1"}],
        },
        session_id="suite-1",
        client_factory=lambda: fake,
    )

    batch_call = next(call for call in calls if "batch" in call)
    score_bodies = [event["body"] for event in batch_call["batch"]]
    assert result["status"] == "recorded"
    assert result["target"] == "trace"
    assert result["trace"]["trace_id"] == "abc123abc123abc123abc123abc123ab"
    assert {body["traceId"] for body in score_bodies} == {
        "abc123abc123abc123abc123abc123ab"
    }
    assert all("sessionId" not in body for body in score_bodies)
