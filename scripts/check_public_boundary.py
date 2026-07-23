"""Reject files and Git history that cross the public-release boundary."""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import re
import subprocess
import unicodedata
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class BoundaryViolation:
    """A public-boundary rule breach without the matched sensitive value."""

    path: Path
    rule: str
    line: int

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: public-boundary rule {self.rule}"


_PRIVATE_KEY_HEADER = re.compile(r"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----")
_PERSONAL_HOME_PATH = re.compile(
    r"(?:[A-Za-z]:[\\/](?:Users|home)[\\/][^\\/\s'\"]+|/(?:Users|home)/[^/\s'\"]+)",
    re.IGNORECASE,
)
_IPV4_LITERAL = re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])")
_TOKEN_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\b(?:gh[pousr]|github_pat)_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
)
_TERM_CANDIDATE = re.compile(r"[^\W_]+(?:[._-][^\W_]+)*", re.UNICODE)
_GITHUB_NOREPLY_EMAIL = re.compile(
    r"(?:\d+\+)?[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?@users\.noreply\.github\.com",
    re.IGNORECASE,
)
_DOCUMENTATION_NETWORKS = (
    ipaddress.IPv4Network("192.0.2.0/24"),
    ipaddress.IPv4Network("198.51.100.0/24"),
    ipaddress.IPv4Network("203.0.113.0/24"),
)
_DEFAULT_FORBIDDEN_TERM_DIGESTS = frozenset(
    {
        "f4a511b048fbb38a8ef4d06181fc546529fcd3cab440c531a0984acf19c1eb93",
        "4fa646e7a80143eeb31268dfc2df5889756f9ffaf9b7703a76110cd41010cb29",
        "631f01cb83271372aa1482303ce9e08624152e228244f8b080f447b0e09ec43b",
        "e9270e3e1a6d191a2e4b132e72030a2694c08f0249d91c29ccc66bb7d1571015",
        "f893cc6764cfbcb72e30862459205a59f609dff82139caf7d230ebeb9ac24358",
        "26c17a01afd9a6446a45d83cdd3b444039be7674935107c3fd1a4a83fd43826a",
        "1ed103497649c994d51fee1d0b2620c4260a8e2a819aec55fb6e0b484b13e75b",
    }
)
_FORBIDDEN_DIRECTORY_NAMES = frozenset(
    {
        ".next",
        ".playwright",
        ".playwright-cli",
        ".pytest_cache",
        ".superpowers",
        ".venv",
        "__pycache__",
        "build",
        "coverage",
        "dist",
        "htmlcov",
        "logs",
        "node_modules",
        "playwright-report",
        "test-results",
        "venv",
    }
)
_ALLOWED_PNG_PATHS = frozenset(
    {
        "docs/screenshots/review-input.png",
        "docs/screenshots/review-findings.png",
    }
)
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_PNG_METADATA_CHUNKS = frozenset({b"tEXt", b"zTXt", b"iTXt", b"eXIf"})


def _run_git(repository: Path, *args: str) -> bytes:
    return subprocess.run(
        ["git", "-C", str(repository), *args],
        check=True,
        capture_output=True,
    ).stdout


def _is_allowed_ip(value: str) -> bool:
    try:
        address = ipaddress.IPv4Address(value)
    except ipaddress.AddressValueError:
        return False
    return address.is_loopback or any(address in network for network in _DOCUMENTATION_NETWORKS)


