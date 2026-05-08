from __future__ import annotations

import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from clients.shared import UnifiedResponse


@pytest.mark.asyncio
async def test_precheck_llm_timeout_falls_back_to_local_scan(tmp_path, monkeypatch):
    import api.routes.review as review_route
    import model_router

    ws = tmp_path / "workspace-precheck-timeout"
    (ws / "wiki").mkdir(parents=True)
    (ws / "wiki" / "concept-budget.md").write_text("预算 规则 PRD", encoding="utf-8")

    def slow_route_call(route_id, **kwargs):  # noqa: ARG001
        time.sleep(0.2)
        return UnifiedResponse(
            text_blocks=[
                {
                    "type": "text",
                    "text": '{"strong":[],"weak":[],"gaps":["should not surface after timeout"]}',
                }
            ],
            tool_calls=[],
            stop_reason="end_turn",
            usage={"input_tokens": 8, "output_tokens": 4},
            model="gpt-5.5",
        )

    monkeypatch.setenv("PECKER_PRECHECK_TIMEOUT", "0.01")
    monkeypatch.setattr(review_route, "get_workspace_dir", lambda _name: ws)
    monkeypatch.setattr(review_route, "require_workspace_access", lambda _ws, _user: None)
    monkeypatch.setattr(model_router, "route_call", slow_route_call)

    req = review_route.PrecheckRequest(
        prd_content="预算 PRD",
        raw_materials=[],
        workspace="workspace-precheck-timeout",
    )
    result = await review_route.precheck(req, project_root=tmp_path, user={"reviewer": "alice"})

    assert result.gaps == []
