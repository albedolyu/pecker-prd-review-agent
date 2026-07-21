"""Bounded post-consolidation coverage advisor."""

from collections.abc import Sequence

from .models import AdvisorReview, Finding


def review_gaps(findings: Sequence[Finding]) -> AdvisorReview:
    """Return at most two coverage notices without changing findings."""

    categories = {finding.category for finding in findings}
    checks = (
        (
            {"scope_section", "acceptance_section", "structure_placeholder"},
            "No structure coverage remains after consolidation.",
        ),
        (
            {"measurable_outcome", "target_user", "failure_experience"},
            "No product-quality coverage remains after consolidation.",
        ),
        (
            {"implementation_placeholder", "interface_contract", "test_examples"},
            "No AI-coding-readiness coverage remains after consolidation.",
        ),
        (
            {"personal_data_handling", "data_source", "data_validation"},
            "No data-quality coverage remains after consolidation.",
        ),
    )
    gaps = [notice for expected, notice in checks if categories.isdisjoint(expected)]
    return AdvisorReview(gaps=gaps[:2])


__all__ = ["review_gaps"]
