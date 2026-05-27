"""Budget-aware wiki page selection for worker prompts.

This module keeps deep review prompts focused by selecting the most relevant
wiki pages per worker dimension before prompt construction. It is intentionally
pure and deterministic so it can be tested without model calls or filesystem IO.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Tuple


_STOP_TERMS = {
    "文档",
    "说明",
    "需求",
    "版本",
    "内容",
    "数据",
    "系统",
    "功能",
    "用户",
    "信息",
    "通过",
    "支持",
    "进行",
    "使用",
    "相关",
    "以下",
    "如下",
    "其中",
}

_AUTHORITY_SCORE = {
    "canonical": 6,
    "contextual": 2,
    "generated": -3,
}


def normalize_wiki_title(title: str) -> str:
    text = str(title or "").strip().lower().replace("\\", "/")
    if text.endswith(".md"):
        text = text[:-3]
    return re.sub(r"[\s_\-./:：#]+", "", text)


def wiki_title_aliases(title: str) -> set[str]:
    text = str(title or "").strip().replace("\\", "/")
    if text.endswith(".md"):
        text = text[:-3]
    aliases = {normalize_wiki_title(text)}
    if "/" in text:
        aliases.add(normalize_wiki_title(text.rsplit("/", 1)[-1]))
    return {a for a in aliases if a}


def select_wiki_pages(
    wiki_pages: Dict[str, str],
    prd_content: str,
    *,
    dim_key: str | None = None,
    wiki_keywords: Dict[str, List[str]] | None = None,
    max_chars: int = 60_000,
    summary_chars: int = 500,
) -> Tuple[Dict[str, str], Dict[str, Any]]:
    """Select and compact wiki pages for a single worker prompt.

    Args:
        wiki_pages: Mapping of wiki title to full markdown content.
        prd_content: PRD text used to extract topical terms.
        dim_key: Current worker dimension, e.g. ``data_quality``.
        wiki_keywords: Dimension-specific keyword config from ``dimensions.py``.
        max_chars: Total character budget for selected wiki content.
        summary_chars: Per-page summary budget for pages that score well but
            do not fit in full.

    Returns:
        ``(selected_pages, telemetry)``. ``selected_pages`` preserves ranking
        order. Telemetry is safe to log and contains no full wiki content.
    """
    if not wiki_pages or max_chars <= 0:
        return {}, _telemetry([], 0, 0)

    dim_terms = list((wiki_keywords or {}).get(dim_key or "", []))
    prd_terms = _extract_prd_terms(prd_content)
    total_before = sum(len(content) for content in wiki_pages.values())

    scored_pages = []
    for index, (title, content) in enumerate(wiki_pages.items()):
        authority = _extract_authority(content)
        score, reasons = _score_page(title, content, dim_terms, prd_terms, authority)
        scored_pages.append({
            "index": index,
            "title": title,
            "content": content,
            "authority": authority,
            "score": score,
            "reasons": reasons,
        })

    has_positive_match = any(p["score"] > 0 for p in scored_pages)
    scored_pages.sort(key=lambda p: (-p["score"], p["index"], p["title"]))

    selected: Dict[str, str] = {}
    page_events: List[Dict[str, Any]] = []
    used_chars = 0

    for page in scored_pages:
        title = page["title"]
        content = page["content"]
        score = page["score"]

        if has_positive_match and score <= 0:
            page_events.append(_page_event(page, mode="omitted", chars=0))
            continue

        remaining = max_chars - used_chars
        if remaining <= 0:
            page_events.append(_page_event(page, mode="omitted", chars=0))
            continue

        if len(content) <= remaining:
            selected[title] = content
            used_chars += len(content)
            page_events.append(_page_event(page, mode="full", chars=len(content)))
            continue

        summary_budget = min(summary_chars, remaining)
        summary = _summarize(content, summary_budget)
        if summary:
            selected[title] = summary
            used_chars += len(summary)
            page_events.append(_page_event(page, mode="summary", chars=len(summary)))
        else:
            page_events.append(_page_event(page, mode="omitted", chars=0))

    return selected, _telemetry(page_events, total_before, used_chars)


def _telemetry(
    page_events: List[Dict[str, Any]],
    total_chars_before: int,
    total_chars_after: int,
) -> Dict[str, Any]:
    selected_count = sum(1 for p in page_events if p["mode"] != "omitted")
    return {
        "selected_count": selected_count,
        "omitted_count": len(page_events) - selected_count,
        "total_chars_before": total_chars_before,
        "total_chars_after": total_chars_after,
        "pages": page_events,
    }


def _page_event(page: Dict[str, Any], *, mode: str, chars: int) -> Dict[str, Any]:
    return {
        "title": page["title"],
        "score": page["score"],
        "authority": page["authority"],
        "mode": mode,
        "chars": chars,
        "reasons": page["reasons"],
    }


def _extract_authority(content: str) -> str:
    """Return frontmatter authority value when present."""
    if not content.startswith("---"):
        return ""
    end = content.find("\n---", 3)
    if end == -1:
        return ""
    frontmatter = content[3:end]
    match = re.search(r"(?im)^\s*authority\s*:\s*([A-Za-z_-]+)\s*$", frontmatter)
    return match.group(1).strip().lower() if match else ""


def _extract_prd_terms(prd_content: str, limit: int = 80) -> List[str]:
    text = (prd_content or "")[:5000]
    raw_terms = []
    raw_terms.extend(re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", text))
    raw_terms.extend(re.findall(r"[\u4e00-\u9fff]{2,6}", text))

    seen = set()
    terms = []
    for term in raw_terms:
        normalized = term.lower() if term.isascii() else term
        if normalized in _STOP_TERMS or normalized in seen:
            continue
        seen.add(normalized)
        terms.append(normalized)
        if len(terms) >= limit:
            break
    return terms


def _score_page(
    title: str,
    content: str,
    dim_terms: Iterable[str],
    prd_terms: Iterable[str],
    authority: str,
) -> Tuple[int, List[str]]:
    title_l = title.lower()
    title_alias_text = " ".join(wiki_title_aliases(title))
    content_head = content[:3000]
    content_l = content_head.lower()

    score = 0
    reasons: List[str] = []

    title_dim_hits = _count_hits(dim_terms, title_l) + _count_hits(dim_terms, title_alias_text)
    if title_dim_hits:
        score += title_dim_hits * 8
        reasons.append(f"title_dim:{title_dim_hits}")

    content_dim_hits = min(_count_hits(dim_terms, content_l), 6)
    if content_dim_hits:
        score += content_dim_hits * 2
        reasons.append(f"content_dim:{content_dim_hits}")

    title_prd_hits = _count_hits(prd_terms, title_l) + _count_hits(prd_terms, title_alias_text)
    if title_prd_hits:
        score += title_prd_hits * 4
        reasons.append(f"title_prd:{title_prd_hits}")

    content_prd_hits = min(_count_hits(prd_terms, content_l), 12)
    if content_prd_hits:
        score += content_prd_hits
        reasons.append(f"content_prd:{content_prd_hits}")

    authority_score = _AUTHORITY_SCORE.get(authority, 0)
    if authority_score:
        score += authority_score
        reasons.append(f"authority:{authority}")

    return score, reasons


def _count_hits(terms: Iterable[str], text: str) -> int:
    count = 0
    for term in terms:
        if not term:
            continue
        needle = term.lower() if term.isascii() else term
        if needle in text:
            count += 1
    return count


def _summarize(content: str, budget: int) -> str:
    if budget <= 0:
        return ""
    if len(content) <= budget:
        return content
    suffix = f"\n\n(... 余 {len(content) - budget} 字已省略 — wiki_selection 预算截断)"
    if len(suffix) >= budget:
        return content[:budget]
    return content[: budget - len(suffix)].rstrip() + suffix
