"""Adaptive routing and context-budget policy for PRD review workers."""

from __future__ import annotations

import os
from typing import Dict, Mapping


HIGH_RISK_DIMS = frozenset({"structure", "quality", "data_quality", "ai_coding", "consistency"})
DIMENSION_WIKI_BUDGET_RATIO = {
    "structure": 0.45,
    "quality": 0.50,
    "ai_coding": 0.75,
    "data_quality": 0.85,
}
LARGE_PRD_WIKI_BUDGET_RATIO = {
    "ai_coding": 0.75,
    "data_quality": 0.85,
}
RECOVERY_WIKI_BUDGET_RATIO = 0.40
SMALL_PRD_CHARS = 8_000
MEDIUM_PRD_CHARS = 15_000
SMALL_PRD_WIKI_BUDGET_RATIO = 0.33
LIGHT_MODE_WIKI_CHARS = 36_000
LARGE_PRD_CHARS = 30_000
LARGE_WIKI_PAGE_COUNT = 50


def review_complexity(prd_content: str | None, wiki_pages: Mapping[str, str] | None) -> Dict[str, int | bool]:
    prd_chars = len(prd_content or "")
    wiki_page_count = len(wiki_pages or {})
    if prd_chars < SMALL_PRD_CHARS:
        size_tier = "small"
    elif prd_chars < MEDIUM_PRD_CHARS:
        size_tier = "medium"
    else:
        size_tier = "large"
    return {
        "prd_chars": prd_chars,
        "wiki_page_count": wiki_page_count,
        "size_tier": size_tier,
        "is_large": prd_chars >= LARGE_PRD_CHARS or wiki_page_count >= LARGE_WIKI_PAGE_COUNT,
    }


def _prd_size_budget_ratio(prd_chars: int) -> float:
    if prd_chars < SMALL_PRD_CHARS:
        return SMALL_PRD_WIKI_BUDGET_RATIO
    return 1.0


def _effective_base_chars(base_chars: int) -> int:
    mode = os.environ.get("PECKER_REVIEW_MODE", "deep").strip().lower()
    if mode == "light":
        return min(base_chars, LIGHT_MODE_WIKI_CHARS)
    return base_chars


def choose_worker_model_override(
    dim_key: str,
    *,
    prd_content: str | None = None,
    wiki_pages: Mapping[str, str] | None = None,
    recovery_mode: bool = False,
) -> str | None:
    """Return a route tier override when the worker should be promoted."""
    if recovery_mode:
        return "gpt55"
    complexity = review_complexity(prd_content, wiki_pages)
    if complexity["is_large"] and dim_key not in {"default"}:
        return "gpt55"
    return None


def wiki_budget_for_dim(
    dim_key: str | None,
    base_chars: int,
    *,
    prd_content: str | None = None,
    wiki_pages: Mapping[str, str] | None = None,
    recovery_mode: bool = False,
) -> int:
    if base_chars <= 0:
        return 1
    base_chars = _effective_base_chars(base_chars)
    ratio = DIMENSION_WIKI_BUDGET_RATIO.get(dim_key or "", 1.0)
    complexity = review_complexity(prd_content, wiki_pages)
    if complexity["is_large"] and dim_key in LARGE_PRD_WIKI_BUDGET_RATIO:
        ratio = min(ratio, LARGE_PRD_WIKI_BUDGET_RATIO[dim_key or ""])
    if prd_content is not None:
        ratio = min(ratio, _prd_size_budget_ratio(int(complexity["prd_chars"])))
    if recovery_mode:
        normal_ratio = ratio
        ratio = min(ratio, RECOVERY_WIKI_BUDGET_RATIO)
        if ratio >= normal_ratio:
            ratio = normal_ratio * 0.75
    return max(1, int(base_chars * ratio))
