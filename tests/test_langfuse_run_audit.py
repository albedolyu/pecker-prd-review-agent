from __future__ import annotations

import json


def _sample_review_result() -> dict:
    return {
        "review_id": "rev_audit",
        "prd_name": "demo.md",
        "workspace": "workspace-alpha",
        "telemetry": {
            "orchestrator": "langgraph",
            "graph_trace": [
                "prepare_round",
                "worker.structure",
                "worker.quality",
                "finalize_round",
                "finalize_review",
            ],
            "worker_node_statuses": [
                {"dimension": "structure", "status": "success", "error_type": ""},
                {"dimension": "quality", "status": "success", "error_type": ""},
            ],
            "resilience": {
                "failed_workers": 0,
                "recovered_workers": 1,
                "recommended_batch_size": 2,
            },
            "observability": {
                "langfuse": {
                    "enabled": True,
                    "configured": True,
                    "status": "done",
                    "backend": "langfuse",
                    "session_id": "review-run:rev_audit",
                    "trace_id": "abc123abc123abc123abc123abc123ab",
                    "trace_url": "https://langfuse.example/project/proj/traces/abc123abc123abc123abc123abc123ab",
                },
                "langfuse_evidence": {
                    "enabled": True,
                    "configured": True,
                    "status": "recorded",
                    "scored_items": 3,
                    "scores_sent": 4,
                    "trace_id": "abc123abc123abc123abc123abc123ab",
                    "reliability": 0.667,
                    "caveat": 1,
                    "retracted": 1,
                },
                "langgraph_checkpoint": {
                    "enabled": True,
                    "thread_id": "review-run:rev_audit",
                    "status": "ready",
                    "checkpoint_path": ".pecker_checkpoints/langgraph.pkl",
                    "checkpoint_exists": True,
                    "thread_found": True,
                    "checkpoint_count": 12,
                },
            },
            "workers": {
                "structure": {
                    "prompt": {
                        "name": "pecker.worker.structure.system",
                        "source": "langfuse",
                        "status": "ready",
                        "label": "production",
                        "version": 8,
                        "hash": "hash-structure",
                    }
                },
                "quality": {
                    "prompt": {
                        "name": "pecker.worker.quality.system",
                        "source": "langfuse",
                        "status": "ready",
                        "label": "production",
                        "version": 8,
                        "hash": "hash-quality",
                    }
                },
            },
        },
        "items": [{"id": "R-001", "problem": "raw finding must not leak"}],
    }


def test_build_langfuse_run_audit_summarizes_trace_prompts_and_scores():
    from scripts.langfuse_run_audit import build_langfuse_run_audit

    audit = build_langfuse_run_audit(
        _sample_review_result(),
        confirmation_result={
            "langfuse_feedback": {
                "status": "recorded",
                "scored_items": 2,
                "scores_sent": 3,
                "trace_id": "abc123abc123abc123abc123abc123ab",
                "aggregate_acceptance_rate": 0.5,
            }
        },
    )

    assert audit["ok"] is True
    assert audit["review_id"] == "rev_audit"
    assert audit["orchestrator"] == "langgraph"
    assert audit["session_checkpoint_linked"] is True
    assert audit["session_checkpoint_mismatch"] is False
    assert audit["langfuse"]["session_id"] == "review-run:rev_audit"
    assert audit["langfuse"]["trace_link_ready"] is True
    assert audit["langfuse"]["trace_url"].endswith("/abc123abc123abc123abc123abc123ab")
    assert audit["langfuse"]["evidence_scores"]["trace_id"] == (
        "abc123abc123abc123abc123abc123ab"
    )
    assert audit["langfuse"]["evidence_scores"]["trace_linked"] is True
    assert audit["langfuse"]["pm_feedback_scores"]["trace_id"] == (
        "abc123abc123abc123abc123abc123ab"
    )
    assert audit["langfuse"]["pm_feedback_scores"]["trace_linked"] is True
    assert audit["langgraph_checkpoint"] == {
        "enabled": True,
        "thread_id": "review-run:rev_audit",
        "status": "ready",
        "checkpoint_path": ".pecker_checkpoints/langgraph.pkl",
        "checkpoint_exists": True,
        "thread_found": True,
        "checkpoint_count": 12,
    }
    assert audit["langgraph"] == {
        "graph_trace": [
            "prepare_round",
            "worker.structure",
            "worker.quality",
            "finalize_round",
            "finalize_review",
        ],
        "graph_trace_ready": True,
        "graph_trace_order_ready": True,
        "missing_worker_trace_nodes": [],
        "worker_node_statuses": [
            {"dimension": "structure", "status": "success", "error_type": ""},
            {"dimension": "quality", "status": "success", "error_type": ""},
        ],
        "worker_nodes_named": True,
        "worker_nodes_ready": True,
        "failed_workers": 0,
        "recovered_workers": 1,
        "recommended_batch_size": 2,
    }
    assert audit["langfuse"]["evidence_scores"]["status"] == "recorded"
    assert audit["langfuse"]["pm_feedback_scores"]["scores_sent"] == 3
    assert audit["langfuse"]["prompt_versions"] == [
        {
            "worker": "quality",
            "name": "pecker.worker.quality.system",
            "source": "langfuse",
            "status": "ready",
            "label": "production",
            "version": 8,
            "hash": "hash-quality",
        },
        {
            "worker": "structure",
            "name": "pecker.worker.structure.system",
            "source": "langfuse",
            "status": "ready",
            "label": "production",
            "version": 8,
            "hash": "hash-structure",
        },
    ]
    serialized = json.dumps(audit, ensure_ascii=False)
    assert "raw finding must not leak" not in serialized


