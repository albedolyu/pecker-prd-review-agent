"""Lightweight PRD scenario detection for dynamic checklist focus.

The detector is intentionally deterministic and local-only. It does not decide
review results; it only gives workers a small "look here first" hint when a PRD
obviously contains schema/DDL or prototype/Figma signals.
"""

from __future__ import annotations

import re
from typing import Any


_SCENARIO_DEFS: tuple[dict[str, Any], ...] = (
    {
        "id": "data_schema",
        "label": "Data schema / DDL handoff",
        "terms": (
            "DDL",
            "CREATE TABLE",
            "schema",
            "field mapping",
            "JOIN",
            "source_table_",
            "NOT NULL",
            "index",
            "字段",
            "字段映射",
            "物理表",
            "数据表",
            "表结构",
        ),
        "dimensions": {
            "data_quality": {
                "priority_rules": ["RC-009", "RC-010"],
                "instruction": (
                    "Inspect table names, field names, types, null/default "
                    "rules, indexes, JOIN sources, and source table filters before "
                    "generic wording issues."
                ),
            },
            "ai_coding": {
                "priority_rules": ["RC-008", "RC-013"],
                "instruction": (
                    "Check whether the implementation handoff traces fields "
                    "from UI/API input to WHERE/JOIN and source schema."
                ),
            },
            "quality": {
                "priority_rules": ["V-07"],
                "instruction": (
                    "Cross-check whether field, sort, filter, and enum claims "
                    "conflict with the stated data source."
                ),
            },
        },
    },
    {
        "id": "figma_prototype",
        "label": "Figma / prototype handoff",
        "terms": (
            "figma.com/design",
            "figma.com/file",
            "node-id=",
            "Figma",
            "prototype",
            "wireframe",
            "screen state",
            "原型",
            "交互稿",
            "页面状态",
            "设计稿",
        ),
        "dimensions": {
            "structure": {
                "priority_rules": ["V-06"],
                "instruction": (
                    "Check whether mobile/web alignment, page scope, states, "
                    "and acceptance sections are explicitly traceable."
                ),
            },
            "ai_coding": {
                "priority_rules": ["RC-005", "RC-006"],
                "instruction": (
                    "Check four-state UI requirements and whether image or "
                    "prototype references are shareable relative/context links."
                ),
            },
            "quality": {
                "priority_rules": ["V-09", "V-12"],
                "instruction": (
                    "Check edge states, empty states, permissions, failures, "
                    "and loading behavior against the referenced screen."
                ),
            },
        },
    },
)


def detect_review_scenarios(prd_content: str | None) -> list[dict[str, Any]]:
    """Return detected PRD scenarios with dimension-specific checklist focus."""
    text = prd_content or ""
    lowered = text.lower()
    scenarios: list[dict[str, Any]] = []
    for scenario in _SCENARIO_DEFS:
        matched = _matched_terms(lowered, scenario["terms"])
        if not matched:
            continue
        scenarios.append(
            {
                "id": scenario["id"],
                "label": scenario["label"],
                "matched_terms": matched,
                "dimensions": scenario["dimensions"],
            }
        )
    return scenarios


def scenario_focus_for_dimension(prd_content: str | None, dim_key: str | None) -> str:
    """Render current-dimension scenario focus for worker prompt injection."""
    if not dim_key:
        return ""
    lines: list[str] = []
    for scenario in detect_review_scenarios(prd_content):
        focus = scenario["dimensions"].get(dim_key)
        if not focus:
            continue
        rules = ", ".join(focus["priority_rules"])
        terms = ", ".join(scenario["matched_terms"][:6])
        lines.append(
            f"- {scenario['id']} ({scenario['label']}): prioritize {rules}. "
            f"{focus['instruction']} Matched signals: {terms}."
        )
    if not lines:
        return ""
    return "## Scenario-specific checklist focus\n" + "\n".join(lines)


def _matched_terms(lowered_text: str, terms: tuple[str, ...]) -> list[str]:
    matched: list[str] = []
    for term in terms:
        needle = term.lower()
        if re.search(re.escape(needle), lowered_text):
            matched.append(term)
    return matched
