from __future__ import annotations

import json


def _sample_result() -> dict:
    return {
        "feedback_kind": "downstream_code_change_signal",
        "summary": {
            "total_findings": 3,
            "likely_adopted": 1,
            "possible_related": 1,
            "no_code_change_signal": 1,
            "implementation_signal_rate": 0.5,
        },
        "signals": [
            {
                "finding_id": "G-001",
                "rule_id": "RC-004",
                "dimension": "data_contract",
                "severity": "must",
                "feedback_label": "likely_adopted_by_implementation",
                "confidence": 0.88,
                "changed_files": ["api/company_logo.py", "schemas/company.py"],
                "change_types": ["api_changed", "schema_added"],
                "evidence": [{"snippets": ["def upload_company_logo(): pass"]}],
            },
            {
                "finding_id": "G-002",
                "rule_id": "EV-01",
                "dimension": "workflow",
                "severity": "should",
                "feedback_label": "possible_related_code_change",
                "confidence": 0.55,
                "changed_files": ["api/workflow.py"],
                "change_types": ["workflow_changed"],
                "evidence": [{"snippets": ["if status == 'failed':"]}],
            },
            {
                "finding_id": "G-003",
                "rule_id": "V-05",
                "dimension": "structure",
                "severity": "should",
                "feedback_label": "no_code_change_signal",
                "confidence": 0.0,
                "changed_files": [],
                "change_types": [],
                "evidence": [],
            },
        ],
    }


def test_code_change_feedback_store_records_and_summarizes(tmp_path):
    from review.code_change_feedback_store import (
        get_recent_code_change_feedback_signals,
        record_code_change_feedback_result,
        summarize_code_change_feedback_store,
    )

    db_path = tmp_path / "code_feedback.db"
    result = record_code_change_feedback_result(
        _sample_result(),
        review_id="rev-logo",
        source_ref="review-commit",
        target_ref="implementation-commit",
        db_path=db_path,
    )
    summary = summarize_code_change_feedback_store(db_path=db_path)
    recent = get_recent_code_change_feedback_signals(limit=5, db_path=db_path)

    assert result == {
        "status": "recorded",
        "signals_recorded": 3,
        "db_path": str(db_path),
    }
    assert summary["total_signals"] == 3
    assert summary["likely_adopted"] == 1
    assert summary["possible_related"] == 1
    assert summary["no_code_change_signal"] == 1
    assert summary["implementation_signal_rate"] == 0.5
    assert summary["by_dimension"]["data_contract"]["likely_adopted"] == 1
    assert summary["by_rule"]["RC-004"]["likely_adopted"] == 1
    g001 = next(row for row in recent if row["finding_id"] == "G-001")
    assert g001["review_id"] == "rev-logo"
    assert g001["target_ref"] == "implementation-commit"
    assert g001["changed_files"] == ["api/company_logo.py", "schemas/company.py"]


def test_code_change_feedback_store_redacts_evidence_snippets(tmp_path):
    from review.code_change_feedback_store import (
        get_recent_code_change_feedback_signals,
        record_code_change_feedback_result,
    )

    payload = _sample_result()
    payload["signals"][0]["evidence"] = [
        {"snippets": ["OPENAI_API_KEY = 'sk-should-not-leak-1234567890'"]}
    ]

    db_path = tmp_path / "code_feedback.db"
    record_code_change_feedback_result(payload, db_path=db_path)
    recent = get_recent_code_change_feedback_signals(limit=3, db_path=db_path)
    serialized = json.dumps(recent, ensure_ascii=False)

    assert "sk-should-not-leak" not in serialized
    assert "[REDACTED" in serialized


def test_code_change_feedback_cli_can_persist_store(tmp_path):
    from scripts.code_change_feedback import main

    findings_path = tmp_path / "findings.json"
    diff_path = tmp_path / "change.diff"
    output_path = tmp_path / "feedback.json"
    db_path = tmp_path / "code_feedback.db"
    findings_path.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "id": "G-004",
                        "rule_id": "RC-004",
                        "dimension": "data_contract",
                        "severity": "must",
                        "location": "Company logo schema",
                        "issue": "Missing logo_url.",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    diff_path.write_text(
        """
diff --git a/schemas/company.py b/schemas/company.py
@@ -1,1 +1,2 @@
+logo_url: str
""",
        encoding="utf-8",
    )

    code = main(
        [
            "--findings-json",
            str(findings_path),
            "--diff-file",
            str(diff_path),
            "--output-json",
            str(output_path),
            "--store-db",
            str(db_path),
            "--review-id",
            "rev-logo",
            "--source-ref",
            "review-commit",
            "--target-ref",
            "impl-commit",
        ]
    )

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert code == 0
    assert payload["store"]["status"] == "recorded"
    assert payload["store"]["signals_recorded"] == 1
