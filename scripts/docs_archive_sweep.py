"""Suggest docs archive moves without changing files."""

from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
import re


DATE_PATTERNS = [
    re.compile(r"(?P<year>20\d{2})[_-](?P<month>\d{2})[_-](?P<day>\d{2})"),
    re.compile(r"(?P<year>20\d{2})(?P<month>\d{2})(?P<day>\d{2})"),
]
SKIP_DIRS = {"archive", "research"}


@dataclass(frozen=True)
class ArchiveMove:
    source: Path
    target: Path
    reason: str
    file_date: date


@dataclass(frozen=True)
class ArchiveWarning:
    source: Path
    reason: str
    last_commit_date: date | None


@dataclass(frozen=True)
class ArchiveSweepResult:
    moves: list[ArchiveMove]
    warnings: list[ArchiveWarning]


def parse_doc_date(filename: str) -> date | None:
    for pattern in DATE_PATTERNS:
        match = pattern.search(filename)
        if not match:
            continue
        try:
            return date(
                int(match.group("year")),
                int(match.group("month")),
                int(match.group("day")),
            )
        except ValueError:
            return None
    return None


def _is_before_current_month(file_date: date, current_date: date) -> bool:
    return (file_date.year, file_date.month) < (current_date.year, current_date.month)


def _iter_markdown_files(docs_root: Path):
    for path in sorted(docs_root.rglob("*.md")):
        relative = path.relative_to(docs_root)
        if relative.parts and relative.parts[0] in SKIP_DIRS:
            continue
        yield path


def _last_git_commit_date(path: Path, repo_root: Path) -> date | None:
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%ct", "--", str(path)],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0 or not result.stdout.strip():
        return None
    return datetime.fromtimestamp(int(result.stdout.strip())).date()


def collect_archive_suggestions(
    docs_root: Path,
    *,
    current_date: date | None = None,
    warn_after_days: int = 30,
) -> ArchiveSweepResult:
    current_date = current_date or date.today()
    docs_root = docs_root.resolve()
    repo_root = docs_root.parent
    moves: list[ArchiveMove] = []
    warnings: list[ArchiveWarning] = []

    for path in _iter_markdown_files(docs_root):
        file_date = parse_doc_date(path.name)
        if file_date and _is_before_current_month(file_date, current_date):
            target = Path("archive") / f"{file_date:%Y-%m}" / path.name
            moves.append(
                ArchiveMove(
                    source=path,
                    target=target,
                    reason="dated_before_current_month",
                    file_date=file_date,
                )
            )
            continue

        if file_date:
            continue

        last_commit_date = _last_git_commit_date(path, repo_root)
        if last_commit_date and last_commit_date < current_date - timedelta(days=warn_after_days):
            warnings.append(
                ArchiveWarning(
                    source=path,
                    reason="undated_and_stale_commit",
                    last_commit_date=last_commit_date,
                )
            )

    return ArchiveSweepResult(moves=moves, warnings=warnings)


def _result_to_json(result: ArchiveSweepResult, docs_root: Path, dry_run: bool) -> str:
    payload = {
        "dry_run": dry_run,
        "moves": [
            {
                "source": move.source.relative_to(docs_root).as_posix(),
                "target": move.target.as_posix(),
                "reason": move.reason,
                "date": move.file_date.isoformat(),
            }
            for move in result.moves
        ],
        "warnings": [
            {
                "source": warning.source.relative_to(docs_root).as_posix(),
                "reason": warning.reason,
                "last_commit_date": warning.last_commit_date.isoformat()
                if warning.last_commit_date
                else None,
            }
            for warning in result.warnings
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _result_to_text(result: ArchiveSweepResult, docs_root: Path, dry_run: bool) -> str:
    lines = [f"docs archive sweep ({'dry-run' if dry_run else 'apply'})"]
    lines.append(f"move suggestions: {len(result.moves)}")
    for move in result.moves:
        source = move.source.relative_to(docs_root).as_posix()
        lines.append(f"- {source} -> {move.target.as_posix()} [{move.reason}]")
    lines.append(f"manual review warnings: {len(result.warnings)}")
    for warning in result.warnings:
        source = warning.source.relative_to(docs_root).as_posix()
        lines.append(f"- {source} [{warning.reason}]")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Suggest docs archive moves.")
    parser.add_argument("--docs-root", default="docs")
    parser.add_argument("--current-date", default=date.today().isoformat())
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--format", choices=["text", "json"], default="text")
    args = parser.parse_args(argv)

    if not args.dry_run:
        parser.error("docs_archive_sweep is read-only; pass --dry-run to print suggestions.")

    docs_root = Path(args.docs_root).resolve()
    current_date = date.fromisoformat(args.current_date)
    result = collect_archive_suggestions(docs_root, current_date=current_date)

    if args.format == "json":
        print(_result_to_json(result, docs_root, dry_run=True))
    else:
        print(_result_to_text(result, docs_root, dry_run=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
