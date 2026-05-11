"""Resolve Figma supplemental-material links into compact review context."""
from __future__ import annotations

import json
import os
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Iterable, List


FIGMA_URL_RE = re.compile(
    r"https?://(?:www\.)?figma\.com/(?:design|file|proto|board|figjam)/[^\s<>\"')\]]+",
    re.IGNORECASE,
)
SENSITIVE_QUERY_KEYS = {
    "access_token",
    "api_key",
    "apikey",
    "auth",
    "authorization",
    "code",
    "client_secret",
    "password",
    "secret",
    "sig",
    "signature",
    "token",
}
DEFAULT_TIMEOUT_SECONDS = 8.0
MAX_FIGMA_LINKS = 5
MAX_NODE_NAMES = 32
MAX_TEXT_NODES = 40
MAX_TEXT_CHARS = 140
MAX_CONTEXT_CHARS = 5000


@dataclass(frozen=True)
class FigmaLink:
    raw_url: str
    safe_url: str
    file_key: str
    node_id: str


def enrich_figma_raw_materials(raw_materials: Iterable[str]) -> List[str]:
    """Append Figma-derived context blocks without blocking review on failures."""
    materials = [str(item) for item in raw_materials]
    links = _extract_figma_links(materials)
    if not links:
        return materials

    parsed_urls = _existing_parsed_urls(materials)
    additions: List[str] = []
    for link in links[:MAX_FIGMA_LINKS]:
        if link.safe_url in parsed_urls:
            continue
        additions.append(_build_figma_context_block(link))

    return materials + additions


def _extract_figma_links(materials: Iterable[str]) -> List[FigmaLink]:
    seen: set[str] = set()
    links: List[FigmaLink] = []
    for material in materials:
        for match in FIGMA_URL_RE.finditer(material):
            raw_url = match.group(0).rstrip("，。；;,.")
            link = _parse_figma_link(raw_url)
            if link is None or link.safe_url in seen:
                continue
            seen.add(link.safe_url)
            links.append(link)
    return links


def _parse_figma_link(raw_url: str) -> FigmaLink | None:
    try:
        parsed = urllib.parse.urlparse(raw_url)
    except ValueError:
        return None
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2:
        return None
    file_key = parts[1]
    node_id = urllib.parse.parse_qs(parsed.query).get("node-id", [""])[0].replace("-", ":")
    if not file_key:
        return None
    return FigmaLink(
        raw_url=raw_url,
        safe_url=_redact_sensitive_url_query_params(raw_url),
        file_key=file_key,
        node_id=node_id,
    )


def _existing_parsed_urls(materials: Iterable[str]) -> set[str]:
    urls: set[str] = set()
    for material in materials:
        if "[补充材料: Figma 解析]" not in material:
            continue
        for match in FIGMA_URL_RE.finditer(material):
            urls.add(_redact_sensitive_url_query_params(match.group(0).rstrip("，。；;,.")))
    return urls


def _build_figma_context_block(link: FigmaLink) -> str:
    token = _figma_access_token()
    if not token:
        return "\n".join(
            [
                "[补充材料: Figma 解析]",
                f"链接: {link.safe_url}",
                f"file_key: {link.file_key}",
                link.node_id and f"node_id: {link.node_id}",
                "读取状态: 未配置 FIGMA_ACCESS_TOKEN，已保留 Figma 链接，未拉取画布内容。",
            ]
        ).strip()

    try:
        payload = _fetch_figma_payload(link, token)
        return _summarize_figma_payload(link, payload)
    except Exception as exc:  # noqa: BLE001 - Figma context should never block review.
        error = str(exc).replace(token, "[REDACTED]")[:200]
        return "\n".join(
            [
                "[补充材料: Figma 解析]",
                f"链接: {link.safe_url}",
                f"file_key: {link.file_key}",
                link.node_id and f"node_id: {link.node_id}",
                f"读取状态: Figma 内容读取失败，已保留链接供人工核对。原因: {error}",
            ]
        ).strip()


