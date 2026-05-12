from __future__ import annotations


def test_enrich_schema_raw_materials_summarizes_ddl_tables_and_columns():
    from api.schema_context import enrich_schema_raw_materials

    raw = """
    [Supplemental material: DDL]
    CREATE TABLE enterprise_risk (
      id BIGINT PRIMARY KEY,
      company_id BIGINT NOT NULL,
      penalty_date DATE,
      risk_type VARCHAR(32)
    );
    """

    enriched = enrich_schema_raw_materials([raw])

    assert enriched[0] == raw
    assert len(enriched) == 2
    summary = enriched[1]
    assert "[Supplemental material: Schema analysis]" in summary
    assert "enterprise_risk" in summary
    assert "company_id" in summary
    assert "penalty_date" in summary
    assert "risk_type" in summary
    assert "CREATE TABLE" not in summary


def test_enrich_schema_raw_materials_is_idempotent():
    from api.schema_context import enrich_schema_raw_materials

    raw = "CREATE TABLE company_profile (id BIGINT, name VARCHAR(128));"
    once = enrich_schema_raw_materials([raw])
    twice = enrich_schema_raw_materials(once)

    assert twice == once


def test_existing_raw_material_enrichment_includes_schema_summary():
    from api.figma_context import enrich_figma_raw_materials

    enriched = enrich_figma_raw_materials(
        ["CREATE TABLE favorite_company (id BIGINT, company_id BIGINT, remind_at TIMESTAMP);"]
    )

    assert any("[Supplemental material: Schema analysis]" in item for item in enriched)
    assert any("favorite_company" in item and "remind_at" in item for item in enriched)


def test_enrich_schema_raw_materials_summarizes_json_schema_properties():
    from api.schema_context import enrich_schema_raw_materials

    raw = """
    {
      "title": "EnterpriseRiskFilter",
      "type": "object",
      "properties": {
        "company_id": {"type": "integer"},
        "risk_type": {"type": "string"},
        "penalty_date": {"type": "string", "format": "date"}
      },
      "required": ["company_id"]
    }
    """

    enriched = enrich_schema_raw_materials([raw])

    assert len(enriched) == 2
    summary = enriched[1]
    assert "[Supplemental material: Schema analysis]" in summary
    assert "JSON Schema" in summary
    assert "EnterpriseRiskFilter" in summary
    assert "company_id" in summary
    assert "risk_type" in summary
    assert "penalty_date" in summary
