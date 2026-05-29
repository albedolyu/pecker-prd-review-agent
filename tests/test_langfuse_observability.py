from __future__ import annotations

import json


def test_langgraph_langfuse_trace_disabled_without_credentials(monkeypatch):
    from review.langfuse_observability import start_langgraph_review_trace

    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    monkeypatch.delenv("PECKER_LANGFUSE_ENABLED", raising=False)

    trace = start_langgraph_review_trace(
        workspace="workspace-alpha",
        thread_id="review-job:rjob_disabled",
        prd_content="# Demo",
        wiki_pages={},
        voting_rounds=1,
        dimensions=["structure"],
    )
    with trace:
        with trace.span("pecker.langgraph.prepare_round", metadata={"round": 1}) as observation:
            trace.update_observation(observation, output={"status": "ok"})
        trace.finish(status="done", output={"merged_items": 0})

    assert trace.snapshot() == {
        "enabled": False,
        "configured": False,
        "status": "disabled",
    }


def test_langgraph_langfuse_trace_redacts_inputs_and_flushes(monkeypatch):
    from review.langfuse_observability import start_langgraph_review_trace

    calls: list[dict] = []

    class FakeObservation:
        def __init__(self, call):
            self.call = call

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def update(self, **kwargs):
            self.call.setdefault("updates", []).append(kwargs)

    class FakeLangfuse:
        def start_as_current_observation(self, **kwargs):
            calls.append(kwargs)
            return FakeObservation(calls[-1])

        def flush(self):
            calls.append({"flush": True})

    prd_body = "# PRD\n" + ("secret business body token=secret-token " * 8)

    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test-secret")
    monkeypatch.setenv("PECKER_LANGFUSE_ENABLED", "1")

    trace = start_langgraph_review_trace(
        workspace="workspace-alpha",
        thread_id="review-job:rjob_secret",
        prd_content=prd_body,
        wiki_pages={"secret.md": "wiki page cookie=secret-cookie"},
        voting_rounds=1,
        dimensions=["structure"],
        client_factory=lambda: FakeLangfuse(),
    )
    with trace:
        with trace.span(
            "pecker.langgraph.worker.structure",
            metadata={
                "dimension": "structure",
                "prd_content": prd_body,
                "authorization": "Bearer should-not-leak",
            },
        ) as observation:
            trace.update_observation(
                observation,
                output={
                    "items": [{"id": "R-1", "problem": "must not leak full item"}],
                    "secret_key": "should-not-leak",
                    "input_tokens": 10,
                },
            )
        trace.finish(
            status="done",
            output={"items": [{"id": "R-1", "problem": "must not leak final item"}]},
        )

    serialized = json.dumps(calls, ensure_ascii=False)
    assert "secret business body" not in serialized
    assert "secret-token" not in serialized
    assert "secret-cookie" not in serialized
    assert "should-not-leak" not in serialized
    assert "must not leak full item" not in serialized
    assert "must not leak final item" not in serialized
    assert calls[0]["name"] == "pecker.langgraph.review"
    assert calls[1]["name"] == "pecker.langgraph.worker.structure"
    assert calls[-1] == {"flush": True}
    assert trace.snapshot()["status"] == "done"


def test_langgraph_langfuse_trace_records_native_usage_details(monkeypatch):
    from review.langfuse_observability import start_langgraph_review_trace

    calls: list[dict] = []

    class FakeObservation:
        def __init__(self, call):
            self.call = call

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def update(self, **kwargs):
            self.call.setdefault("updates", []).append(kwargs)

    class FakeLangfuse:
        def start_as_current_observation(self, **kwargs):
            calls.append(kwargs)
            return FakeObservation(calls[-1])

        def flush(self):
            calls.append({"flush": True})

    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test-secret")
    monkeypatch.setenv("PECKER_LANGFUSE_ENABLED", "1")

    trace = start_langgraph_review_trace(
        workspace="workspace-alpha",
        thread_id="review-job:rjob_usage",
        prd_content="# Demo",
        wiki_pages={},
        voting_rounds=1,
        dimensions=["structure"],
        client_factory=lambda: FakeLangfuse(),
    )
    with trace:
        with trace.span(
            "pecker.langgraph.worker.structure",
            as_type="generation",
        ) as observation:
            trace.update_observation(
                observation,
                output={
                    "status": "done",
                    "usage": {"input_tokens": 10, "output_tokens": 5},
                },
            )
        trace.finish(status="done")

    worker_update = calls[1]["updates"][0]
    assert calls[1]["as_type"] == "generation"
    assert worker_update["usage_details"] == {"input": 10, "output": 5}