def test_langfuse_run_audit_markdown_shows_checkpoint_thread_link():
    from scripts.langfuse_run_audit import (
        build_langfuse_run_audit,
        render_langfuse_run_audit_markdown,
    )

    audit = build_langfuse_run_audit(_sample_review_result())

    markdown = render_langfuse_run_audit_markdown(audit)

    assert "- session_id: `review-run:rev_audit`" in markdown
    assert "- checkpoint_thread_id: `review-run:rev_audit`" in markdown
    assert "- session_checkpoint_linked: `True`" in markdown
    assert "- graph_trace_order_ready: `True`" in markdown


def test_langfuse_run_audit_markdown_shows_operator_status_summary():
    from scripts.langfuse_run_audit import (
        build_langfuse_run_audit,
        render_langfuse_run_audit_markdown,
    )

    result = _sample_review_result()
    result["telemetry"]["observability"]["langfuse"]["enabled"] = False
    result["telemetry"]["observability"]["langfuse"]["configured"] = False

    audit = build_langfuse_run_audit(result)

    markdown = render_langfuse_run_audit_markdown(audit)

    assert "- status: `missing`" in markdown
    assert "- ok: `False`" in markdown
    assert "- missing_count: `2`" in markdown


def test_langfuse_run_audit_exposes_operator_status_fields():
    from scripts.langfuse_run_audit import build_langfuse_run_audit

    result = _sample_review_result()
    result["telemetry"]["observability"]["langfuse"]["enabled"] = False
    result["telemetry"]["observability"]["langfuse"]["configured"] = False

    audit = build_langfuse_run_audit(result)

    assert audit["status"] == "missing"
    assert audit["missing_count"] == 2


def test_langfuse_run_audit_snapshot_exposes_operator_status_fields():
    from scripts.langfuse_run_audit import (
        build_langfuse_run_audit,
        build_langfuse_run_audit_snapshot,
    )

    result = _sample_review_result()
    result["telemetry"]["observability"]["langfuse"]["enabled"] = False
    result["telemetry"]["observability"]["langfuse"]["configured"] = False

    audit = build_langfuse_run_audit(result)
    snapshot = build_langfuse_run_audit_snapshot(
        audit,
        json_path="output/langfuse_audits/rev_audit.json",
        markdown_path="output/langfuse_audits/rev_audit.md",
    )

    assert snapshot["status"] == "missing"
    assert snapshot["missing_count"] == 2


