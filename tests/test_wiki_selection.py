"""Wiki context selection tests for deep review prompt optimization."""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _total_chars(pages: dict[str, str]) -> int:
    return sum(len(v) for v in pages.values())


def test_select_wiki_pages_prefers_dimension_and_prd_keyword_matches():
    from review.wiki_selection import select_wiki_pages

    prd = "本次 PRD 涉及 ds_order 表的 refund_count 字段映射和 JOIN 口径。"
    wiki_pages = {
        "模板规范": "PRD 模板和章节结构说明。" * 20,
        "字段映射规范": (
            "---\nauthority: canonical\n---\n"
            "ds_order.refund_count 必须标注 source_table、JOIN 来源和空值降级。"
        ),
        "运营活动说明": "活动文案、弹窗素材和运营排期。" * 20,
    }

    selected, telemetry = select_wiki_pages(
        wiki_pages,
        prd,
        dim_key="data_quality",
        wiki_keywords={"data_quality": ["字段", "映射", "DDL", "JOIN", "数据"]},
        max_chars=220,
        summary_chars=80,
    )

    assert list(selected)[0] == "字段映射规范"
    assert "字段映射规范" in selected
    assert "运营活动说明" not in selected
    assert telemetry["selected_count"] == len(selected)
    assert telemetry["omitted_count"] >= 1


def test_select_wiki_pages_prefers_canonical_when_scores_are_close():
    from review.wiki_selection import select_wiki_pages

    wiki_pages = {
        "字段映射-草稿": "---\nauthority: generated\n---\n字段 映射 JOIN 口径。",
        "字段映射-正式": "---\nauthority: canonical\n---\n字段 映射 JOIN 口径。",
    }

    selected, telemetry = select_wiki_pages(
        wiki_pages,
        "检查字段映射和 JOIN 口径。",
        dim_key="data_quality",
        wiki_keywords={"data_quality": ["字段", "映射", "JOIN"]},
        max_chars=200,
        summary_chars=80,
    )

    assert list(selected)[0] == "字段映射-正式"
    first = telemetry["pages"][0]
    assert first["title"] == "字段映射-正式"
    assert first["authority"] == "canonical"


def test_select_wiki_pages_summarizes_lower_priority_pages_within_budget():
    from review.wiki_selection import select_wiki_pages

    high = "字段映射 ds_order refund_count JOIN。" + ("A" * 140)
    medium = "字段口径 refund_count。" + ("B" * 180)
    low = "运营排期。" + ("C" * 200)
    selected, telemetry = select_wiki_pages(
        {"高相关": high, "中相关": medium, "低相关": low},
        "refund_count 字段映射。",
        dim_key="data_quality",
        wiki_keywords={"data_quality": ["字段", "映射", "JOIN"]},
        max_chars=300,
        summary_chars=45,
    )

    assert "高相关" in selected
    assert "中相关" in selected
    assert "低相关" not in selected
    assert "(... 余" in selected["中相关"]
    assert _total_chars(selected) <= 300
    assert any(p["mode"] == "summary" for p in telemetry["pages"])


def test_build_worker_messages_uses_wiki_selector(monkeypatch):
    from review.prompting import _build_worker_messages

    monkeypatch.setattr("agent_config.MAX_WIKI_CHARS", 240)

    messages = _build_worker_messages(
        "PRD 涉及 refund_count 字段映射和 JOIN 口径。",
        {
            "字段映射规范": "---\nauthority: canonical\n---\nrefund_count 字段 JOIN。" + ("A" * 80),
            "运营活动说明": "活动文案、弹窗素材和运营排期。" + ("B" * 300),
        },
        dim_key="data_quality",
        wiki_keywords={"data_quality": ["字段", "映射", "JOIN"]},
    )

    content = messages[0]["content"]
    assert "### 字段映射规范" in content
    assert "### 运营活动说明" not in content


def test_build_worker_messages_injects_prd_matched_kg_entity_anchors(tmp_path):
    from review.prompting import _build_worker_messages

    workspace = tmp_path / "workspace"
    kg_dir = workspace / "wiki" / "_kg"
    kg_dir.mkdir(parents=True)
    entities = [
        {
            "id": "e_abc12345",
            "title": "Field mapping standard",
            "type": "spec_doc",
            "description": "Requires PRDs to map UI fields to source_table and source_column.",
            "aliases": ["field source contract"],
            "source_pages": ["concepts/field-mapping.md"],
        },
        {
            "id": "e_def67890",
            "title": "Irrelevant operations note",
            "type": "note",
            "description": "Unrelated release process guidance.",
            "aliases": ["release calendar"],
            "source_pages": ["ops/release-calendar.md"],
        },
    ]
    (kg_dir / "entities.json").write_text(
        json.dumps(entities, ensure_ascii=False),
        encoding="utf-8",
    )
    (kg_dir / "relations.json").write_text("[]", encoding="utf-8")

    messages = _build_worker_messages(
        "This PRD must follow the field source contract for all DDL columns.",
        {},
        dim_key="data_quality",
        wiki_path=str(workspace / "wiki"),
    )

    content = messages[0]["content"]
    assert "## Wiki entity anchors matched from PRD" in content
    assert "[[entity:e_abc12345]]" in content
    assert "Field mapping standard" in content
    assert "concepts/field-mapping.md" in content
    assert "e_def67890" not in content


