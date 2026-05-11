from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class _FakeRequest:
    async def is_disconnected(self) -> bool:
        return False


@pytest.mark.asyncio
async def test_standard_review_can_emit_preliminary_result_before_goshawk_patch(
    monkeypatch,
    tmp_path,
):
    import api.routes.review as review_route
    import goshawk_advisor
    import parallel_review as parallel_review_mod
    import review.evidence_verify as evidence_verify

    ws = tmp_path / "workspace-alpha"
    ws.mkdir()
    (ws / "wiki").mkdir()

    monkeypatch.setenv("PECKER_SIGNATURE_SECRET", "test-signature-secret-32-chars")
    monkeypatch.setenv("PECKER_ENABLE_ASYNC_GOSHAWK_PATCHES", "1")
    monkeypatch.setattr(review_route, "get_project_root", lambda: tmp_path)
    monkeypatch.setattr(review_route, "get_workspace_dir", lambda _name: ws)
    monkeypatch.setattr(review_route, "require_workspace_access", lambda _ws, _user: None)
    monkeypatch.setattr(review_route, "check_budget", lambda *_args, **_kwargs: {"enabled": True})
    monkeypatch.setattr(review_route, "record_review_cost", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(review_route, "budget_status_snapshot", lambda *_args, **_kwargs: {})

    async def fake_parallel_review(*_args, **_kwargs):
        return {
            "workers": [
                {
                    "dimension": "business",
                    "dimension_name": "业务",
                    "items": [
                        {
                            "id": "I-1",
                            "dimension": "业务",
                            "severity": "must",
                            "location": "第一章",
                            "problem": "缺少验收标准。",
                            "suggestion": "补充可验证的验收标准。",
                        }
                    ],
                    "usage": {"input_tokens": 10, "output_tokens": 5},
                    "cost_usd": 0.01,
                }
            ],
            "merged_items": [
                {
                    "id": "I-1",
                    "dimension": "业务",
                    "severity": "must",
                    "location": "第一章",
                    "problem": "缺少验收标准。",
                    "suggestion": "补充可验证的验收标准。",
                }
            ],
            "total_usage": {"input_tokens": 10, "output_tokens": 5},
        }

    async def fake_advisor_review(*_args, **_kwargs):
        return {
            "flagged_as_false_positive": [],
            "additional_findings": [
                {
                    "id": "G-1",
                    "dimension": "风险",
                    "severity": "should",
                    "location": "第二章",
                    "problem": "缺少异常状态说明。",
                    "suggestion": "补充失败和空状态处理。",
                }
            ],
            "verdict": "REVIEWED",
            "confidence": 0.92,
        }

    def fake_apply_advisor_result(items, goshawk_result, **_kwargs):
        return list(items) + list(goshawk_result.get("additional_findings", []))

    monkeypatch.setattr(parallel_review_mod, "parallel_review", fake_parallel_review)
    monkeypatch.setattr(evidence_verify, "verify_evidence", lambda items, *_args, **_kwargs: items)
    monkeypatch.setattr(
        evidence_verify,
        "summarize_verification",
        lambda verified: {"total": len(verified), "retracted": 0, "caveat": 0},
    )
    monkeypatch.setattr(goshawk_advisor, "advisor_review_default_async", fake_advisor_review)
    monkeypatch.setattr(goshawk_advisor, "apply_advisor_result", fake_apply_advisor_result)

    req = review_route.ReviewRequest(
        prd_content="这是一个标准评审 PRD。",
        workspace="workspace-alpha",
        prd_name="async-goshawk.md",
        mode="standard",
        wiki_pages={},
    )

    response = await review_route.run_review(
        req,
        _FakeRequest(),
        user={"reviewer": "pm-a", "readonly": False},
    )

    chunks = []
    async for chunk in response.body_iterator:
        chunks.append(chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk)
    stream = "".join(chunks)

    assert "event: preliminary_result" in stream
    assert "event: goshawk_patch" in stream
    assert stream.index("event: preliminary_result") < stream.index("event: final_reviewer_started")
    assert stream.index("event: goshawk_patch") < stream.index("event: result")
    assert '"goshawk_status": "pending"' in stream
    assert '"goshawk_status": "completed"' in stream
    assert "G-1" in stream