def _figma_access_token() -> str:
    return (
        os.environ.get("FIGMA_ACCESS_TOKEN", "").strip()
        or os.environ.get("PECKER_FIGMA_ACCESS_TOKEN", "").strip()
    )


def _figma_timeout_seconds() -> float:
    raw = (
        os.environ.get("FIGMA_FETCH_TIMEOUT")
        or os.environ.get("PECKER_FIGMA_FETCH_TIMEOUT")
        or str(DEFAULT_TIMEOUT_SECONDS)
    )
    try:
        return max(0.5, float(raw))
    except ValueError:
        return DEFAULT_TIMEOUT_SECONDS


def _fetch_figma_payload(link: FigmaLink, token: str) -> dict[str, Any]:
    file_key = urllib.parse.quote(link.file_key, safe="")
    if link.node_id:
        node_id = urllib.parse.quote(link.node_id, safe="")
        api_url = f"https://api.figma.com/v1/files/{file_key}/nodes?ids={node_id}"
    else:
        api_url = f"https://api.figma.com/v1/files/{file_key}"
    request = urllib.request.Request(
        api_url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=_figma_timeout_seconds()) as response:
        body = response.read()
    data = json.loads(body.decode("utf-8"))
    return data if isinstance(data, dict) else {}


def _summarize_figma_payload(link: FigmaLink, payload: dict[str, Any]) -> str:
    documents = _figma_documents(payload)
    node_names: List[str] = []
    text_values: List[str] = []
    for document in documents:
        _collect_figma_summary(document, node_names=node_names, text_values=text_values)

    lines = [
        "[补充材料: Figma 解析]",
        f"链接: {link.safe_url}",
        f"file_key: {link.file_key}",
        link.node_id and f"node_id: {link.node_id}",
        "读取状态: 已读取 Figma 结构与文本，以下内容已进入本次评审上下文。",
        payload.get("name") and f"文件名: {str(payload.get('name'))[:120]}",
    ]
    if node_names:
        lines.append("关键节点: " + " / ".join(node_names[:MAX_NODE_NAMES]))
    if text_values:
        lines.append("可读文本:")
        lines.extend(f"- {text}" for text in text_values[:MAX_TEXT_NODES])
    return "\n".join(str(line) for line in lines if line)[:MAX_CONTEXT_CHARS]


def _figma_documents(payload: dict[str, Any]) -> List[dict[str, Any]]:
    if isinstance(payload.get("nodes"), dict):
        docs = []
        for node in payload["nodes"].values():
            if isinstance(node, dict) and isinstance(node.get("document"), dict):
                docs.append(node["document"])
        return docs
    document = payload.get("document")
    return [document] if isinstance(document, dict) else []


def _collect_figma_summary(
    node: dict[str, Any],
    *,
    node_names: List[str],
    text_values: List[str],
) -> None:
    node_type = str(node.get("type") or "")
    name = str(node.get("name") or "").strip()
    if name and len(node_names) < MAX_NODE_NAMES and node_type in {"FRAME", "SECTION", "COMPONENT", "INSTANCE", "GROUP", "TEXT"}:
        node_names.append(name[:80])

    characters = str(node.get("characters") or "").strip()
    if characters and len(text_values) < MAX_TEXT_NODES:
        text_values.append(_compact_whitespace(characters)[:MAX_TEXT_CHARS])

    for child in node.get("children") or []:
        if isinstance(child, dict):
            _collect_figma_summary(child, node_names=node_names, text_values=text_values)


def _compact_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _redact_sensitive_url_query_params(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    if not parsed.query:
        return url

    query_parts = []
    for key, value in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True):
        if key.lower() in SENSITIVE_QUERY_KEYS:
            value = "[REDACTED]"
        query_parts.append((key, value))
    safe_query = urllib.parse.urlencode(query_parts, doseq=True).replace("%5BREDACTED%5D", "[REDACTED]")
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, safe_query, parsed.fragment))