def test_langfuse_run_audit_marks_disabled_observability_missing():
    from scripts.langfuse_run_audit import build_langfuse_run_audit

    result = _sample_review_result()
    langfuse = result["telemetry"]["observability"]["langfuse"]
    langfuse["enabled"] = False
    langfuse["configured"] = False
    result["telemetry"]["observability"]["langgraph_checkpoint"]["enabled"] = False

    audit = build_langfuse_run_audit(result)

    assert audit["ok"] is False
    assert audit["langfuse"]["trace_link_ready"] is True
    assert audit["langgraph_checkpoint"]["thread_id"] == "review-run:rev_audit"
    assert "langfuse.enabled" in audit["missing"]
    assert "langfuse.configured" in audit["missing"]
    assert "langgraph_checkpoint.enabled" in audit["missing"]


def test_langfuse_run_audit_marks_missing_checkpoint_when_thread_not_found():
    from scripts.langfuse_run_audit import build_langfuse_run_audit

    result = _sample_review_result()
    result["telemetry"]["observability"]["langgraph_checkpoint"] = {
        "enabled": True,
        "thread_id": "review-run:rev_audit",
        "status": "missing",
        "checkpoint_path": ".pecker_checkpoints/langgraph.pkl",
        "checkpoint_exists": False,
        "thread_found": False,
        "checkpoint_count": 0,
    }

    audit = build_langfuse_run_audit(result)

    assert audit["ok"] is False
    assert audit["langgraph_checkpoint"]["status"] == "missing"
    assert "langgraph_checkpoint.thread_found" in audit["missing"]
    assert "langgraph_checkpoint.status" in audit["missing"]


def test_langfuse_run_audit_marks_missing_checkpoint_snapshot():
    from scripts.langfuse_run_audit import build_langfuse_run_audit

    result = _sample_review_result()
    result["telemetry"]["observability"].pop("langgraph_checkpoint")

    audit = build_langfuse_run_audit(result)

    assert audit["ok"] is False
    assert audit["langfuse"]["trace_link_ready"] is True
    assert audit["langgraph_checkpoint"]["thread_id"] == ""
    assert "langgraph_checkpoint" in audit["missing"]


def test_langfuse_run_audit_marks_missing_checkpoint_thread_id():
    from scripts.langfuse_run_audit import build_langfuse_run_audit

    result = _sample_review_result()
    result["telemetry"]["observability"]["langgraph_checkpoint"].pop("thread_id")

    audit = build_langfuse_run_audit(result)

    assert audit["ok"] is False
    assert audit["langgraph_checkpoint"]["status"] == "ready"
    assert audit["langgraph_checkpoint"]["thread_id"] == ""
    assert "langgraph_checkpoint.thread_id" in audit["missing"]


def test_langfuse_run_audit_marks_session_checkpoint_thread_mismatch_missing():
    from scripts.langfuse_run_audit import (
        build_langfuse_run_audit,
        build_langfuse_run_audit_snapshot,
        render_langfuse_run_audit_markdown,
    )

    result = _sample_review_result()
    checkpoint = result["telemetry"]["observability"]["langgraph_checkpoint"]
    checkpoint["thread_id"] = "review-run:other"

    audit = build_langfuse_run_audit(result)
    snapshot = build_langfuse_run_audit_snapshot(
        audit,
        json_path="output/langfuse_audits/rev_audit.json",
        markdown_path="output/langfuse_audits/rev_audit.md",
    )

    assert audit["ok"] is False
    assert audit["session_checkpoint_linked"] is False
    assert audit["session_checkpoint_mismatch"] is True
    assert audit["langfuse"]["session_id"] == "review-run:rev_audit"
    assert audit["langgraph_checkpoint"]["thread_id"] == "review-run:other"
    assert "langfuse.session_checkpoint_thread" in audit["missing"]
    assert snapshot["session_checkpoint_linked"] is False
    assert snapshot["session_checkpoint_mismatch"] is True
    markdown = render_langfuse_run_audit_markdown(audit)
    assert "- session_checkpoint_linked: `False`" in markdown
    assert "- session_checkpoint_mismatch: `True`" in markdown


