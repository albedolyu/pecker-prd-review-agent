from __future__ import annotations

from pathlib import Path


def test_endpoint_check_ignores_experiment_and_future_design_docs(monkeypatch, tmp_path):
    from scripts import doc_coherence

    docs = tmp_path / "docs"
    docs.mkdir()
    experiment = docs / "full_prd_endpoint_2026_04_28.md"
    experiment.write_text("GET `/api/v1/labour-arbitration/detail`\n", encoding="utf-8")
    future_design = docs / "review-funnel-schema.md"
    future_design.write_text("Future dashboard: `/api/dashboard/funnel?workspace=X&last=N`\n", encoding="utf-8")
    product_doc = docs / "README.md"
    product_doc.write_text("Real API doc: `/api/missing`\n", encoding="utf-8")

    monkeypatch.setattr(doc_coherence, "_doc_files", lambda: [experiment, future_design, product_doc])
    monkeypatch.setattr(doc_coherence, "_collect_route_paths", lambda: {"/api/real"})
    monkeypatch.setattr(doc_coherence, "PROJECT_ROOT", tmp_path)

    findings = doc_coherence.check_endpoints()

    assert [f.where for f in findings] == ["docs/README.md"]
    assert "/api/missing" in findings[0].message


def test_file_path_check_ignores_research_and_template_placeholders(monkeypatch, tmp_path):
    from scripts import doc_coherence

    docs = tmp_path / "docs"
    docs.mkdir()
    research = docs / "research_ai_coding_upstream_2026_04_27.md"
    research.write_text("Upstream reference: `core/router.py`\n", encoding="utf-8")
    template_doc = docs / "sprint-real-prd-calibration-evidence-governance.md"
    template_doc.write_text(
        "\n".join(
            [
                "Template: `docs/calibration-report-YYYY-MM-DD.md`",
                "Memory example: `memory/xxx.md`",
                "Future script: `scripts/reject_reason_report.py`",
            ]
        ),
        encoding="utf-8",
    )
    product_doc = docs / "README.md"
    product_doc.write_text("Real path: `web/lib/missing.ts`\n", encoding="utf-8")

    monkeypatch.setattr(doc_coherence, "_doc_files", lambda: [research, template_doc, product_doc])
    monkeypatch.setattr(doc_coherence, "PROJECT_ROOT", tmp_path)

    findings = doc_coherence.check_file_paths()

    assert [f.where for f in findings] == ["docs/README.md"]
    assert "web/lib/missing.ts" in findings[0].message
