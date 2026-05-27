"""Extract compact schema context from supplemental materials."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Iterable, List


SCHEMA_CONTEXT_MARKER = "[Supplemental material: Schema analysis]"
MAX_TABLES = 8
MAX_COLUMNS_PER_TABLE = 12
MAX_CONTEXT_CHARS = 4000

_CREATE_TABLE_RE = re.compile(
    r"\bCREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?P<name>[`\"\[\]\w.]+)\s*\((?P<body>.*?)\)\s*;",
    re.IGNORECASE | re.DOTALL,
)
_IDENTIFIER_RE = re.compile(r"^[`\"\[]?(?P<name>[A-Za-z_][\w$]*)[`\"\]]?$")
_TABLE_CONSTRAINT_PREFIXES = {
    "constraint",
    "primary",
    "foreign",
    "unique",
    "check",
    "key",
    "index",
}


@dataclass(frozen=True)
class SchemaTable:
    name: str
    columns: tuple[str, ...]
    source: str = "DDL table"


def enrich_schema_raw_materials(raw_materials: Iterable[str]) -> List[str]:
    """Append a compact DDL/schema summary for cross-asset review alignment."""
    materials = [str(item) for item in raw_materials]
    if any(SCHEMA_CONTEXT_MARKER in item for item in materials):
        return materials

    tables = _extract_create_table_summaries(materials)
    tables.extend(_extract_json_schema_summaries(materials, seen={table.name.lower() for table in tables}))
    if not tables:
        return materials

    return materials + [_build_schema_context_block(tables)]


def _extract_create_table_summaries(materials: Iterable[str]) -> List[SchemaTable]:
    seen: set[str] = set()
    tables: List[SchemaTable] = []
    for material in materials:
        for match in _CREATE_TABLE_RE.finditer(material):
            table_name = _clean_table_name(match.group("name"))
            if not table_name or table_name.lower() in seen:
                continue
            columns = tuple(_extract_columns(match.group("body")))
            if not columns:
                continue
            seen.add(table_name.lower())
            tables.append(SchemaTable(name=table_name, columns=columns))
            if len(tables) >= MAX_TABLES:
                return tables
    return tables


def _extract_json_schema_summaries(materials: Iterable[str], *, seen: set[str]) -> List[SchemaTable]:
    tables: List[SchemaTable] = []
    for material in materials:
        for payload in _iter_json_objects(material):
            if not isinstance(payload, dict):
                continue
            properties = payload.get("properties")
            if not isinstance(properties, dict) or not properties:
                continue
            title = str(payload.get("title") or payload.get("$id") or payload.get("name") or "json_schema").strip()
            schema_name = _clean_json_schema_name(title)
            if not schema_name or schema_name.lower() in seen:
                continue
            fields = tuple(_extract_json_schema_fields(properties))
            if not fields:
                continue
            seen.add(schema_name.lower())
            tables.append(SchemaTable(name=schema_name, columns=fields, source="JSON Schema"))
            if len(tables) >= MAX_TABLES:
                return tables
    return tables


def _iter_json_objects(material: str) -> Iterable[object]:
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", material):
        try:
            payload, _ = decoder.raw_decode(material[match.start() :])
        except json.JSONDecodeError:
            continue
        yield payload


def _clean_json_schema_name(raw_name: str) -> str:
    name = raw_name.rsplit("/", 1)[-1].split("#", 1)[0].strip()
    if not name:
        return ""
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", name).strip("_.-")
    return cleaned[:80]


def _extract_json_schema_fields(properties: dict[object, object]) -> List[str]:
    fields: List[str] = []
    seen: set[str] = set()
    for raw_field in properties:
        field = str(raw_field).strip()
        if not _IDENTIFIER_RE.match(field):
            continue
        key = field.lower()
        if key in seen:
            continue
        seen.add(key)
        fields.append(field)
        if len(fields) >= MAX_COLUMNS_PER_TABLE:
            break
    return fields


def _clean_table_name(raw_name: str) -> str:
    parts = [part.strip("`\"[] ") for part in raw_name.split(".")]
    cleaned = [part for part in parts if _IDENTIFIER_RE.match(part)]
    return ".".join(cleaned[-2:])


def _extract_columns(body: str) -> List[str]:
    columns: List[str] = []
    seen: set[str] = set()
    for field in _split_columns(body):
        token = field.strip().split(maxsplit=1)[0] if field.strip() else ""
        if not token:
            continue
        if token.lower().strip("`\"[]") in _TABLE_CONSTRAINT_PREFIXES:
            continue
        match = _IDENTIFIER_RE.match(token)
        if not match:
            continue
        column = match.group("name")
        key = column.lower()
        if key in seen:
            continue
        seen.add(key)
        columns.append(column)
        if len(columns) >= MAX_COLUMNS_PER_TABLE:
            break
    return columns


def _split_columns(body: str) -> List[str]:
    parts: List[str] = []
    current: List[str] = []
    depth = 0
    for char in body:
        if char == "(":
            depth += 1
        elif char == ")" and depth > 0:
            depth -= 1
        if char == "," and depth == 0:
            parts.append("".join(current))
            current = []
            continue
        current.append(char)
    if current:
        parts.append("".join(current))
    return parts


def _build_schema_context_block(tables: List[SchemaTable]) -> str:
    lines = [
        SCHEMA_CONTEXT_MARKER,
        "Read status: local DDL parsed; use this as a schema alignment anchor.",
        "Review focus: verify that PRD fields, filters, joins, permissions, and acceptance criteria match these assets.",
        "Detected tables:",
    ]
    for table in tables:
        lines.append(f"- {table.name} ({table.source}): " + ", ".join(table.columns))
    return "\n".join(lines)[:MAX_CONTEXT_CHARS]