def test_langfuse_run_audit_marks_score_trace_mismatch_missing():
    from scripts.langfuse_run_audit import build_langfuse_run_audit

    result = _sample_review_result()
    result["telemetry"]["observability"]["langfuse_evidence"]["trace_id"] = (
        "fedcba9876543210fedcba9876543210"
    )

    audit = build_langfuse_run_audit(result)

    assert audit["ok"] is False
    assert audit["langfuse"]["evidence_scores"]["trace_linked"] is False
    assert "langfuse_evidence.trace_id" in audit["missing"]


def test_langfuse_run_audit_marks_missing_evidence_scores_when_findings_exist():
    from scripts.langfuse_run_audit import build_langfuse_run_audit

    result = _sample_review_result()
    result["telemetry"]["observability"].pop("langfuse_evidence")

    audit = build_langfuse_run_audit(result)

    assert audit["ok"] is False
    assert audit["langfuse"]["evidence_scores"]["status"] == ""
    assert audit["langfuse"]["evidence_scores"]["scored_items"] == 0
    assert "langfuse_evidence" in audit["missing"]


def test_langfuse_run_audit_marks_recorded_scores_with_zero_sent_missing():
    from scripts.langfuse_run_audit import build_langfuse_run_audit

    result = _sample_review_result()
    evidence = result["telemetry"]["observability"]["langfuse_evidence"]
    evidence["scored_items"] = 3
    evidence["scores_sent"] = 0

    audit = build_langfuse_run_audit(
        result,
        confirmation_result={
            "langfuse_feedback": {
                "status": "recorded",
                "scored_items": 2,
                "scores_sent": 0,
                "trace_id": "abc123abc123abc123abc123abc123ab",
            }
        },
    )

    assert audit["ok"] is False
    assert audit["langfuse"]["evidence_scores"]["scored_items"] == 3
    assert audit["langfuse"]["evidence_scores"]["scores_sent"] == 0
    assert audit["langfuse"]["pm_feedback_scores"]["scored_items"] == 2
    assert audit["langfuse"]["pm_feedback_scores"]["scores_sent"] == 0
    assert "langfuse_evidence.scores_sent" in audit["missing"]
    assert "langfuse_feedback.scores_sent" in audit["missing"]


def test_langfuse_run_audit_snapshot_exposes_score_failure_flags():
    from scripts.langfuse_run_audit import (
        build_langfuse_run_audit,
        build_langfuse_run_audit_snapshot,
    )

    result = _sample_review_result()
    evidence = result["telemetry"]["observability"]["langfuse_evidence"]
    evidence["scored_items"] = 3
    evidence["scores_sent"] = 0

    audit = build_langfuse_run_audit(
        result,
        confirmation_result={
            "langfuse_feedback": {
                "status": "recorded",
                "scored_items": 2,
                "scores_sent": 0,
                "trace_id": "abc123abc123abc123abc123abc123ab",
            }
        },
    )

    snapshot = build_langfuse_run_audit_snapshot(
        audit,
        json_path="output/langfuse_audits/rev_audit.json",
        markdown_path="output/langfuse_audits/rev_audit.md",
    )

    assert snapshot["ok"] is False
    assert snapshot["evidence_score_failure"] is True
    assert snapshot["feedback_score_failure"] is True
    assert "langfuse_evidence.scores_sent" in snapshot["missing"]
    assert "langfuse_feedback.scores_sent" in snapshot["missing"]


def test_langfuse_run_audit_marks_langfuse_prompt_without_label_or_hash_missing():
    from scripts.langfuse_run_audit import build_langfuse_run_audit

    result = _sample_review_result()
    prompt = result["telemetry"]["workers"]["structure"]["prompt"]
    prompt.pop("label")
    prompt.pop("hash")

    audit = build_langfuse_run_audit(result)

    assert audit["ok"] is False
    assert "worker_prompt.structure.label" in audit["missing"]
    assert "worker_prompt.structure.hash" in audit["missing"]


def test_langfuse_run_audit_marks_missing_prompt_for_worker_node():
    from scripts.langfuse_run_audit import build_langfuse_run_audit

    result = _sample_review_result()
    result["telemetry"]["workers"].pop("quality")

    audit = build_langfuse_run_audit(result)

    assert audit["ok"] is False
    assert [prompt["worker"] for prompt in audit["langfuse"]["prompt_versions"]] == [
        "structure",
    ]
    assert "worker_prompt.quality" in audit["missing"]


