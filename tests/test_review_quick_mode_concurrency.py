from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class _FakeRequest:
    async def is_disconnected(self) -> bool:
        return False


@pytest.mark.asyncio
async def test_quick_review_uses_async_worker_path(monkeypatch, tmp_path):
    """Quick mode must keep the async worker timeout path.

    The team concurrency stress run exposed that quick mode used
    ``parallel_review_sync`` inside ``run_in_executor``.  That sync path has no
    per-worker timeout, so a stuck gateway request can hang the SSE stream.
    """
    import api.routes.review as review_route
    import parallel_review as parallel_review_mod

    ws = tmp_path / "workspace-sample"
    ws.mkdir()
    (ws / "wiki").mkdir()

    monkeypatch.setenv("PECKER_SIGNATURE_SECRET", "test-signature-secret-32-chars")
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
                    "dimension": "quality",
                    "dimension_name": "质量",
                    "items": [],
                    "usage": {"input_tokens": 0, "output_tokens": 0},
                    "model": "gpt-5.4",
                }
            ],
            "merged_items": [],
            "total_usage": {"input_tokens": 0, "output_tokens": 0},
        }

    def fail_sync_path(*_args, **_kwargs):
        raise AssertionError("quick mode must not call parallel_review_sync")

    monkeypatch.setattr(parallel_review_mod, "parallel_review", fake_parallel_review)
    monkeypatch.setattr(parallel_review_mod, "parallel_review_sync", fail_sync_path)

    req = review_route.ReviewRequest(
        prd_content="这是一个用于 quick 并发回归的 PRD。",
        workspace="workspace-sample",
        prd_name="quick-timeout-regression.md",
        mode="quick",
        wiki_pages={},
    )

    response = await review_route.run_review(
        req,
        _FakeRequest(),
        user={"reviewer": "stress-pm", "readonly": False},
    )

    chunks = []
    async for chunk in response.body_iterator:
        chunks.append(chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk)
    stream = "".join(chunks)

    assert "event: result" in stream
    assert "parallel_review_sync" not in stream
