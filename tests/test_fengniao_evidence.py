from __future__ import annotations

import pytest


def test_search_fengniao_evidence_reads_wiki_knowledge_and_fact_layer(tmp_path, monkeypatch):
    from api.fengniao_evidence import search_fengniao_evidence

    wiki = tmp_path / "wiki"
    knowledge = tmp_path / "fengniao-knowledge"
    source = tmp_path / "source" / "riskbird-mobile-vue3"

    (wiki / "modules").mkdir(parents=True)
    (knowledge / "guidelines").mkdir(parents=True)
    (source / "src" / "views").mkdir(parents=True)

    (wiki / "modules" / "company-detail.md").write_text(
        "# 企业详情\n股权结构页面来自企业详情模块，字段需要以事实层接口为准。\n",
        encoding="utf-8",
    )
    (knowledge / "guidelines" / "GL-001.md").write_text(
        "# PRD 证据规则\n评审风鸟需求时，结论需要区分知识库解释和原始事实层。\n",
        encoding="utf-8",
    )
    (source / "src" / "views" / "ShareholderPanel.vue").write_text(
        "<script setup>\nconst fields = ['股权结构', '认缴金额', '持股比例']\n</script>\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("PECKER_FENGNIAO_WIKI_PATH", str(wiki))
    monkeypatch.setenv("PECKER_FENGNIAO_KNOWLEDGE_PATH", str(knowledge))
    monkeypatch.setenv("PECKER_FENGNIAO_SOURCE_ROOTS", str(source))

    result = search_fengniao_evidence(
        "风鸟企业详情股权结构字段，查一下原始事实层源码依据",
        include_fact_layer=True,
        max_results=6,
    )

    layers = {hit["layer"] for hit in result["hits"]}
    assert {"wiki", "knowledge", "fact"}.issubset(layers)
    assert result["include_fact_layer"] is True
    assert "事实层" in result["answer"]
    assert "ShareholderPanel.vue" in result["answer"]
    assert any(hit["line"] >= 1 for hit in result["hits"])


def test_search_fengniao_evidence_omits_fact_layer_until_requested(tmp_path, monkeypatch):
    from api.fengniao_evidence import search_fengniao_evidence

    wiki = tmp_path / "wiki"
    source = tmp_path / "source"
    wiki.mkdir()
    source.mkdir()
    (wiki / "entry.md").write_text("风鸟企业详情支持股权结构说明。\n", encoding="utf-8")
    (source / "CompanyDetail.vue").write_text("股权结构事实字段\n", encoding="utf-8")

    monkeypatch.setenv("PECKER_FENGNIAO_WIKI_PATH", str(wiki))
    monkeypatch.delenv("PECKER_FENGNIAO_KNOWLEDGE_PATH", raising=False)
    monkeypatch.setenv("PECKER_FENGNIAO_SOURCE_ROOTS", str(source))

    result = search_fengniao_evidence("风鸟企业详情股权结构怎么理解", include_fact_layer=False)

    assert result["include_fact_layer"] is False
    assert {hit["layer"] for hit in result["hits"]} == {"wiki"}


def test_search_fengniao_evidence_redacts_configured_root_paths(tmp_path, monkeypatch):
    from api.fengniao_evidence import search_fengniao_evidence

    secret_root = tmp_path / "openai_api_key=secret-root-value" / "wiki"
    secret_root.mkdir(parents=True)
    (secret_root / "entry.md").write_text("company shareholder evidence\n", encoding="utf-8")

    monkeypatch.setenv("PECKER_FENGNIAO_WIKI_PATH", str(secret_root))
    monkeypatch.delenv("PECKER_FENGNIAO_KNOWLEDGE_PATH", raising=False)
    monkeypatch.delenv("PECKER_FENGNIAO_SOURCE_ROOTS", raising=False)

    result = search_fengniao_evidence("company shareholder evidence")

    serialized_paths = " ".join(root["path"] for root in result["searched_roots"])
    assert "secret-root-value" not in serialized_paths
    assert "openai_api_key=[REDACTED_SECRET]" in serialized_paths


def test_search_fengniao_evidence_redacts_hit_display_paths(tmp_path, monkeypatch):
    from api.fengniao_evidence import search_fengniao_evidence

    wiki = tmp_path / "wiki"
    secret_dir = wiki / "api_key=secret-path-value"
    secret_dir.mkdir(parents=True)
    (secret_dir / "entry.md").write_text("company shareholder evidence\n", encoding="utf-8")

    monkeypatch.setenv("PECKER_FENGNIAO_WIKI_PATH", str(wiki))
    monkeypatch.delenv("PECKER_FENGNIAO_KNOWLEDGE_PATH", raising=False)
    monkeypatch.delenv("PECKER_FENGNIAO_SOURCE_ROOTS", raising=False)

    result = search_fengniao_evidence("company shareholder evidence")

    serialized = result["answer"] + " " + " ".join(hit["path"] for hit in result["hits"])
    assert "secret-path-value" not in serialized
    assert "api_key=[REDACTED_SECRET]" in serialized


def test_search_fengniao_evidence_caps_direct_max_results(tmp_path, monkeypatch):
    from api.fengniao_evidence import search_fengniao_evidence

    wiki = tmp_path / "wiki"
    wiki.mkdir()
    for index in range(12):
        (wiki / f"entry-{index}.md").write_text(
            "company shareholder evidence\n",
            encoding="utf-8",
        )

    monkeypatch.setenv("PECKER_FENGNIAO_WIKI_PATH", str(wiki))
    monkeypatch.delenv("PECKER_FENGNIAO_KNOWLEDGE_PATH", raising=False)
    monkeypatch.delenv("PECKER_FENGNIAO_SOURCE_ROOTS", raising=False)

    result = search_fengniao_evidence("company shareholder evidence", max_results=99)

    assert len(result["hits"]) == 8


def test_infer_include_fact_layer_from_question():
    from api.fengniao_evidence import infer_include_fact_layer

    assert infer_include_fact_layer("帮我查原始事实层字段") is True
    assert infer_include_fact_layer("这个页面源码里怎么实现") is True
    assert infer_include_fact_layer("风鸟知识库里怎么说") is False


@pytest.mark.asyncio
async def test_fengniao_assistant_route_infers_fact_layer(monkeypatch):
    from api.routes import fengniao_assistant

    captured = {}

    def fake_search(question, *, include_fact_layer, max_results):
        captured["question"] = question
        captured["include_fact_layer"] = include_fact_layer
        captured["max_results"] = max_results
        return {
            "answer": "查到事实层依据",
            "hits": [{"layer": "fact", "path": "src/foo.ts", "line": 1, "snippet": "字段"}],
            "searched_roots": [],
            "include_fact_layer": include_fact_layer,
        }

    monkeypatch.setattr(fengniao_assistant, "search_fengniao_evidence", fake_search)

    response = await fengniao_assistant.ask_fengniao_assistant(
        fengniao_assistant.FengniaoAssistantRequest(question="查一下原始事实层字段"),
        _user={"reviewer": "pm-a", "readonly": False},
    )

    assert captured["question"] == "查一下原始事实层字段"
    assert captured["include_fact_layer"] is True
    assert captured["max_results"] == 5
    assert response.answer == "查到事实层依据"
