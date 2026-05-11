"""Confidence scoring shared by review workers and legacy adapters."""

from __future__ import annotations


# Evidence type to confidence baseline.
# A = source/wiki quote, B = rule reference, C = inferred/experience evidence.
EVIDENCE_CONFIDENCE_BASE = {
    "A": 0.9,
    "B": 0.8,
    "C": 0.5,
    "": 0.4,
}

# Goshawk supplemental findings are useful, but lower confidence than worker
# findings because they did not pass the primary worker review path.
GOSHAWK_SUPPLEMENT_DECAY = 0.8


def compute_confidence(evidence_type: str | None, is_supplement: bool = False) -> float:
    """Return the calibrated confidence score for an evidence type."""

    base = EVIDENCE_CONFIDENCE_BASE.get((evidence_type or "").upper(), 0.4)
    if is_supplement:
        base *= GOSHAWK_SUPPLEMENT_DECAY
    return round(base, 2)
