from __future__ import annotations

import os
import re
from collections import OrderedDict
from typing import Any

from review.dimensions import get_wiki_keywords
from review.wiki_selection import _summarize, normalize_wiki_title, select_wiki_pages


TRUE_VALUES = {"1", "true", "yes", "on"}
DEFAULT_GOSHAWK_WIKI_CHARS = 25_000
WORKER_DIM_KEYS = ("structure", "quality", "ai_coding", "data_quality")
WORKER_WIKI_BUDGET_CHARS = 4_950


def should_compact_goshawk_wiki() -> bool:
    return os.environ.get("PECKER_GOSHAWK_COMPACT_WIKI", "").strip().lower() in TRUE_VALUES


def get_goshawk_wiki_budget() -> int:
    raw = os.environ.get("PECKER_GOSHAWK_WIKI_CHARS", "").strip()
    if not raw:
        return DEFAULT_GOSHAWK_WIKI_CHARS
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_GOSHAWK_WIKI_CHARS
    return max(0, value)


def compact_goshawk_wiki_pages(
    wiki_pages: dict[str, str],
    prd_content: str,
    worker_results: list[dict[str, Any]],
    *,
    max_chars: int | None = None,
) -> tuple[dict[str, str], dict[str, Any]]:
    budget = get_goshawk_wiki_budget() if max_chars is None else max(0, int(max_chars))
    if not wiki_pages or budget <= 0:
        return {}, _telemetry({}, 0, 0, [], [], {})

    selected: OrderedDict[str, str] = OrderedDict()
    total_before = sum(len(content) for content in wiki_pages.values())
    worker_events: list[dict[str, Any]] = []
    forced_events: list[dict[str, Any]] = []
    used_chars = 0

    def add_page(title: str, content: str, mode: str) -> None:
        nonlocal used_chars
        if not title or not content or used_chars >= budget:
            return
        current = selected.get(title)
        if current is not None and len(current) >= len(content):
            return
        if current is not None:
            used_chars -= len(current)
        remaining = budget - used_chars
        if remaining <= 0:
            return
        if len(content) <= remaining:
            selected[title] = content
            used_chars += len(content)
            worker_events.append({"title": title, "mode": mode, "chars": len(content)})
            return
        summary = _summarize(content, min(1200, remaining))
        if summary:
            selected[title] = summary
            used_chars += len(summary)
            worker_events.append({"title": title, "mode": f"{mode}_summary", "chars": len(summary)})

    wiki_keywords = get_wiki_keywords()
    for dim_key in WORKER_DIM_KEYS:
        dim_selected, dim_telemetry = select_wiki_pages(
            wiki_pages,
            prd_content,
            dim_key=dim_key,
            wiki_keywords=wiki_keywords,
            max_chars=WORKER_WIKI_BUDGET_CHARS,
            summary_chars=500,
        )
        for title, content in dim_selected.items():
            add_page(title, content, f"worker_union:{dim_key}")
        worker_events.append(
            {
                "dimension": dim_key,
                "mode": "worker_selection_summary",
                "selected_count": dim_telemetry.get("selected_count"),
                "chars": dim_telemetry.get("total_chars_after"),
            }
        )

    aliases = _wiki_alias_map(wiki_pages)
    for title in _forced_titles_from_worker_citations(worker_results, aliases):
        content = wiki_pages.get(title) or ""
        if not content or used_chars >= budget:
            forced_events.append({"title": title, "mode": "omitted", "chars": 0})
            continue
        before = used_chars
        add_page(title, content, "forced_citation")
        forced_events.append(
            {
                "title": title,
                "mode": "selected" if used_chars > before else "already_selected",
                "chars": max(0, used_chars - before),
            }
        )

    remaining_budget = max(0, budget - used_chars)
    remaining_pages = {title: content for title, content in wiki_pages.items() if title not in selected}
    auto_selected, auto_telemetry = select_wiki_pages(
        remaining_pages,
        _focus_text(prd_content, worker_results),
        dim_key=None,
        max_chars=remaining_budget,
        summary_chars=900,
    )
    for title, content in auto_selected.items():
        add_page(title, content, "auto_prd_worker")

    total_after = sum(len(content) for content in selected.values())
    return dict(selected), _telemetry(
        selected,
        total_before,
        total_after,
        worker_events,
        forced_events,
        auto_telemetry,
        budget=budget,
    )


def _telemetry(
    selected: dict[str, str],
    total_before: int,
    total_after: int,
    worker_events: list[dict[str, Any]],
    forced_events: list[dict[str, Any]],
    auto_telemetry: dict[str, Any],
    *,
    budget: int = 0,
) -> dict[str, Any]:
    return {
        "strategy": "worker_union_then_forced_citations_then_prd_worker_selection",
        "budget_chars": budget,
        "selected_count": len(selected),
        "worker_union_count": len([event for event in worker_events if event.get("title")]),
        "forced_count": len(forced_events),
        "total_chars_before": total_before,
        "total_chars_after": total_after,
        "reduction_ratio": round(total_after / total_before, 4) if total_before else 0,
        "selected_titles": list(selected.keys()),
        "worker_union_pages": worker_events,
        "forced_pages": forced_events,
        "auto_selection": auto_telemetry,
    }


def _wiki_alias_map(wiki_pages: dict[str, str]) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for title in wiki_pages:
        aliases[normalize_wiki_title(title)] = title
        if "/" in title:
            aliases[normalize_wiki_title(title.rsplit("/", 1)[-1])] = title
    return aliases


def _forced_titles_from_worker_citations(
    worker_results: list[dict[str, Any]],
    aliases: dict[str, str],
) -> list[str]:
    titles: OrderedDict[str, None] = OrderedDict()
    citation_re = re.compile(r"\[\[([^\]]+)\]\]")
    for item in worker_results or []:
        if not isinstance(item, dict):
            continue
        for key in ("evidence_content", "evidence", "location", "issue", "suggestion"):
            for raw in citation_re.findall(str(item.get(key) or "")):
                title = aliases.get(normalize_wiki_title(raw))
                if title:
                    titles[title] = None
    return list(titles.keys())


def _focus_text(prd_content: str, worker_results: list[dict[str, Any]]) -> str:
    parts = [str(prd_content or "")[:8000]]
    for item in worker_results or []:
        if not isinstance(item, dict):
            continue
        parts.append(
            "\n".join(
                str(item.get(key) or "")
                for key in ("id", "rule_id", "dimension", "location", "issue", "suggestion", "evidence_content")
            )
        )
    return "\n".join(parts)
