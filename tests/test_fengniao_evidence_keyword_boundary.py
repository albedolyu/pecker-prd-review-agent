from __future__ import annotations


def test_infer_include_fact_layer_ignores_english_keyword_substrings():
    from api.fengniao_evidence import infer_include_fact_layer

    assert infer_include_fact_layer("How should PMs compare capital budget tradeoffs?") is False
