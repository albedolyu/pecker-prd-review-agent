from __future__ import annotations

import json
from pathlib import Path


GOLDEN_PATH = (
    Path(__file__).resolve().parents[1]
    / "eval"
    / "golden"
    / "review_assistant_customer_needs.json"
)


def _load_golden() -> dict:
    return json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))


def test_fengniao_evidence_backend_meets_golden_customer_needs(tmp_path, monkeypatch):
    from api.fengniao_evidence import search_fengniao_evidence

    golden = _load_golden()
    cases = golden["backend_evidence_cases"]
    passed = 0

    for case in cases:
        root_map = {
            "wiki": tmp_path / case["id"] / "wiki",
            "knowledge": tmp_path / case["id"] / "knowledge",
            "source": tmp_path / case["id"] / "source",
        }
        for root in root_map.values():
            root.mkdir(parents=True, exist_ok=True)
        for fixture in case["fixture_files"]:
            path = root_map[fixture["root"]] / fixture["path"]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(fixture["content"], encoding="utf-8")

        monkeypatch.setenv("PECKER_FENGNIAO_WIKI_PATH", str(root_map["wiki"]))
        monkeypatch.setenv("PECKER_FENGNIAO_KNOWLEDGE_PATH", str(root_map["knowledge"]))
        monkeypatch.setenv("PECKER_FENGNIAO_SOURCE_ROOTS", str(root_map["source"]))

        result = search_fengniao_evidence(
            case["question"],
            include_fact_layer=case["include_fact_layer"],
            max_results=6,
        )
        layers = {hit["layer"] for hit in result["hits"]}

        for layer in case["expect"].get("layers", []):
            assert layer in layers, f"{case['id']} missing layer {layer}: {result}"
        for layer in case["expect"].get("forbidden_layers", []):
            assert layer not in layers, f"{case['id']} should not include layer {layer}: {result}"
        for phrase in case["expect"].get("must_include", []):
            assert phrase in result["answer"], f"{case['id']} missing phrase {phrase}: {result}"
        passed += 1

    assert passed == len(cases)
