from __future__ import annotations

import json


def test_code_diff_feedback_detects_likely_implementation_adoption():
    from review.code_change_feedback import build_code_change_feedback

    findings = [
        {
            "id": "G-012",
            "rule_id": "RC-004",
            "dimension": "data_contract",
            "severity": "must",
            "location": "Company logo upload API fields",
            "issue": "PRD does not define logo_url and company_id validation.",
            "suggestion": "Add explicit fields and validation for logo upload.",
        }
    ]
    diff_text = """
diff --git a/api/company_logo.py b/api/company_logo.py
@@ -1,2 +1,8 @@
+def upload_company_logo(company_id: str, logo_url: str):
+    if not company_id:
+        raise ValueError("company_id is required")
+    return {"logo_url": logo_url}
diff --git a/schemas/company.py b/schemas/company.py
@@ -3,2 +3,5 @@
+class CompanyLogoUpload:
+    company_id: str
+    logo_url: str
diff --git a/tests/test_company_logo.py b/tests/test_company_logo.py
@@ -0,0 +1,3 @@
+def test_upload_company_logo_requires_company_id():
+    assert True
"""

    result = build_code_change_feedback(findings, diff_text)

    assert result["summary"]["total_findings"] == 1
    signal = result["signals"][0]
    assert signal["finding_id"] == "G-012"
    assert signal["feedback_label"] == "likely_adopted_by_implementation"
    assert signal["confidence"] >= 0.75
    assert signal["changed_files"] == [
        "api/company_logo.py",
        "schemas/company.py",
        "tests/test_company_logo.py",
    ]
    assert "schema_added" in signal["change_types"]
    assert "validation_added" in signal["change_types"]
    assert "test_added" in signal["change_types"]


def test_code_diff_feedback_keeps_unrelated_changes_low_confidence():
    from review.code_change_feedback import build_code_change_feedback

    findings = [
        {
            "id": "G-020",
            "rule_id": "EV-01",
            "dimension": "workflow",
            "location": "Payment refund state",
            "issue": "Missing refund failure status.",
        }
    ]
    diff_text = """
diff --git a/web/styles/theme.css b/web/styles/theme.css
@@ -1,2 +1,4 @@
+body { color: #111; }
+button { border-radius: 4px; }
"""

    result = build_code_change_feedback(findings, diff_text)

    signal = result["signals"][0]
    assert signal["feedback_label"] == "no_code_change_signal"
    assert signal["confidence"] < 0.45
    assert signal["changed_files"] == []
    assert result["summary"]["likely_adopted"] == 0


def test_code_diff_feedback_understands_chinese_review_dimensions():
    from review.code_change_feedback import build_code_change_feedback

    findings = [
        {
            "id": "G-021",
            "rule_id": "RC-004",
            "dimension": "数据质量",
            "severity": "must",
            "location": "Company logo schema",
            "issue": "Missing logo_url field.",
        }
    ]
    diff_text = """
diff --git a/schemas/company.py b/schemas/company.py
@@ -1,1 +1,4 @@
+class CompanyLogo:
+    company_id: str
+    logo_url: str
"""

    result = build_code_change_feedback(findings, diff_text)

    signal = result["signals"][0]
    assert signal["feedback_label"] == "likely_adopted_by_implementation"
    assert "schema_added" in signal["change_types"]


def test_code_diff_feedback_ignores_analyzer_fixture_changes():
    from review.code_change_feedback import build_code_change_feedback

    findings = [
        {
            "id": "G-022",
            "rule_id": "RC-004",
            "dimension": "数据质量",
            "severity": "must",
            "location": "Company logo schema",
            "issue": "Missing logo_url field.",
        }
    ]
    diff_text = """
diff --git a/tests/test_code_change_feedback.py b/tests/test_code_change_feedback.py
@@ -1,1 +1,4 @@
+def test_fixture_mentions_logo_url():
+    payload = {"logo_url": "https://example.test/logo.png"}
+    assert payload
"""

    result = build_code_change_feedback(findings, diff_text)

    signal = result["signals"][0]
    assert signal["feedback_label"] == "no_code_change_signal"
    assert signal["changed_files"] == []


