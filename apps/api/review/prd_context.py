"""Local PRD context packet builder for retry and gateway recovery paths."""
from __future__ import annotations

import os
import re
from functools import lru_cache
from typing import Iterable, List, Tuple


_DIM_KEYWORDS = {
    "structure": ("目标", "范围", "流程", "验收", "边界", "角色", "里程碑", "成功标准"),
    "quality": ("体验", "交互", "页面", "空态", "异常", "文案", "用户", "反馈"),
    "data_quality": ("字段", "口径", "数据", "指标", "埋点", "映射", "JOIN", "统计"),
    "data": ("字段", "口径", "数据", "指标", "埋点", "映射", "JOIN", "统计"),
    "risk": ("实现", "接口", "依赖", "权限", "安全", "超时", "兜底", "边界"),
    "ai_coding": ("实现", "接口", "依赖", "权限", "安全", "超时", "兜底", "边界"),
}
AUTO_PACKET_PRD_CHARS = 12_000
AUTO_PACKET_WIKI_PAGES = 50


def _clean(text: str) -> str:
    return re.sub(r"\n{3,}", "\n\n", str(text or "")).strip()


@lru_cache(maxsize=32)
def _split_sections_cached(prd_content: str) -> Tuple[Tuple[str, str, int, int], ...]:
    lines = str(prd_content or "").splitlines()
    sections: List[Tuple[str, List[str], int, int]] = []
    current_title = "开头说明"
    current_lines: List[str] = []
    current_start_line = 1
    heading_re = re.compile(r"^\s*(#{1,6}\s+.+|\d+(?:\.\d+)*[\.、]\s*.+|[一二三四五六七八九十]+[、.]\s*.+)\s*$")
    for line_no, line in enumerate(lines, start=1):
        if heading_re.match(line):
            if current_lines:
                sections.append((current_title, current_lines, current_start_line, line_no - 1))
            current_title = re.sub(r"^\s*#{1,6}\s*", "", line).strip()
            current_lines = [line]
            current_start_line = line_no
        else:
            current_lines.append(line)
    if current_lines:
        sections.append((current_title, current_lines, current_start_line, len(lines)))
    return tuple(
        (title, _clean("\n".join(body)), start_line, end_line)
        for title, body, start_line, end_line in sections
        if _clean("\n".join(body))
    )


def _split_sections(prd_content: str) -> List[Tuple[str, str, int, int]]:
    return list(_split_sections_cached(str(prd_content or "")))


def _score_section(title: str, body: str, keywords: Iterable[str]) -> int:
    text = f"{title}\n{body}".lower()
    score = 0
    for keyword in keywords:
        if str(keyword).lower() in text:
            score += 5 if str(keyword).lower() in title.lower() else 2
    return score


def _is_overview_section(title: str, idx: int) -> bool:
    if idx == 0:
        return True
    return bool(re.search(r"(目标|背景|范围|概述|说明|价值|业务)", title))


def _line_range_label(start_line: int, end_line: int) -> str:
    if start_line == end_line:
        return f"第 {start_line} 行"
    return f"第 {start_line}-{end_line} 行"


def build_prd_context_packet(
    prd_content: str,
    *,
    dim_key: str | None = None,
    max_chars: int = 12_000,
) -> str:
    """Build a compact, deterministic PRD packet for recovery retries.

    This is local preprocessing, not an LLM summary. It preserves section names
    and excerpts so retry prompts can shrink input without inventing facts.
    """
    max_chars = max(800, int(max_chars or 12_000))
    prd_content = _clean(prd_content)
    if len(prd_content) <= max_chars:
        return prd_content

    sections = _split_sections(prd_content)
    if not sections:
        return prd_content[:max_chars].rstrip()

    outline = [
        f"- {title[:80]}（原文{_line_range_label(start_line, end_line)}）"
        for title, _body, start_line, end_line in sections[:30]
    ]
    keywords = _DIM_KEYWORDS.get(dim_key or "", ())
    scored = [
        (_score_section(title, body, keywords), idx, title, body, start_line, end_line)
        for idx, (title, body, start_line, end_line) in enumerate(sections)
    ]
    scored.sort(key=lambda row: (row[0], -row[1]), reverse=True)
    selected = [row for row in scored if row[0] > 0][:4]
    if not selected:
        selected = scored[:4]
    overview = next(
        (
            (0, idx, title, body, start_line, end_line)
            for idx, (title, body, start_line, end_line) in enumerate(sections[:8])
            if _is_overview_section(title, idx)
        ),
        None,
    )
    if overview is not None and all(row[1] != overview[1] for row in selected):
        selected = [overview, *selected[:3]]
    selected.sort(key=lambda row: row[1])

    budget_for_excerpts = max_chars - 80 - sum(len(line) + 1 for line in outline)
    per_section = max(240, budget_for_excerpts // max(1, len(selected)))

    parts = ["## PRD 结构索引", "\n".join(outline), "## 本维度相关摘录"]
    for _score, _idx, title, body, start_line, end_line in selected:
        excerpt = body[:per_section].rstrip()
        parts.append(f"### {title}（原文{_line_range_label(start_line, end_line)}）\n{excerpt}")

    packet = _clean("\n\n".join(parts))
    if len(packet) > max_chars:
        packet = packet[:max_chars].rstrip()
    return packet


def should_use_prd_context_packet(
    prd_content: str,
    wiki_pages: dict | None,
    *,
    recovery_mode: bool = False,
) -> bool:
    """Decide whether a worker should receive a compact PRD packet."""
    mode = os.environ.get("PECKER_PRD_CONTEXT_MODE", "auto").strip().lower()
    if mode in {"full", "off", "0", "false"}:
        return False
    if mode in {"packet", "compact", "on", "1", "true"}:
        return True
    if recovery_mode:
        return True
    return (
        len(prd_content or "") >= prd_context_auto_threshold_chars()
        or len(wiki_pages or {}) >= AUTO_PACKET_WIKI_PAGES
    )


def prd_context_auto_threshold_chars() -> int:
    raw = os.environ.get("PECKER_PRD_CONTEXT_AUTO_CHARS", "").strip()
    if not raw:
        return AUTO_PACKET_PRD_CHARS
    try:
        value = int(raw)
    except ValueError:
        return AUTO_PACKET_PRD_CHARS
    return max(2_000, value)


def prd_context_packet_budget(*, recovery_mode: bool = False) -> int:
    default = 8_000 if recovery_mode else 12_000
    raw = os.environ.get("PECKER_PRD_CONTEXT_PACKET_CHARS", "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(800, value)