def test_langfuse_run_audit_collects_prompt_versions_from_worker_results_when_telemetry_workers_missing():
    from scripts.langfuse_run_audit import build_langfuse_run_audit

    result = _sample_review_result()
    result["telemetry"].pop("workers")
    result["workers"] = [
        {
            "dimension": "structure",
            "telemetry": {
                "prompt": {
                    "name": "pecker.worker.structure.system",
                    "source": "langfuse",
                    "status": "ready",
                    "label": "production",
                    "version": 8,
                    "hash": "hash-structure",
                }
            },
        },
        {
            "dimension": "quality",
            "telemetry": {
                "prompt": {
                    "name": "pecker.worker.quality.system",
                    "source": "langfuse",
                    "status": "ready",
                    "label": "production",
                    "version": 8,
                    "hash": "hash-quality",
                }
            },
        },
    ]

    audit = build_langfuse_run_audit(result)

    assert audit["ok"] is True
    assert "worker_prompts" not in audit["missing"]
    assert [prompt["worker"] for prompt in audit["langfuse"]["prompt_versions"]] == [
        "quality",
        "structure",
    ]


def test_langfuse_run_audit_marks_missing_graph_trace_and_failed_worker_status():
    from scripts.langfuse_run_audit import build_langfuse_run_audit

    result = _sample_review_result()
    result["telemetry"]["graph_trace"] = []
    result["telemetry"]["worker_node_statuses"][1]["status"] = "failed"

    audit = build_langfuse_run_audit(result)

    assert audit["ok"] is False
    assert audit["langgraph"]["graph_trace_ready"] is False
    assert audit["langgraph"]["worker_nodes_ready"] is False
    assert "langgraph.graph_trace" in audit["missing"]
    assert "langgraph.worker_node_statuses.status" in audit["missing"]


def test_langfuse_run_audit_marks_missing_worker_node_in_graph_trace():
    from scripts.langfuse_run_audit import build_langfuse_run_audit

    result = _sample_review_result()
    result["telemetry"]["graph_trace"].remove("worker.quality")

    audit = build_langfuse_run_audit(result)

    assert audit["ok"] is False
    assert audit["langgraph"]["graph_trace_ready"] is False
    assert "langgraph.graph_trace.worker.quality" in audit["missing"]


def test_langfuse_run_audit_marks_worker_trace_out_of_order():
    from scripts.langfuse_run_audit import build_langfuse_run_audit

    result = _sample_review_result()
    result["telemetry"]["graph_trace"] = [
        "prepare_round",
        "finalize_round",
        "finalize_review",
        "worker.structure",
        "worker.quality",
    ]

    audit = build_langfuse_run_audit(result)

    assert audit["ok"] is False
    assert audit["langgraph"]["graph_trace_ready"] is False
    assert audit["langgraph"]["graph_trace_order_ready"] is False
    assert "langgraph.graph_trace.order" in audit["missing"]


def test_langfuse_run_audit_marks_worker_node_without_dimension_missing():
    from scripts.langfuse_run_audit import build_langfuse_run_audit

    result = _sample_review_result()
    result["telemetry"]["worker_node_statuses"][1]["dimension"] = ""

    audit = build_langfuse_run_audit(result)

    assert audit["ok"] is False
    assert audit["langgraph"]["worker_nodes_ready"] is False
    assert "langgraph.worker_node_statuses.dimension" in audit["missing"]


def test_langfuse_run_audit_cli_require_ready_exits_nonzero_when_trace_missing(tmp_path, capsys):
    from scripts.langfuse_run_audit import main

    result = _sample_review_result()
    result["telemetry"]["observability"]["langfuse"].pop("trace_url")
    result_path = tmp_path / "review-result.json"
    result_path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")

    exit_code = main([
        "--review-result",
        str(result_path),
        "--format",
        "json",
        "--require-ready",
    ])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert payload["ok"] is False
    assert "langfuse.trace_url" in payload["missing"]