def test_code_diff_feedback_redacts_sensitive_added_lines():
    from review.code_change_feedback import build_code_change_feedback

    findings = [
        {
            "id": "G-030",
            "rule_id": "RC-009",
            "dimension": "data_contract",
            "location": "API key config",
            "issue": "Add API key validation.",
        }
    ]
    diff_text = """
diff --git a/api/key_config.py b/api/key_config.py
@@ -0,0 +1,2 @@
+OPENAI_API_KEY = "sk-should-not-leak-1234567890"
+validate_api_key(OPENAI_API_KEY)
"""

    result = build_code_change_feedback(findings, diff_text)
    serialized = json.dumps(result, ensure_ascii=False)

    assert "sk-should-not-leak" not in serialized
    assert "[REDACTED" in serialized


def test_code_change_feedback_cli_writes_json(tmp_path):
    from scripts.code_change_feedback import main

    findings_path = tmp_path / "findings.json"
    diff_path = tmp_path / "change.diff"
    output_path = tmp_path / "feedback.json"
    findings_path.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "id": "G-040",
                        "rule_id": "AC-01",
                        "dimension": "acceptance",
                        "location": "Logo upload acceptance",
                        "issue": "Missing acceptance test for logo upload.",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    diff_path.write_text(
        """
diff --git a/tests/test_logo_acceptance.py b/tests/test_logo_acceptance.py
@@ -0,0 +1,2 @@
+def test_logo_upload_acceptance():
+    assert True
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
        ]
    )

    assert code == 0
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["signals"][0]["finding_id"] == "G-040"
    assert payload["signals"][0]["feedback_label"] in {
        "likely_adopted_by_implementation",
        "possible_related_code_change",
    }


def test_code_change_feedback_builds_langfuse_scores_without_raw_code():
    from review.code_change_feedback import build_code_change_feedback_score_payloads

    result = {
        "summary": {
            "total_findings": 2,
            "likely_adopted": 1,
            "possible_related": 1,
            "no_code_change_signal": 0,
            "implementation_signal_rate": 0.75,
        },
        "signals": [
            {
                "finding_id": "G-1",
                "feedback_label": "likely_adopted_by_implementation",
                "confidence": 0.9,
                "evidence": [{"snippets": ["raw code should not be copied"]}],
            }
        ],
    }

    scores = build_code_change_feedback_score_payloads(
        result,
        session_id="code-feedback-suite",
    )

    names = {score["name"] for score in scores}
    assert "pecker.code_change_feedback.implementation_signal_rate" in names
    assert "pecker.code_change_feedback.likely_adopted" in names
    assert all(score["session_id"] == "code-feedback-suite" for score in scores)
    assert all(score["data_type"] == "NUMERIC" for score in scores)
    assert "raw code should not be copied" not in json.dumps(scores, ensure_ascii=False)


def test_code_change_feedback_cli_can_record_langfuse_scores(tmp_path, monkeypatch):
    import scripts.code_change_feedback as script

    calls = []
    monkeypatch.setattr(
        script,
        "record_code_change_feedback_scores",
        lambda result, **kwargs: calls.append((result, kwargs))
        or {"status": "recorded", "scores_sent": 5},
    )
    findings_path = tmp_path / "findings.json"
    diff_path = tmp_path / "change.diff"
    output_path = tmp_path / "feedback.json"
    findings_path.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "id": "G-050",
                        "dimension": "data_contract",
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

    code = script.main(
        [
            "--findings-json",
            str(findings_path),
            "--diff-file",
            str(diff_path),
            "--output-json",
            str(output_path),
            "--record-langfuse",
            "--session-id",
            "code-feedback-run",
        ]
    )

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert code == 0
    assert calls[0][1]["session_id"] == "code-feedback-run"
    assert payload["langfuse_scores"] == {"status": "recorded", "scores_sent": 5}
