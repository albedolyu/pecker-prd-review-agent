from __future__ import annotations

import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from clients.shared import UnifiedResponse


def _advisor_response() -> UnifiedResponse:
    return UnifiedResponse(
        text_blocks=[],
        tool_calls=[
            {
                "id": "call_1",
                "name": "submit_advisor_review",
                "input": {
                    "flagged_as_false_positive": [],
                    "additional_findings": [
                        {
                            "rule_id": "RC-004",
                            "location": "验收标准",
                            "issue": "缺少异常路径",
                            "suggestion": "补充失败场景和兜底文案",
                            "severity": "should",
                            "evidence_type": "B",
                            "evidence_content": "规则要求覆盖异常路径",
                        }
                    ],
                    "conflict_resolutions": [],
                    "confidence": 0.9,
                },
            }
        ],
        stop_reason="tool_use",
        usage={"input_tokens": 10, "output_tokens": 5},
        model="gpt-5.5",
    )


def test_advisor_none_client_uses_route_without_legacy_cli(monkeypatch):
    """Web 热路径传 None 时,苍鹰应直接走 model_router,不能再创建 Claude CLI。"""
    import goshawk_advisor
    import model_router

    calls = []

    def fail_legacy_client():
        raise AssertionError("legacy client should not be constructed")

    def fake_route_call(route_id, **kwargs):
        calls.append((route_id, kwargs))
        return _advisor_response()

    monkeypatch.setattr(goshawk_advisor, "_make_client", fail_legacy_client)
    monkeypatch.setattr(model_router, "route_call", fake_route_call)

    result = goshawk_advisor.advisor_review(
        None,
        "PRD 内容",
        [{"id": "R-001", "issue": "已有发现"}],
        {},
        deadline=time.monotonic() + 20,
    )

    assert calls and calls[0][0] == "advisor.goshawk"
    assert result["verdict"] == "REVIEWED"
    assert result["model_used"] == "gpt-5.5"


@pytest.mark.asyncio
async def test_precheck_uses_route_call_without_legacy_client(tmp_path, monkeypatch):
    """预检也必须走 GPT 路由,不能因为 get_client 回退到 Claude/Anthropic。"""
    import api.routes.review as review_route
    import model_router

    ws = tmp_path / "workspace-demo"
    (ws / "wiki").mkdir(parents=True)
    (ws / "wiki" / "concept-budget.md").write_text("预算规则", encoding="utf-8")

    calls = []

    def fake_route_call(route_id, **kwargs):
        calls.append((route_id, kwargs))
        return UnifiedResponse(
            text_blocks=[
                {
                    "type": "text",
                    "text": '{"strong":["预算规则"],"weak":[],"gaps":["缺少上线范围"]}',
                }
            ],
            tool_calls=[],
            stop_reason="end_turn",
            usage={"input_tokens": 8, "output_tokens": 4},
            model="gpt-5.4",
        )

    monkeypatch.setattr(review_route, "get_workspace_dir", lambda _name: ws)
    monkeypatch.setattr(review_route, "require_workspace_access", lambda _ws, _user: None)
    monkeypatch.setattr(
        review_route,
        "get_client",
        lambda: (_ for _ in ()).throw(AssertionError("legacy client should not be used")),
    )
    monkeypatch.setattr(model_router, "route_call", fake_route_call)

    req = review_route.PrecheckRequest(
        prd_content="这是一个预算评审 PRD",
        raw_materials=[],
        workspace="workspace-demo",
    )
    result = await review_route.precheck(req, project_root=tmp_path, user={"reviewer": "alice"})

    assert calls and calls[0][0] == "precheck.gaps"
    assert "缺少上线范围" in result.gaps
