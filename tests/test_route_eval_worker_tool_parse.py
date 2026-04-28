from __future__ import annotations


def test_worker_pattern_extracts_submit_review_items_tool(monkeypatch, tmp_path):
    from clients.shared import UnifiedResponse
    from eval.route_eval import runner
    import model_router

    prd = tmp_path / "sample.md"
    prd.write_text("# PRD\n\nNeed complete field mapping.", encoding="utf-8")

    def fake_route_call(*_args, **_kwargs):
        return UnifiedResponse(
            text_blocks=[],
            tool_calls=[
                {
                    "id": "toolu_test",
                    "name": "submit_review_items",
                    "input": {
                        "dimension": "compliance",
                        "items": [
                            {
                                "rule_id": "V-04",
                                "location": "2.1",
                                "issue": "field mapping missing",
                                "suggestion": "add mapping table",
                                "severity": "must",
                                "evidence_type": "B",
                                "evidence_content": "checklist",
                            }
                        ],
                    },
                }
            ],
            stop_reason="tool_use",
            usage={"input_tokens": 10, "output_tokens": 20},
            model="sonnet",
        )

    monkeypatch.setattr(model_router, "route_call", fake_route_call)

    resp, error_type, fallback = runner._call_worker_pattern(
        "worker.compliance",
        "sonnet",
        [{"prd_path": str(prd), "workspace": "workspace-test"}],
        max_cases=1,
    )

    assert error_type is None
    assert fallback is False
    assert len(resp.items) == 1
    assert resp.items[0]["issue"] == "field mapping missing"
    assert resp.items[0]["dimension"] == "compliance"
    assert resp.items[0]["workspace"] == "workspace-test"