def _normalize_term(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold()


def _contains_forbidden_term(line: str, forbidden_term_digests: frozenset[str]) -> bool:
    for match in _TERM_CANDIDATE.finditer(line):
        token = match.group(0)
        candidates = {token, *re.split(r"[._-]+", token)}
        for candidate in candidates:
            normalized = _normalize_term(candidate)
            if not normalized:
                continue
            digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
            if digest in forbidden_term_digests:
                return True
    return False


def _line_rule(line: str, forbidden_term_digests: frozenset[str]) -> str | None:
    if _PRIVATE_KEY_HEADER.search(line):
        return "private-key-header"
    if _PERSONAL_HOME_PATH.search(line):
        return "personal-home-path"
    if _contains_forbidden_term(line, forbidden_term_digests):
        return "forbidden-term-digest"
    if any(pattern.search(line) for pattern in _TOKEN_PATTERNS):
        return "credential-token-format"
    if any(not _is_allowed_ip(value) for value in _IPV4_LITERAL.findall(line)):
        return "non-documentation-ipv4"
    return None


def _normalized_relative_path(value: str | Path) -> str:
    normalized = str(value).replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized.lstrip("/")


def _path_rule(relative_path: str | Path) -> str | None:
    normalized = _normalized_relative_path(relative_path)
    parts = [part.casefold() for part in normalized.split("/") if part]
    if not parts:
        return None
    basename = parts[-1]
    if any(part.startswith(".env") for part in parts):
        return "forbidden-artifact-path"
    if basename == ".coverage" or basename.endswith(".log"):
        return "forbidden-artifact-path"
    if re.search(r"\.(?:db|sqlite|sqlite3)(?:-(?:journal|wal|shm))?$", basename):
        return "forbidden-artifact-path"
    if any(part in _FORBIDDEN_DIRECTORY_NAMES or part.endswith(".egg-info") for part in parts):
        return "forbidden-artifact-path"
    if any(parts[index : index + 2] == ["output", "playwright"] for index in range(len(parts) - 1)):
        return "forbidden-artifact-path"
    return None


def _has_sensitive_path_content(
    normalized_path: str, forbidden_term_digests: frozenset[str]
) -> bool:
    return bool(_PERSONAL_HOME_PATH.search(normalized_path)) or _contains_forbidden_term(
        normalized_path, forbidden_term_digests
    )


def _display_path(root: Path, path: Path) -> Path:
    try:
        return path.resolve().relative_to(root.resolve())
    except ValueError:
        return Path("<outside-repository>")


def _png_rule(data: bytes) -> str | None:
    if not data.startswith(_PNG_SIGNATURE):
        return "png-invalid-structure"
    position = len(_PNG_SIGNATURE)
    chunk_types: list[bytes] = []
    while position < len(data):
        if position + 12 > len(data):
            return "png-invalid-structure"
        length = int.from_bytes(data[position : position + 4], "big")
        chunk_type = data[position + 4 : position + 8]
        chunk_end = position + 12 + length
        if chunk_end > len(data):
            return "png-invalid-structure"
        chunk_data = data[position + 8 : position + 8 + length]
        expected_crc = int.from_bytes(data[position + 8 + length : chunk_end], "big")
        if zlib.crc32(chunk_type + chunk_data) != expected_crc:
            return "png-invalid-structure"
        if chunk_type in _PNG_METADATA_CHUNKS:
            return "png-metadata-chunk"
        chunk_types.append(chunk_type)
        position = chunk_end
        if chunk_type == b"IEND":
            break
    if position != len(data) or not chunk_types or chunk_types[0] != b"IHDR":
        return "png-invalid-structure"
    if b"IDAT" not in chunk_types or chunk_types[-1] != b"IEND":
        return "png-invalid-structure"
    return None


def _scan_bytes(
    logical_path: str | Path,
    display_path: Path,
    data: bytes,
    forbidden_term_digests: frozenset[str],
) -> list[BoundaryViolation]:
    normalized_path = _normalized_relative_path(logical_path)
    if _has_sensitive_path_content(normalized_path, forbidden_term_digests):
        return [BoundaryViolation(Path("<redacted-path>"), "sensitive-path-content", 0)]

    path_rule = _path_rule(logical_path)
    if path_rule:
        return [BoundaryViolation(display_path, path_rule, 0)]

    if normalized_path in _ALLOWED_PNG_PATHS:
        png_rule = _png_rule(data)
        return [BoundaryViolation(display_path, png_rule, 0)] if png_rule else []

    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return [BoundaryViolation(display_path, "binary-not-allowlisted", 0)]
    if "\x00" in text:
        return [BoundaryViolation(display_path, "binary-not-allowlisted", 0)]

    violations: list[BoundaryViolation] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        rule = _line_rule(line, forbidden_term_digests)
        if rule:
            violations.append(BoundaryViolation(display_path, rule, line_number))
    return violations


def scan_paths(
    root: Path,
    paths: Iterable[Path],
    forbidden_term_digests: Iterable[str] | None = None,
) -> list[BoundaryViolation]:
    """Scan repository paths before decoding and return redacted violations."""

    repository = Path(root).resolve()
    digests = frozenset(
        _DEFAULT_FORBIDDEN_TERM_DIGESTS
        if forbidden_term_digests is None
        else forbidden_term_digests
    )
    violations: list[BoundaryViolation] = []
    for path in paths:
        candidate = Path(path)
        display_path = _display_path(repository, candidate)
        relative_path = _normalized_relative_path(display_path)
        if ".git" in {part.casefold() for part in relative_path.split("/")} or not candidate.is_file():
            continue
        violations.extend(
            _scan_bytes(relative_path, display_path, candidate.read_bytes(), digests)
        )
    return violations


def scan_repository(
    root: Path, forbidden_term_digests: Iterable[str] | None = None
) -> list[BoundaryViolation]:
    """Scan tracked and untracked files that Git considers publication candidates."""

    repository = Path(root).resolve()
    paths = [
        repository / relative_path.decode("utf-8")
        for relative_path in _run_git(
            repository,
            "ls-files",
            "-z",
            "--cached",
            "--others",
            "--exclude-standard",
        ).split(b"\0")
        if relative_path
    ]
    return scan_paths(repository, paths, forbidden_term_digests)


def _history_path(commit: str, label: str | Path) -> Path:
    return Path(".git-history") / commit[:12] / Path(label)


def _commit_metadata_violations(commit: str, content: bytes) -> list[BoundaryViolation]:
    headers, separator, message = content.partition(b"\n\n")
    violations: list[BoundaryViolation] = []
    for field in (b"author", b"committer"):
        matching = [line for line in headers.splitlines() if line.startswith(field + b" ")]
        email_match = re.search(rb"<([^<>]+)> \d+ [+-]\d{4}$", matching[0]) if matching else None
        if not email_match:
            violations.append(
                BoundaryViolation(_history_path(commit, field.decode("ascii")), "invalid-commit-metadata", 0)
            )
            continue
        email = email_match.group(1).decode("ascii", errors="replace")
        if not _GITHUB_NOREPLY_EMAIL.fullmatch(email):
            violations.append(
                BoundaryViolation(
                    _history_path(commit, field.decode("ascii")),
                    "non-github-noreply-email",
                    0,
                )
            )
    if not separator:
        violations.append(
            BoundaryViolation(_history_path(commit, "commit-message"), "invalid-commit-metadata", 0)
        )
    return violations


def scan_git_history(
    root: Path,
    forbidden_term_digests: Iterable[str] | None = None,
    *,
    history_ref: str = "HEAD",
) -> list[BoundaryViolation]:
    """Scan every commit reachable from the selected source ref."""

    repository = Path(root).resolve()
    digests = frozenset(
        _DEFAULT_FORBIDDEN_TERM_DIGESTS
        if forbidden_term_digests is None
        else forbidden_term_digests
    )
    commits = [
        line.decode("ascii")
        for line in _run_git(repository, "rev-list", history_ref).splitlines()
    ]
    violations: list[BoundaryViolation] = []
    seen_blob_paths: set[tuple[str, bytes]] = set()

    for commit in commits:
        commit_content = _run_git(repository, "cat-file", "-p", commit)
        violations.extend(_commit_metadata_violations(commit, commit_content))
        _, _, message = commit_content.partition(b"\n\n")
        violations.extend(
            _scan_bytes(
                "commit-message",
                _history_path(commit, "commit-message"),
                message,
                digests,
            )
        )

        for entry in _run_git(repository, "ls-tree", "-r", "-z", commit).split(b"\0"):
            if not entry:
                continue
            metadata, path_bytes = entry.split(b"\t", 1)
            _, object_type, object_id = metadata.split(b" ", 2)
            if object_type != b"blob":
                continue
            key = (object_id.decode("ascii"), path_bytes)
            if key in seen_blob_paths:
                continue
            seen_blob_paths.add(key)
            try:
                logical_path = path_bytes.decode("utf-8")
            except UnicodeDecodeError:
                violations.append(
                    BoundaryViolation(
                        _history_path(commit, "non-utf8-path"),
                        "non-utf8-history-path",
                        0,
                    )
                )
                continue
            blob = _run_git(repository, "cat-file", "blob", object_id.decode("ascii"))
            violations.extend(
                _scan_bytes(
                    logical_path,
                    _history_path(commit, Path(logical_path)),
                    blob,
                    digests,
                )
            )
    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--history",
        action="store_true",
        help="also scan commits reachable from the selected source ref",
    )
    parser.add_argument(
        "--history-ref",
        default="HEAD",
        help="source ref to scan when --history is enabled (default: HEAD)",
    )
    args = parser.parse_args(argv)
    root = Path.cwd()
    violations = scan_repository(root)
    if args.history:
        violations.extend(scan_git_history(root, history_ref=args.history_ref))
    for violation in violations:
        print(violation)
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