def test_langgraph_langfuse_trace_propagates_queryable_session(monkeypatch):
    import review.langfuse_observability as observability

    calls: list[dict] = []
    context_events: list[str] = []

    class FakePropagationContext:
        def __enter__(self):
            context_events.append("enter")
            return self

        def __exit__(self, exc_type, exc, tb):
            context_events.append("exit")
            return False

    class FakeLangfuseModule:
        @staticmethod
        def propagate_attributes(**kwargs):
            calls.append(kwargs)
            return FakePropagationContext()

    class FakeObservation:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def update(self, **_kwargs):
            return None

    class FakeLangfuse:
        def start_as_current_observation(self, **kwargs):
            calls.append({"observation": kwargs})
            return FakeObservation()

        def flush(self):
            calls.append({"flush": True})

    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test-secret")
    monkeypatch.setenv("PECKER_LANGFUSE_ENABLED", "1")
    monkeypatch.setattr(
        observability.importlib,
        "import_module",
        lambda name: FakeLangfuseModule if name == "langfuse" else None,
    )

    trace = observability.start_langgraph_review_trace(
        workspace="workspace-alpha",
        thread_id="review-job:rjob_123",
        prd_content="# PRD\nsecret body",
        wiki_pages={"secret.md": "must not leak"},
        voting_rounds=1,
        dimensions=["structure"],
        client_factory=lambda: FakeLangfuse(),
    )
    with trace:
        trace.finish(status="done")

    propagate_call = calls[0]
    assert propagate_call["session_id"] == "review-job:rjob_123"
    assert propagate_call["trace_name"] == "pecker.langgraph.review"
    assert propagate_call["metadata"]["workspace"] == "workspace-alpha"
    assert propagate_call["metadata"]["orchestrator"] == "langgraph"
    assert context_events == ["enter", "exit"]
    assert trace.snapshot()["session_id"] == "review-job:rjob_123"


def test_langgraph_langfuse_trace_exposes_stable_trace_link(monkeypatch):
    from review.langfuse_observability import start_langgraph_review_trace

    calls: list[dict] = []

    class FakeObservation:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def update(self, **_kwargs):
            return None

    class FakeLangfuse:
        def create_trace_id(self, *, seed=None):
            calls.append({"create_trace_id": seed})
            return "abc123abc123abc123abc123abc123ab"

        def get_trace_url(self, *, trace_id=None):
            calls.append({"get_trace_url": trace_id})
            return f"https://langfuse.example/project/proj/traces/{trace_id}"

        def start_as_current_observation(self, **kwargs):
            calls.append({"observation": kwargs})
            return FakeObservation()

        def flush(self):
            calls.append({"flush": True})

    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test-secret")
    monkeypatch.setenv("PECKER_LANGFUSE_ENABLED", "1")

    trace = start_langgraph_review_trace(
        workspace="workspace-alpha",
        thread_id="review-run:rev_123",
        prd_content="# Demo",
        wiki_pages={},
        voting_rounds=1,
        dimensions=["structure"],
        client_factory=lambda: FakeLangfuse(),
    )
    with trace:
        trace.finish(status="done")

    observation = next(call["observation"] for call in calls if "observation" in call)
    assert calls[0] == {"create_trace_id": "review-run:rev_123"}
    assert {"get_trace_url": "abc123abc123abc123abc123abc123ab"} in calls
    assert observation["trace_context"] == {"trace_id": "abc123abc123abc123abc123abc123ab"}
    assert trace.snapshot()["trace_id"] == "abc123abc123abc123abc123abc123ab"
    assert trace.snapshot()["trace_url"] == (
        "https://langfuse.example/project/proj/traces/abc123abc123abc123abc123abc123ab"
    )


