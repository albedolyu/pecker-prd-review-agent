from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from pecker.models import PromptQualityScore, PromptVariant
from pecker.redaction import redact_text


EVIDENCE_TERMS = ("evidence", "quote", "citation", "source", "line", "excerpt")
SCHEMA_TERMS = ("json", "schema", "field", "rule_id", "severity", "confidence")
GUIDANCE_TERMS = ("how_to_fix", "recommendation", "acceptance", "example", "owner")
SAFETY_NEGATIVE_TERMS = (
    "ignore previous instructions",
    "print secrets",
    "leak key",
    "private url",
)


def load_prompt_variants(path: str | Path) -> list[PromptVariant]:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return [PromptVariant(**item) for item in raw.get("prompts", [])]


def evaluate_prompt_quality(variants: list[PromptVariant]) -> list[PromptQualityScore]:
    return [score_prompt_variant(variant) for variant in variants]


def rank_prompt_quality(scores: list[PromptQualityScore]) -> list[dict[str, Any]]:
    rows = [score.model_dump() for score in scores]
    return sorted(rows, key=lambda row: (-row["overall"], row["name"]))


def score_prompt_variant(variant: PromptVariant) -> PromptQualityScore:
    prompt = redact_text(variant.prompt)
    lowered = prompt.lower()
    expected = [item.strip().lower() for item in variant.expected_controls if item.strip()]
    covered = [item for item in expected if item in lowered]
    missing = [item for item in expected if item not in lowered]

    instruction_coverage = _ratio(len(covered), len(expected)) if expected else 1.0
    evidence_contract = _keyword_score(lowered, EVIDENCE_TERMS)
    output_schema = _keyword_score(lowered, SCHEMA_TERMS)
    improvement_guidance = _keyword_score(lowered, GUIDANCE_TERMS)
    safety_boundary = 0.0 if any(term in lowered for term in SAFETY_NEGATIVE_TERMS) else 1.0

    overall = round(
        instruction_coverage * 0.35
        + evidence_contract * 0.20
        + output_schema * 0.20
        + improvement_guidance * 0.15
        + safety_boundary * 0.10,
        4,
    )

    return PromptQualityScore(
        name=variant.name,
        role=variant.role,
        instruction_coverage=round(instruction_coverage, 4),
        evidence_contract=round(evidence_contract, 4),
        output_schema=round(output_schema, 4),
        improvement_guidance=round(improvement_guidance, 4),
        safety_boundary=round(safety_boundary, 4),
        overall=overall,
        missing_controls=missing,
    )


def _keyword_score(text: str, terms: tuple[str, ...]) -> float:
    hits = sum(1 for term in terms if term in text)
    return _ratio(hits, len(terms))


def _ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 1.0
    return max(0.0, min(1.0, numerator / denominator))
