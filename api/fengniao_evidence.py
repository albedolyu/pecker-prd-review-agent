"""Read-only Fengniao knowledge and fact-layer search for the PM assistant."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, List

from api.sanitize import redact_text

_DEFAULT_WIKI_PATH = Path(r"C:\Users\20834\Desktop\代码项目\风鸟代码库\wiki")
_DEFAULT_KNOWLEDGE_PATH = Path(r"C:\Users\20834\Desktop\代码项目\fengniao-knowledge")
_DEFAULT_SOURCE_ROOTS = (
    Path(r"C:\Users\20834\Desktop\代码项目\风鸟代码库\源码\riskbird-mobile-vue3"),
    Path(r"C:\Users\20834\Desktop\代码项目\风鸟代码库\源码\RiskBirdApi"),
    Path(r"C:\Users\20834\Desktop\代码项目\风鸟代码库\源码\RiskBirdWeb"),
)

_TEXT_EXTENSIONS = {
    ".css",
    ".java",
    ".js",
    ".json",
    ".jsx",
    ".kt",
    ".less",
    ".md",
    ".py",
    ".scss",
    ".ts",
    ".tsx",
    ".txt",
    ".vue",
    ".xml",
    ".yaml",
    ".yml",
}
_SKIP_DIRS = {
    ".git",
    ".next",
    ".pytest_cache",
    ".venv",
    ".vscode",
    "__pycache__",
    "build",
    "dist",
    "logs",
    "node_modules",
    "target",
}
_MAX_FILE_BYTES = 512 * 1024
_MAX_FILES_PER_ROOT = 1200
_FACT_LAYER_TERMS = (
    "事实层",
    "原始",
    "源码",
    "代码",
    "接口",
    "字段",
    "实现",
    "页面",
    "数据库",
    "api",
    "source",
)
_CJK_STOP_TERMS = {
    "一下",
    "这个",
    "那个",
    "什么",
    "怎么",
    "是否",
    "可以",
    "支持",
    "查询",
    "查一",
    "查查",
    "帮我",
    "风鸟",
    "知识",
    "知识库",
    "事实层",
    "原始",
    "源码",
    "依据",
    "内容",
}


@dataclass(frozen=True)
class _SearchRoot:
    layer: str
    label: str
    path: Path


@dataclass(frozen=True)
class _ScoredHit:
    score: int
    layer: str
    layer_label: str
    path: str
    absolute_path: str
    line: int
    snippet: str


def infer_include_fact_layer(question: str) -> bool:
    """Infer whether the user is asking for original fact/source evidence."""
    q = question.lower()
    return any(term in q for term in _FACT_LAYER_TERMS)


def search_fengniao_evidence(
    question: str,
    *,
    include_fact_layer: bool = False,
    max_results: int = 5,
) -> dict[str, Any]:
    """Search governed Fengniao knowledge and optional original source mirrors.

    This is deliberately lexical and read-only. The assistant uses it as a
    lightweight evidence lookup, not as an autonomous reviewer.
    """
    terms = _extract_terms(question)
    roots = _configured_roots(include_fact_layer)
    hits: List[_ScoredHit] = []

    for root in roots:
        hits.extend(_search_root(root, terms))

    ordered = sorted(hits, key=lambda hit: (-hit.score, hit.layer, hit.path))[:max_results]
    public_hits = [
        {
            "layer": hit.layer,
            "layer_label": hit.layer_label,
            "path": hit.path,
            "line": hit.line,
            "snippet": hit.snippet,
        }
        for hit in ordered
    ]
    return {
        "answer": _build_answer(question, public_hits, include_fact_layer=include_fact_layer),
        "hits": public_hits,
        "searched_roots": [
            {
                "layer": root.layer,
                "label": root.label,
                "path": str(root.path),
                "exists": root.path.is_dir(),
            }
            for root in roots
        ],
        "include_fact_layer": include_fact_layer,
    }


def _configured_roots(include_fact_layer: bool) -> list[_SearchRoot]:
    roots: list[_SearchRoot] = []

    wiki = _env_path("PECKER_FENGNIAO_WIKI_PATH", _DEFAULT_WIKI_PATH)
    roots.append(_SearchRoot("wiki", "风鸟代码 Wiki", wiki))

    knowledge_raw = os.environ.get("PECKER_FENGNIAO_KNOWLEDGE_PATH", "").strip()
    if knowledge_raw:
        roots.append(_SearchRoot("knowledge", "风鸟知识库", Path(knowledge_raw)))
    elif wiki == _DEFAULT_WIKI_PATH:
        roots.append(_SearchRoot("knowledge", "风鸟知识库", _DEFAULT_KNOWLEDGE_PATH))

    if include_fact_layer:
        for source_root in _source_roots():
            roots.append(_SearchRoot("fact", "原始事实层", source_root))

    return roots


def _env_path(name: str, default: Path) -> Path:
    value = os.environ.get(name, "").strip()
    return Path(value) if value else default


def _source_roots() -> list[Path]:
    raw = os.environ.get("PECKER_FENGNIAO_SOURCE_ROOTS", "").strip()
    if raw:
        return [Path(item.strip()) for item in raw.split(";") if item.strip()]
    return list(_DEFAULT_SOURCE_ROOTS)


def _search_root(root: _SearchRoot, terms: list[str]) -> list[_ScoredHit]:
    if not root.path.is_dir() or not terms:
        return []

    hits: list[_ScoredHit] = []
    for file_path in _iter_text_files(root.path):
        try:
            text = file_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

        score = _score_file(file_path, text, terms)
        if score <= 0:
            continue

        line, snippet = _best_snippet(text, terms)
        hits.append(
            _ScoredHit(
                score=score,
                layer=root.layer,
                layer_label=root.label,
                path=_relative_display_path(file_path, root.path),
                absolute_path=str(file_path),
                line=line,
                snippet=redact_text(snippet),
            )
        )
    return hits


def _iter_text_files(root: Path) -> Iterable[Path]:
    seen = 0
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            entries = list(current.iterdir())
        except OSError:
            continue
        for entry in entries:
            if entry.is_dir():
                if entry.name not in _SKIP_DIRS:
                    stack.append(entry)
                continue
            if entry.suffix.lower() not in _TEXT_EXTENSIONS:
                continue
            try:
                if entry.stat().st_size > _MAX_FILE_BYTES:
                    continue
            except OSError:
                continue
            yield entry
            seen += 1
            if seen >= _MAX_FILES_PER_ROOT:
                return


def _extract_terms(question: str) -> list[str]:
    raw_terms = re.findall(r"[a-z0-9_./:-]{2,}|[\u4e00-\u9fff]+", question.lower())
    terms: list[str] = []
    for raw in raw_terms:
        if re.fullmatch(r"[\u4e00-\u9fff]+", raw):
            if 2 <= len(raw) <= 8 and raw not in _CJK_STOP_TERMS:
                terms.append(raw)
            for size in (2, 3, 4, 5, 6):
                if len(raw) < size:
                    continue
                for index in range(0, len(raw) - size + 1):
                    sub = raw[index : index + size]
                    if sub not in _CJK_STOP_TERMS:
                        terms.append(sub)
        elif raw not in _CJK_STOP_TERMS:
            terms.append(raw)

    deduped: list[str] = []
    seen = set()
    for term in terms:
        if term in seen:
            continue
        seen.add(term)
        deduped.append(term)
    return deduped[:80]


def _score_file(path: Path, text: str, terms: list[str]) -> int:
    lower_text = text.lower()
    lower_name = path.name.lower()
    score = 0
    for term in terms:
        if term in lower_name:
            score += 8
        count = lower_text.count(term)
        if count:
            score += min(count, 5) * 2
    return score


def _best_snippet(text: str, terms: list[str]) -> tuple[int, str]:
    lines = text.splitlines()
    for index, line in enumerate(lines, start=1):
        lower_line = line.lower()
        if any(term in lower_line for term in terms):
            return index, _clean_snippet(line)
    return 1, _clean_snippet(text[:260])


def _clean_snippet(value: str) -> str:
    compact = re.sub(r"\s+", " ", value).strip()
    if len(compact) <= 260:
        return compact
    return compact[:257] + "..."


def _relative_display_path(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root)).replace("\\", "/")
    except ValueError:
        return path.name


def _build_answer(
    question: str,
    hits: list[dict[str, Any]],
    *,
    include_fact_layer: bool,
) -> str:
    if not hits:
        scope = "风鸟知识库和原始事实层" if include_fact_layer else "风鸟知识库"
        return f"这次在{scope}里没有命中可引用依据。建议先补充更具体的页面名、接口名、字段名或业务对象。"

    fact_count = sum(1 for hit in hits if hit["layer"] == "fact")
    header = f"查到 {len(hits)} 条风鸟依据"
    if include_fact_layer:
        header += f"，其中事实层 {fact_count} 条"
    header += "。我先按证据列出来，结论仍以 PRD 当前语境和源码实际实现为准："

    lines = [header]
    for index, hit in enumerate(hits, start=1):
        location = f"{hit['path']}:{hit['line']}"
        lines.append(
            f"{index}. [{hit['layer_label']}] {location} — {hit['snippet']}"
        )
    if not include_fact_layer:
        lines.append("如果要核对原始事实层，可以直接问“查事实层/源码/接口字段”。")
    return "\n".join(lines)