def test_build_worker_messages_injects_kg_entity_source_authority(tmp_path):
    from review.prompting import _build_worker_messages

    workspace = tmp_path / "workspace"
    kg_dir = workspace / "wiki" / "_kg"
    concepts_dir = workspace / "wiki" / "concepts"
    kg_dir.mkdir(parents=True)
    concepts_dir.mkdir(parents=True)
    (concepts_dir / "field-mapping.md").write_text(
        "---\nauthority: canonical\nsources: 2\n---\nField mapping source of truth.",
        encoding="utf-8",
    )
    entities = [
        {
            "id": "e_abc12345",
            "title": "Field mapping standard",
            "type": "spec_doc",
            "description": "Requires PRDs to map UI fields to source_table and source_column.",
            "aliases": ["field source contract"],
            "source_pages": ["concepts/field-mapping.md"],
        }
    ]
    (kg_dir / "entities.json").write_text(
        json.dumps(entities, ensure_ascii=False),
        encoding="utf-8",
    )
    (kg_dir / "relations.json").write_text("[]", encoding="utf-8")

    messages = _build_worker_messages(
        "This PRD must follow the field source contract for all DDL columns.",
        {},
        dim_key="data_quality",
        wiki_path=str(workspace / "wiki"),
    )

    content = messages[0]["content"]
    assert "authority=canonical" in content


def test_build_worker_messages_emits_selection_telemetry(monkeypatch):
    from review.prompting import _build_worker_messages

    monkeypatch.setattr("agent_config.MAX_WIKI_CHARS", 180)
    seen = []

    _build_worker_messages(
        "PRD 涉及 refund_count 字段映射。",
        {
            "字段映射规范": "refund_count 字段映射 JOIN。" + ("A" * 80),
            "运营活动说明": "运营排期。" + ("B" * 300),
        },
        dim_key="data_quality",
        wiki_keywords={"data_quality": ["字段", "映射", "JOIN"]},
        on_wiki_selection=seen.append,
    )

    assert len(seen) == 1
    assert seen[0]["selected_count"] == 1
    assert seen[0]["omitted_count"] == 1
    assert seen[0]["total_chars_after"] < seen[0]["total_chars_before"]


def test_build_worker_messages_uses_smaller_structure_wiki_budget(monkeypatch):
    from review.prompting import _build_worker_messages

    monkeypatch.setattr("agent_config.MAX_WIKI_CHARS", 1000)
    seen = []
    wiki_pages = {
        f"schema-flow-{i}": "schema flow requirement " + ("A" * 360)
        for i in range(5)
    }

    _build_worker_messages(
        "schema flow requirement",
        wiki_pages,
        dim_key="structure",
        wiki_keywords={"structure": ["schema", "flow", "requirement"]},
        on_wiki_selection=seen.append,
    )

    assert len(seen) == 1
    assert seen[0]["total_chars_after"] <= 450


def test_quality_wiki_budget_is_capped_below_global_default():
    from review.prompting import _wiki_budget_for_dim

    assert _wiki_budget_for_dim("quality", 1000) == 500


def test_wiki_title_aliases_normalize_directory_spaces_and_extension():
    from review.wiki_selection import wiki_title_aliases

    aliases = wiki_title_aliases("api/API 总览.md")

    assert "api总览" in aliases
    assert "apiapi总览" in aliases


def test_worker_core_exposes_wiki_selection_in_telemetry(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from parallel_review import _worker_core

    fake_dim = {
        "name": "数据质量",
        "model": "sonnet",
        "effort": "medium",
        "checklist": [{"rule_id": "V-02"}],
        "rules": "V-02 格式规范性",
        "codename": "测试鸟",
    }
    monkeypatch.setattr(
        "review.worker.get_review_dimensions",
        lambda workspace=None: {"data_quality": fake_dim},
    )
    monkeypatch.setattr(
        "review.worker.get_wiki_keywords",
        lambda workspace=None: {"data_quality": ["字段", "映射", "JOIN"]},
    )
    monkeypatch.setattr(
        "review.worker._build_worker_system",
        lambda *a, **kw: "dynamic system prompt",
    )
    fake_cm = MagicMock()
    monkeypatch.setattr("review.worker.PromptCacheMonitor", lambda: fake_cm, raising=False)
    monkeypatch.setattr("api_adapter.compute_call_cost_usd", lambda model, usage: 0.001)
    monkeypatch.setattr("agent_config.MAX_WIKI_CHARS", 180)

    response = SimpleNamespace(
        content=[
            SimpleNamespace(
                type="tool_use",
                name="submit_review_items",
                id="toolu_test",
                input={
                    "items": [
                        {
                            "id": "R-001",
                            "rule_id": "V-02",
                            "location": "1.1",
                            "issue": "foo",
                            "suggestion": "bar",
                            "severity": "should",
                            "evidence_type": "B",
                            "evidence_content": "V-02",
                        }
                    ]
                },
            )
        ],
        usage={
            "input_tokens": 100,
            "output_tokens": 50,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
        },
    )
    client = MagicMock()
    client.create.return_value = response

    result = _worker_core(
        client=client,
        dim_key="data_quality",
        prd_content="PRD 涉及 refund_count 字段映射。",
        wiki_pages={
            "字段映射规范": "refund_count 字段映射 JOIN。" + ("A" * 80),
            "运营活动说明": "运营排期。" + ("B" * 300),
        },
        model_tiers={"sonnet": "s-m"},
    )

    wiki_selection = result["telemetry"]["wiki_selection"]
    assert wiki_selection["selected_count"] == 1
    assert wiki_selection["omitted_count"] == 1
    assert wiki_selection["total_chars_after"] < wiki_selection["total_chars_before"]
