from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_precheck_uses_enriched_figma_materials(monkeypatch, tmp_path):
    from api.routes import review
    from api.routes.review import PrecheckRequest

    workspace = tmp_path / "workspace-alpha"
    (workspace / "wiki").mkdir(parents=True)
    review._wiki_scan_cache.clear()

    captured_raw_materials = []

    monkeypatch.setattr(review, "get_workspace_dir", lambda _workspace: workspace)
    monkeypatch.setattr(review, "require_workspace_access", lambda _ws, _user: None)
    monkeypatch.setattr(
        review,
        "_scan_wiki_for_prd",
        lambda _prd_content, _wiki_path: {"strong": [], "weak": [], "gaps": [], "wiki_pages": {}},
    )
    monkeypatch.setattr(
        review,
        "enrich_figma_raw_materials",
        lambda raw: [*raw, "[补充材料: Figma 解析]\n可读文本:\n- 确认并导出报告"],
    )

    def fake_precheck_call(req):
        captured_raw_materials.extend(req.raw_materials)

        class FakeResponse:
            content = []
            model = "fake"
            usage = {}

        return {"strong": [], "weak": [], "gaps": []}, FakeResponse()

    monkeypatch.setattr(review, "_call_precheck_gaps", fake_precheck_call)

    await review.precheck(
        PrecheckRequest(
            prd_content="# Demo",
            raw_materials=[
                "[补充材料: Figma]\n链接: https://www.figma.com/design/abc123/Product?node-id=12-34"
            ],
            workspace="workspace-alpha",
        ),
        project_root=tmp_path,
        user={"reviewer": "pm-a"},
    )

    assert any("确认并导出报告" in material for material in captured_raw_materials)


@pytest.mark.asyncio
async def test_non_stream_review_job_pipeline_uses_enriched_figma_materials(monkeypatch, tmp_path):
    from api.review_jobs import RecordingReviewProgressEmitter, ReviewJob
    from api.routes import review_jobs
    from api.routes.review import ReviewRequest

    captured = {}

    monkeypatch.setenv("PECKER_REVIEW_JOB_PIPELINE", "legacy")
    monkeypatch.setattr(
        review_jobs,
        "enrich_figma_raw_materials",
        lambda raw: [*raw, "[补充材料: Figma 解析]\n可读文本:\n- 最后一步确认"],
    )

    async def fake_parallel_review(_client, enhanced_prd, *_args, **_kwargs):
        captured["enhanced_prd"] = enhanced_prd
        return {"workers": [], "merged_items": [], "total_usage": {}}

    class FakeReviewResult:
        def __init__(self, payload):
            self._payload = payload

        def model_dump(self):
            return self._payload

    monkeypatch.setattr(review_jobs, "_parallel_review_for_job", fake_parallel_review)
    monkeypatch.setattr(review_jobs, "_persist_completed_review_draft", lambda **_kwargs: None)
    monkeypatch.setattr(review_jobs, "record_review_cost", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        review_jobs.ReviewResult,
        "create",
        staticmethod(lambda **kwargs: FakeReviewResult({"review_id": "rev_figma", **kwargs})),
    )

    job = ReviewJob(
        job_id="job_figma",
        owner="pm-a",
        workspace="workspace-alpha",
        prd_name="demo.md",
        mode="quick",
    )
    emitter = RecordingReviewProgressEmitter(job)

    await review_jobs._run_review_job_pipeline(
        req=ReviewRequest(
            prd_content="# Demo",
            raw_materials=[
                "[补充材料: Figma]\n链接: https://www.figma.com/design/abc123/Product?node-id=12-34"
            ],
            workspace="workspace-alpha",
            prd_name="demo.md",
            reviewer="pm-a",
            mode="quick",
        ),
        user={"reviewer": "pm-a"},
        ws_abs_path=str(tmp_path / "workspace-alpha"),
        emitter=emitter,
        project_root=tmp_path,
    )

    assert "最后一步确认" in captured["enhanced_prd"]