def test_record_review_confirmation_scores_records_safe_scores(monkeypatch):
    from review.langfuse_observability import record_review_confirmation_scores

    calls: list[dict] = []

    class FakeLangfuse:
        def create_score(self, **kwargs):
            calls.append(kwargs)

        def flush(self):
            calls.append({"flush": True})

    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test-secret")
    monkeypatch.setenv("PECKER_LANGFUSE_ENABLED", "1")

    snapshot = record_review_confirmation_scores(
        review_result={
            "review_id": "rev_score",
            "reviewer": "alice",
            "workspace": "workspace-alpha",
            "prd_name": "demo",
            "mode": "standard",
            "items": [
                {
                    "id": "R-001",
                    "rule_id": "V-05",
                    "dimension": "structure",
                    "severity": "must",
                    "location": "sec 1",
                    "problem": "raw problem must not leak",
                    "suggestion": "raw suggestion must not leak",
                    "evidence_content": "raw evidence must not leak",
                },
                {
                    "id": "R-002",
                    "rule_id": "V-07",
                    "dimension": "quality",
                    "severity": "should",
                },
            ],
        },
        decisions={
            "R-001": {"action": "accept", "reason_note": "useful"},
            "R-002": {"action": "reject", "reason_category": "model_noise"},
            "R-stale": {"action": "reject", "reason_category": "model_noise"},
        },
        client_factory=lambda: FakeLangfuse(),
    )

    assert snapshot == {
        "enabled": True,
        "configured": True,
        "status": "recorded",
        "scored_items": 2,
        "scores_sent": 3,
        "aggregate_acceptance_rate": 0.5,
    }
    item_scores = [call for call in calls if call.get("name") == "pecker.pm_item_feedback"]
    aggregate_scores = [call for call in calls if call.get("name") == "pecker.pm_acceptance_rate"]
    assert [call["value"] for call in item_scores] == [1.0, 0.0]
    assert aggregate_scores[0]["value"] == 0.5
    assert calls[-1] == {"flush": True}

    serialized = json.dumps(calls, ensure_ascii=False)
    assert "raw problem must not leak" not in serialized
    assert "raw suggestion must not leak" not in serialized
    assert "raw evidence must not leak" not in serialized
    assert "sk-test-secret" not in serialized


def test_record_review_confirmation_scores_does_not_send_pm_free_text_or_locations(monkeypatch):
    from review.langfuse_observability import record_review_confirmation_scores

    calls: list[dict] = []

    class FakeLangfuse:
        def create_score(self, **kwargs):
            calls.append(kwargs)

        def flush(self):
            calls.append({"flush": True})

    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test-secret")
    monkeypatch.setenv("PECKER_LANGFUSE_ENABLED", "1")

    snapshot = record_review_confirmation_scores(
        review_result={
            "review_id": "rev_score",
            "reviewer": "alice",
            "workspace": "workspace-alpha",
            "prd_name": "demo",
            "mode": "standard",
            "items": [
                {
                    "id": "R-001",
                    "rule_id": "V-05",
                    "dimension": "structure",
                    "severity": "must",
                    "location": "内部 Roadmap: Project Dawn launch date Q4",
                }
            ],
        },
        decisions={
            "R-001": {
                "action": "reject",
                "reason_category": "model_noise",
                "reason_note": "Customer ACME private rollout should not leave Pecker",
            }
        },
        client_factory=lambda: FakeLangfuse(),
    )

    assert snapshot["status"] == "recorded"
    item_score = next(call for call in calls if call.get("name") == "pecker.pm_item_feedback")
    metadata = item_score["metadata"]
    assert metadata["reason_note_present"] is True
    assert metadata["reason_note_chars"] == len("Customer ACME private rollout should not leave Pecker")
    assert metadata["location_present"] is True
    assert "reason_note" not in metadata
    assert "location" not in metadata
    serialized = json.dumps(calls, ensure_ascii=False)
    assert "Customer ACME private rollout" not in serialized
    assert "Project Dawn" not in serialized


