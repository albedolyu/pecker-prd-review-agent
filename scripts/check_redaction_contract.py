"""Redaction-contract guard helpers.

The functions are intentionally small and importable so unit tests and future
git hooks can share the same leak checks.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Iterable, List

_PUBLIC_EXIT_PATTERNS = ("emit(", "store.save(", "JSONResponse(")


def find_inline_prd_sources(project_root: Path | str) -> List[str]:
    root = Path(project_root)
    leaks: List[str] = []
    eval_root = root / "eval_reports"
    if not eval_root.is_dir():
        return leaks
    for path in sorted(eval_root.glob("**/*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if _contains_inline_prd_source(payload):
            leaks.append(str(path))
    return leaks


def find_unreviewed_public_exit_calls(paths: Iterable[Path | str]) -> List[str]:
    warnings: List[str] = []
    for raw_path in paths:
        path = Path(raw_path)
        if path.suffix != ".py" or not path.is_file():
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        for index, line in enumerate(lines):
            stripped = line.strip()
            if not _is_public_exit_call(stripped):
                continue
            window = lines[max(0, index - 4): index + 1]
            if any("contract: NoPRDBody" in candidate for candidate in window):
                continue
            warnings.append(f"{path}:{index + 1}: {stripped}")
    return warnings


def _is_public_exit_call(line: str) -> bool:
    if not line or line.startswith("#"):
        return False
    return any(pattern in line for pattern in _PUBLIC_EXIT_PATTERNS)


def _contains_inline_prd_source(value: Any) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "prd_source" and isinstance(item, str) and _looks_like_inline_prd(item):
                return True
            if _contains_inline_prd_source(item):
                return True
    if isinstance(value, list):
        return any(_contains_inline_prd_source(item) for item in value)
    return False


def _looks_like_inline_prd(value: str) -> bool:
    text = value.strip()
    if len(text) < 120:
        return False
    if _looks_like_path_reference(text):
        return False
    return "\n" in text or "PRD" in text.upper() or "需求" in text


def _looks_like_path_reference(value: str) -> bool:
    if "\n" in value or "\r" in value or len(value) > 260:
        return False
    suffixes = (".md", ".markdown", ".txt", ".docx", ".pdf", ".json")
    return "/" in value or "\\" in value or value.lower().endswith(suffixes)


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check PRD redaction contract artifacts.")
    parser.add_argument("--project-root", default=".", help="Repository root to scan.")
    parser.add_argument("--changed-file", action="append", default=[], help="Python file to scan for public exits.")
    args = parser.parse_args(list(argv) if argv is not None else None)
    leaks = find_inline_prd_sources(Path(args.project_root))
    public_exit_warnings = find_unreviewed_public_exit_calls(args.changed_file)
    if leaks:
        print("Inline PRD source found in eval reports:")
        for path in leaks:
            print(f"- {path}")
    if public_exit_warnings:
        print("Public exit calls without nearby contract: NoPRDBody:")
        for warning in public_exit_warnings:
            print(f"- {warning}")
    if leaks or public_exit_warnings:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
