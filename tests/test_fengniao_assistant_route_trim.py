from __future__ import annotations

import pytest
from pydantic import ValidationError


@pytest.mark.asyncio
async def test_fengniao_assistant_route_trims_question_before_search(monkeypatch):
    from api.routes import fengniao_assistant

    captured = {}

    def fake_search(question, *, include_fact_layer, max_results):
        captured["question"] = question
        captured["include_fact_layer"] = include_fact_layer
        captured["max_results"] = max_results
        return {
            "answer": "ok",
            "hits": [],
            "searched_roots": [],
            "include_fact_layer": include_fact_layer,
        }

    monkeypatch.setattr(fengniao_assistant, "search_fengniao_evidence", fake_search)

    await fengniao_assistant.ask_fengniao_assistant(
        fengniao_assistant.FengniaoAssistantRequest(
            question="  check source implementation  ",
            include_fact_layer=None,
        ),
        _user={"reviewer": "pm-a", "readonly": False},
    )

    assert captured["question"] == "check source implementation"
    assert captured["include_fact_layer"] is True
    assert captured["max_results"] == 5


def test_fengniao_assistant_request_rejects_blank_question():
    from api.routes.fengniao_assistant import FengniaoAssistantRequest

    with pytest.raises(ValidationError):
        FengniaoAssistantRequest(question="   ")