def test_record_review_confirmation_scores_reuses_langgraph_session(monkeypatch):
    from review.langfuse_observability import record_review_confirmation_scores

    calls: list[dict] = []

    class FakeLangfuse:
        def create_score(self, **kwargs):
            calls.append(kwargs)

        def flush(self):
            calls.append({"flush": True})

    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test-secret")
    monkeypatch.setenv("PECKER_LANGFUSE_ENABLED", "1")

    snapshot = record_review_confirmation_scores(
        review_result={
            "review_id": "rev_score",
            "reviewer": "alice",
            "workspace": "workspace-alpha",
            "prd_name": "demo",
            "mode": "standard",
            "telemetry": {
                "observability": {
                    "langfuse": {
                        "session_id": "review-job:rjob_123",
                        "trace_id": "abc123abc123abc123abc123abc123ab",
                    }
                }
            },
            "items": [
                {
                    "id": "R-001",
                    "rule_id": "V-05",
                    "dimension": "structure",
                    "severity": "must",
                }
            ],
        },
        decisions={"R-001": {"action": "accept"}},
        client_factory=lambda: FakeLangfuse(),
    )

    assert snapshot["status"] == "recorded"
    assert snapshot["trace_id"] == "abc123abc123abc123abc123abc123ab"
    assert snapshot["trace_linked"] is True
    score_calls = [call for call in calls if "name" in call]
    assert all("session_id" not in call for call in score_calls)
    assert {call["trace_id"] for call in score_calls} == {
        "abc123abc123abc123abc123abc123ab"
    }


def test_record_evidence_verification_scores_records_safe_scores(monkeypatch):
    from review.langfuse_observability import record_evidence_verification_scores

    calls: list[dict] = []

    class FakeLangfuse:
        def create_score(self, **kwargs):
            calls.append(kwargs)

        def flush(self):
            calls.append({"flush": True})

    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test-secret")
    monkeypatch.setenv("PECKER_LANGFUSE_ENABLED", "1")

    snapshot = record_evidence_verification_scores(
        review_result={
            "review_id": "rev_ev",
            "reviewer": "alice",
            "workspace": "workspace-alpha",
            "prd_name": "demo",
            "mode": "standard",
            "telemetry": {
                "observability": {
                    "langfuse": {
                        "session_id": "review-run:rev_ev",
                        "trace_id": "abc123abc123abc123abc123abc123ab",
                    }
                }
            },
        },
        verified_items=[
            {
                "id": "R-001",
                "rule_id": "V-05",
                "dimension": "structure",
                "severity": "must",
                "verification_status": "verified",
                "evidence_type": "A",
                "evidence_content": "raw evidence must not leak",
                "problem": "raw problem must not leak",
            },
            {
                "id": "R-002",
                "rule_id": "V-07",
                "dimension": "quality",
                "severity": "should",
                "verification_status": "verified_with_caveat",
                "verification_details": {"reason_code": "A_wiki_page_not_found_weak"},
                "suggestion": "raw suggestion must not leak",
            },
            {
                "id": "R-003",
                "rule_id": "V-99",
                "dimension": "risk",
                "severity": "must",
                "verification_status": "retracted",
                "verification_details": {"reason_code": "B_missing_rule"},
            },
        ],
        summary={
            "total": 3,
            "verified": 2,
            "caveat": 1,
            "retracted": 1,
            "reliability": 0.667,
        },
        client_factory=lambda: FakeLangfuse(),
    )

    assert snapshot == {
        "enabled": True,
        "configured": True,
        "status": "recorded",
        "scored_items": 3,
        "scores_sent": 4,
        "trace_id": "abc123abc123abc123abc123abc123ab",
        "trace_linked": True,
        "reliability": 0.667,
        "caveat": 1,
        "retracted": 1,
    }
    item_scores = [call for call in calls if call.get("name") == "pecker.evidence_item_status"]
    aggregate_scores = [call for call in calls if call.get("name") == "pecker.evidence_reliability"]
    assert [call["value"] for call in item_scores] == [1.0, 0.5, 0.0]
    assert aggregate_scores[0]["value"] == 0.667
    assert all("session_id" not in call for call in item_scores + aggregate_scores)
    assert {call["trace_id"] for call in item_scores + aggregate_scores} == {
        "abc123abc123abc123abc123abc123ab"
    }
    assert calls[-1] == {"flush": True}

    serialized = json.dumps(calls, ensure_ascii=False)
    assert "raw evidence must not leak" not in serialized
    assert "raw problem must not leak" not in serialized
    assert "raw suggestion must not leak" not in serialized
    assert "sk-test-secret" not in serialized


