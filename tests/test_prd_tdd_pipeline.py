from __future__ import annotations

import json
from pathlib import Path


def _review_payload(*, must: int = 0, failed_workers: list[str] | None = None) -> dict:
    items = [
        {
            "id": f"R-{index:03d}",
            "severity": "must",
            "status": "VERIFIED",
            "issue": "blocking gap",
        }
        for index in range(1, must + 1)
    ]
    return {
        "case_label": "privacy compliance",
        "workspace": "C:/ws",
        "prd_files": ["prd.md"],
        "completion": {"status": "complete", "failed_workers": failed_workers or []},
        "verified_items": items,
        "items": items,
        "report_paths": {"json": "review.json"},
        "verification_summary": {"retracted": 0, "reliability": 1.0},
    }


def test_build_verdict_payload_approves_clean_gpt_review(tmp_path):
    from scripts.prd_tdd_pipeline import build_verdict_payload

    verdict = build_verdict_payload(
        _review_payload(),
        prd_id="PRIVACY-COMPLIANCE-CODEX-20260508",
        prd_path=tmp_path / "prd.md",
    )

    assert verdict["verdict"] == "approved"
    assert verdict["agent"] == "pecker gpt direct review"
    assert verdict["items"] == []


def test_build_verdict_payload_requires_revision_for_must_findings(tmp_path):
    from scripts.prd_tdd_pipeline import build_verdict_payload

    verdict = build_verdict_payload(
        _review_payload(must=1),
        prd_id="PRIVACY-COMPLIANCE-CODEX-20260508",
        prd_path=tmp_path / "prd.md",
    )

    assert verdict["verdict"] == "needs_revision"
    assert verdict["must_count"] == 1


def test_run_pipeline_stops_before_zhique_when_pecker_needs_revision(tmp_path):
    from scripts.prd_tdd_pipeline import run_pipeline

    workspace = tmp_path / "workspace"
    prd_dir = workspace / "prd"
    prd_dir.mkdir(parents=True)
    (prd_dir / "prd.md").write_text("# PRD", encoding="utf-8")

    def fake_review_runner(**kwargs):
        return _review_payload(must=1)

    def fail_weave(**kwargs):
        raise AssertionError("Zhique should not run when Pecker requires revision")

    result = run_pipeline(
        workspace=workspace,
        zhique_root=tmp_path / "zhique",
        test_output_root=tmp_path / "test-cases",
        knowledge_root=tmp_path / "knowledge",
        prd_id="PRIVACY-COMPLIANCE-CODEX-20260508",
        review_runner=fake_review_runner,
        weave_runner=fail_weave,
    )

    assert result["ok"] is False
    assert result["pecker"]["verdict"] == "needs_revision"
    assert result["zhique"] is None


def test_run_pipeline_runs_zhique_and_quality_gate_for_approved_prd(tmp_path):
    from scripts.prd_tdd_pipeline import run_pipeline

    workspace = tmp_path / "workspace"
    prd_dir = workspace / "prd"
    prd_dir.mkdir(parents=True)
    (prd_dir / "prd.md").write_text("# PRD", encoding="utf-8")
    output_dir = tmp_path / "test-cases" / "PRIVACY-COMPLIANCE-CODEX-20260508"
    calls = {}

    def fake_review_runner(**kwargs):
        calls["review"] = kwargs
        return _review_payload()

    def fake_weave(**kwargs):
        calls["weave"] = kwargs
        output_dir.mkdir(parents=True)
        return output_dir

    class FakeGate:
        ok = True

        def to_dict(self):
            return {"ok": True, "failures": [], "summary": {"case_count": 3}}

    def fake_quality_gate(output_dir_arg, **kwargs):
        calls["gate"] = {"output_dir": output_dir_arg, **kwargs}
        return FakeGate()

    result = run_pipeline(
        workspace=workspace,
        zhique_root=tmp_path / "zhique",
        test_output_root=tmp_path / "test-cases",
        knowledge_root=tmp_path / "knowledge",
        prd_id="PRIVACY-COMPLIANCE-CODEX-20260508",
        review_runner=fake_review_runner,
        weave_runner=fake_weave,
        quality_gate_checker=fake_quality_gate,
        gateway_factory=lambda pecker_root: "gateway",
    )

    assert result["ok"] is True
    assert result["pecker"]["verdict"] == "approved"
    assert result["zhique"]["output_dir"] == str(output_dir)
    assert result["zhique"]["quality_gate"]["ok"] is True
    assert calls["weave"]["model_gateway"] == "gateway"
    assert calls["weave"]["woodpecker_report_path"].name == "verdict.json"
    assert calls["gate"]["output_dir"] == output_dir

    saved = json.loads((workspace / "output" / "prd-tdd-pipeline" / "pipeline_result.json").read_text(encoding="utf-8"))
    assert saved["ok"] is True


def test_prd_tdd_pipeline_script_is_registered():
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")

    assert 'pecker-prd-tdd-pipeline = "scripts.prd_tdd_pipeline:main"' in pyproject