def test_langfuse_run_audit_cli_reads_windows_utf8_bom_json(tmp_path, capsys):
    from scripts.langfuse_run_audit import main

    result_path = tmp_path / "review-result.json"
    result_path.write_text(
        json.dumps(_sample_review_result(), ensure_ascii=False),
        encoding="utf-8-sig",
    )

    exit_code = main([
        "--review-result",
        str(result_path),
        "--format",
        "json",
        "--require-ready",
    ])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["ok"] is True


def test_langfuse_run_audit_cli_writes_json_and_markdown_artifacts(tmp_path, capsys):
    from scripts.langfuse_run_audit import main

    result_path = tmp_path / "review-result.json"
    json_path = tmp_path / "output" / "langfuse_audits" / "rev_audit.json"
    markdown_path = tmp_path / "output" / "langfuse_audits" / "rev_audit.md"
    result_path.write_text(
        json.dumps(_sample_review_result(), ensure_ascii=False),
        encoding="utf-8",
    )

    exit_code = main([
        "--review-result",
        str(result_path),
        "--format",
        "json",
        "--output-json",
        str(json_path),
        "--output-markdown",
        str(markdown_path),
        "--require-ready",
    ])

    stdout_payload = json.loads(capsys.readouterr().out)
    saved_payload = json.loads(json_path.read_text(encoding="utf-8"))
    saved_markdown = markdown_path.read_text(encoding="utf-8")
    assert exit_code == 0
    assert stdout_payload["ok"] is True
    assert saved_payload["review_id"] == "rev_audit"
    assert saved_payload["status"] == "ready"
    assert "- status: `ready`" in saved_markdown
    assert "- missing_count: `0`" in saved_markdown


def test_langfuse_run_audit_cli_writes_snapshot_artifact(tmp_path, capsys):
    from scripts.langfuse_run_audit import main

    result_path = tmp_path / "review-result.json"
    json_path = tmp_path / "output" / "langfuse_audits" / "rev_audit.json"
    markdown_path = tmp_path / "output" / "langfuse_audits" / "rev_audit.md"
    snapshot_path = tmp_path / "output" / "langfuse_audits" / "rev_audit.snapshot.json"
    result_path.write_text(
        json.dumps(_sample_review_result(), ensure_ascii=False),
        encoding="utf-8",
    )

    exit_code = main([
        "--review-result",
        str(result_path),
        "--format",
        "json",
        "--output-json",
        str(json_path),
        "--output-markdown",
        str(markdown_path),
        "--output-snapshot",
        str(snapshot_path),
        "--snapshot-json-path",
        "output/langfuse_audits/rev_audit.json",
        "--snapshot-markdown-path",
        "output/langfuse_audits/rev_audit.md",
        "--require-ready",
    ])

    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert json.loads(capsys.readouterr().out)["ok"] is True
    assert exit_code == 0
    assert snapshot["ok"] is True
    assert snapshot["status"] == "ready"
    assert snapshot["missing_count"] == 0
    assert snapshot["json_path"] == "output/langfuse_audits/rev_audit.json"
    assert snapshot["markdown_path"] == "output/langfuse_audits/rev_audit.md"
    assert snapshot["trace_link_ready"] is True
    assert snapshot["session_checkpoint_linked"] is True


def test_langfuse_run_audit_cli_prints_snapshot_format(tmp_path, capsys):
    from scripts.langfuse_run_audit import main

    result_path = tmp_path / "review-result.json"
    result_path.write_text(
        json.dumps(_sample_review_result(), ensure_ascii=False),
        encoding="utf-8",
    )

    exit_code = main([
        "--review-result",
        str(result_path),
        "--format",
        "snapshot",
        "--snapshot-json-path",
        "output/langfuse_audits/rev_audit.json",
        "--snapshot-markdown-path",
        "output/langfuse_audits/rev_audit.md",
        "--require-ready",
    ])

    snapshot = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert snapshot["ok"] is True
    assert snapshot["status"] == "ready"
    assert snapshot["missing_count"] == 0
    assert snapshot["json_path"] == "output/langfuse_audits/rev_audit.json"
    assert snapshot["markdown_path"] == "output/langfuse_audits/rev_audit.md"
    assert snapshot["trace_link_ready"] is True