def test_record_evidence_verification_scores_prefers_direct_batch_ingestion(monkeypatch):
    from review.langfuse_observability import record_evidence_verification_scores

    calls: list[dict] = []

    class FakeIngestion:
        def batch(self, **kwargs):
            calls.append(kwargs)

    class FakeApi:
        ingestion = FakeIngestion()

    class FakeLangfuse:
        api = FakeApi()

        def create_trace_id(self, *, seed=None):
            return "abcdefabcdefabcdefabcdefabcdefab"

        def create_score(self, **_kwargs):
            raise AssertionError("direct batch ingestion should avoid async score queue")

        def flush(self):
            raise AssertionError("direct batch ingestion should not rely on async flush")

    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test-secret")
    monkeypatch.setenv("PECKER_LANGFUSE_ENABLED", "1")

    snapshot = record_evidence_verification_scores(
        review_result={
            "review_id": "rev_ev",
            "reviewer": "alice",
            "workspace": "workspace-alpha",
            "prd_name": "demo",
            "mode": "standard",
            "telemetry": {
                "observability": {
                    "langfuse": {
                        "session_id": "review-job:rjob_123",
                        "trace_id": "abc123abc123abc123abc123abc123ab",
                    }
                }
            },
        },
        verified_items=[
            {
                "id": "R-001",
                "rule_id": "V-05",
                "dimension": "structure",
                "severity": "must",
                "verification_status": "verified",
                "evidence_type": "A",
                "evidence_content": "raw evidence must not leak",
            }
        ],
        summary={"total": 1, "verified": 1, "reliability": 1.0},
        client_factory=lambda: FakeLangfuse(),
    )

    assert snapshot["status"] == "recorded"
    assert snapshot["scored_items"] == 1
    assert snapshot["scores_sent"] == 2
    assert len(calls) == 1
    batch = calls[0]["batch"]
    assert [event["type"] for event in batch] == ["score-create", "score-create"]
    assert {event["body"]["traceId"] for event in batch} == {
        "abc123abc123abc123abc123abc123ab"
    }
    assert all("sessionId" not in event["body"] for event in batch)
    serialized = json.dumps(calls, ensure_ascii=False)
    assert "raw evidence must not leak" not in serialized


def test_record_evidence_verification_scores_reports_batch_errors(monkeypatch):
    from review.langfuse_observability import record_evidence_verification_scores

    class FakeBatchResponse:
        successes = []
        errors = [{"message": "Provide exactly one score target"}]

    class FakeIngestion:
        def batch(self, **_kwargs):
            return FakeBatchResponse()

    class FakeApi:
        ingestion = FakeIngestion()

    class FakeLangfuse:
        api = FakeApi()

        def create_trace_id(self, *, seed=None):
            return "abcdefabcdefabcdefabcdefabcdefab"

    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test-secret")
    monkeypatch.setenv("PECKER_LANGFUSE_ENABLED", "1")

    snapshot = record_evidence_verification_scores(
        review_result={
            "review_id": "rev_ev",
            "reviewer": "alice",
            "workspace": "workspace-alpha",
            "prd_name": "demo",
            "mode": "standard",
            "telemetry": {
                "observability": {
                    "langfuse": {
                        "session_id": "review-job:rjob_123",
                        "trace_id": "abc123abc123abc123abc123abc123ab",
                    }
                }
            },
        },
        verified_items=[
            {
                "id": "R-001",
                "rule_id": "V-05",
                "dimension": "structure",
                "severity": "must",
                "verification_status": "verified",
            }
        ],
        summary={"total": 1, "verified": 1, "reliability": 1.0},
        client_factory=lambda: FakeLangfuse(),
    )

    assert snapshot["status"] == "error"
    assert snapshot["scores_sent"] == 0
    assert "Langfuse score batch rejected" in snapshot["error"]
