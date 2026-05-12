from __future__ import annotations


def test_detects_schema_heavy_prd_and_maps_dimension_focus():
    from review.scenario_detection import detect_review_scenarios

    scenarios = detect_review_scenarios(
        """
        This PRD adds a field mapping table for ds_risk_court_mediation.
        DDL: CREATE TABLE ds_risk_court_mediation (...).
        The display field publish_date joins company_base by entid.
        """
    )

    schema = scenarios[0]
    assert schema["id"] == "data_schema"
    assert schema["dimensions"]["data_quality"]["priority_rules"] == [
        "RC-009",
        "RC-010",
        "FN-01",
    ]
    assert "DDL" in schema["matched_terms"]


def test_detects_figma_prototype_prd_and_maps_dimension_focus():
    from review.scenario_detection import detect_review_scenarios

    scenarios = detect_review_scenarios(
        """
        Prototype: https://www.figma.com/design/abc123/Foo?node-id=1-2
        The PRD must align the empty, loading, and permission states with the screen.
        """
    )

    figma = scenarios[0]
    assert figma["id"] == "figma_prototype"
    assert figma["dimensions"]["structure"]["priority_rules"] == ["FN-09", "V-06"]
    assert figma["dimensions"]["ai_coding"]["priority_rules"] == ["RC-005", "RC-006"]


def test_build_worker_messages_injects_only_current_dimension_scenario_focus():
    from review.prompting import _build_worker_messages

    messages = _build_worker_messages(
        """
        DDL: CREATE TABLE ds_risk_court_mediation (...).
        Field mapping: publish_date -> publish_date, JOIN by entid.
        Figma: https://www.figma.com/design/abc123/Foo?node-id=1-2
        """,
        {},
        dim_key="data_quality",
    )

    content = messages[0]["content"]
    assert "## Scenario-specific checklist focus" in content
    assert "data_schema" in content
    assert "RC-009, RC-010, FN-01" in content
    assert "RC-005" not in content
