import hashlib
from pathlib import Path
import struct
import subprocess
import zlib

import pytest

from scripts import check_public_boundary

scan_paths = check_public_boundary.scan_paths
scan_repository = check_public_boundary.scan_repository


def _windows_path(*parts: str) -> str:
    return "C:" + chr(92) + chr(92).join(parts)


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


def _init_repository(root: Path, email: str = "123+portfolio-bot@users.noreply.github.com") -> None:
    _git(root, "init", "--quiet")
    _git(root, "config", "user.name", "Portfolio Bot")
    _git(root, "config", "user.email", email)


def _commit_all(root: Path, message: str) -> None:
    _git(root, "add", "-A")
    _git(root, "commit", "--quiet", "-m", message)


def _png_chunk(chunk_type: bytes, data: bytes) -> bytes:
    payload = chunk_type + data
    return struct.pack(">I", len(data)) + payload + struct.pack(">I", zlib.crc32(payload))


def _safe_png(extra_chunks: tuple[tuple[bytes, bytes], ...] = ()) -> bytes:
    header = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    pixels = zlib.compress(b"\x00\x00\x00\x00")
    chunks = [(b"IHDR", header), *extra_chunks, (b"IDAT", pixels), (b"IEND", b"")]
    return b"\x89PNG\r\n\x1a\n" + b"".join(_png_chunk(kind, data) for kind, data in chunks)


def test_scan_paths_allows_synthetic_prose_and_documentation_ip(tmp_path: Path) -> None:
    candidate = tmp_path / "README.md"
    candidate.write_text(
        "Example company profile. Documentation endpoint: 192.0.2.10.\n",
        encoding="utf-8",
    )

    assert scan_paths(tmp_path, [candidate]) == []


@pytest.mark.parametrize(
    ("content", "matched_value", "expected_rule"),
    [
        (
            "local_path = '" + _windows_path("Users", "portfolio-user", "Desktop", "private-workspace"),
            _windows_path("Users", "portfolio-user", "Desktop", "private-workspace"),
            "personal-home-path",
        ),
        ("resolver = '" + "8" + ".8.8.8'", "8" + ".8.8.8", "non-documentation-ipv4"),
        ("-----BEGIN " + "PRIVATE KEY-----", "-----BEGIN " + "PRIVATE KEY-----", "private-key-header"),
    ],
)
def test_scan_paths_reports_sensitive_content_without_echoing_it(
    tmp_path: Path, content: str, matched_value: str, expected_rule: str
) -> None:
    candidate = tmp_path / "candidate.txt"
    candidate.write_text(content + "\n", encoding="utf-8")

    violations = scan_paths(tmp_path, [candidate])

    assert len(violations) == 1
    assert violations[0].path == candidate.relative_to(tmp_path)
    assert violations[0].rule == expected_rule
    assert violations[0].line == 1
    assert matched_value not in str(violations[0])


def test_scan_paths_matches_optional_one_way_forbidden_term_digest(tmp_path: Path) -> None:
    forbidden_term = "ExampleInternalApi"
    digest = hashlib.sha256(forbidden_term.casefold().encode("utf-8")).hexdigest()
    candidate = tmp_path / "candidate.txt"
    candidate.write_text(f"source_repository = '{forbidden_term}'\n", encoding="utf-8")

    violations = scan_paths(tmp_path, [candidate], forbidden_term_digests={digest})

    assert [violation.rule for violation in violations] == ["forbidden-term-digest"]
    assert forbidden_term not in str(violations[0])


def test_scan_paths_redacts_a_forbidden_digest_found_only_in_the_path(tmp_path: Path) -> None:
    forbidden_term = "".join(("Example", "Internal", "Api"))
    digest = hashlib.sha256(forbidden_term.casefold().encode("utf-8")).hexdigest()
    candidate = tmp_path / forbidden_term / "notes.txt"
    candidate.parent.mkdir()
    candidate.write_text("Safe synthetic content.\n", encoding="utf-8")

    violations = scan_paths(tmp_path, [candidate], forbidden_term_digests={digest})

    assert len(violations) == 1
    assert violations[0].path == Path("<redacted-path>")
    assert violations[0].rule == "sensitive-path-content"
    assert violations[0].line == 0
    assert forbidden_term not in str(violations[0])


@pytest.mark.parametrize(
    "relative_path",
    [
        ".env",
        "config/.ENV.Local",
        "cache/data.DB",
        "cache/data.sqlite3-wal",
        "LOGS/run.txt",
        "frontend/Node_Modules/pkg/index.js",
        "frontend/.NEXT/cache/item",
        "reports/Coverage/index.html",
        "reports/htmlcov/index.html",
        "tools/.VENV/pyvenv.cfg",
        "tools/venv/pyvenv.cfg",
        "build/package.txt",
        "dist/package.txt",
        "output/playwright/trace.zip",
        "playwright-report/index.html",
        "test-results/results.json",
        ".playwright/browser.bin",
        ".playwright-cli/session.json",
        "package.egg-info/PKG-INFO",
        "src/__PYCACHE__/module.pyc",
        ".PYTEST_CACHE/v/cache/nodeids",
    ],
)
def test_scan_paths_rejects_forbidden_artifact_paths_before_decoding(
    tmp_path: Path, relative_path: str
) -> None:
    candidate = tmp_path.joinpath(*relative_path.split("/"))
    candidate.parent.mkdir(parents=True, exist_ok=True)
    candidate.write_bytes(b"harmless\xffbinary")

    violations = scan_paths(tmp_path, [candidate])

    assert len(violations) == 1
    assert violations[0].rule == "forbidden-artifact-path"
    assert violations[0].line == 0
    assert "harmless" not in str(violations[0])


def test_scan_repository_rejects_a_force_tracked_ignored_database(tmp_path: Path) -> None:
    _init_repository(tmp_path)
    (tmp_path / ".gitignore").write_text("*.db\n", encoding="utf-8")
    database = tmp_path / "runtime" / "cache.db"
    database.parent.mkdir()
    database.write_bytes(b"SQLite format 3\x00synthetic")
    _git(tmp_path, "add", ".gitignore")
    _git(tmp_path, "add", "--force", "runtime/cache.db")

    violations = scan_repository(tmp_path)

    assert [violation.rule for violation in violations] == ["forbidden-artifact-path"]
    assert violations[0].path == Path("runtime/cache.db")


@pytest.mark.parametrize(
    ("filename", "payload"),
    [
        ("cache.db-journal", b""),
        ("cache.sqlite-journal", b"safe utf-8 journal"),
        ("cache.sqlite3-journal", b""),
    ],
)
def test_scan_repository_rejects_force_tracked_database_journals(
    tmp_path: Path, filename: str, payload: bytes
) -> None:
    _init_repository(tmp_path)
    (tmp_path / ".gitignore").write_text("*-journal\n", encoding="utf-8")
    journal = tmp_path / "runtime" / filename
    journal.parent.mkdir()
    journal.write_bytes(payload)
    _git(tmp_path, "add", ".gitignore")
    _git(tmp_path, "add", "--force", f"runtime/{filename}")

    violations = scan_repository(tmp_path)

    assert [violation.rule for violation in violations] == ["forbidden-artifact-path"]
    assert violations[0].path == Path("runtime") / filename


def test_scan_repository_rejects_force_tracked_superpowers_content(tmp_path: Path) -> None:
    _init_repository(tmp_path)
    (tmp_path / ".gitignore").write_text(".superpowers/\n", encoding="utf-8")
    candidate = tmp_path / ".superpowers" / "sdd" / "notes.md"
    candidate.parent.mkdir(parents=True)
    candidate.write_text("Safe synthetic notes.\n", encoding="utf-8")
    _git(tmp_path, "add", ".gitignore")
    _git(tmp_path, "add", "--force", ".superpowers/sdd/notes.md")

    violations = scan_repository(tmp_path)

    assert [violation.rule for violation in violations] == ["forbidden-artifact-path"]
    assert violations[0].path == Path(".superpowers/sdd/notes.md")


def test_scan_paths_allows_only_metadata_free_png_screenshots(tmp_path: Path) -> None:
    candidate = tmp_path / "docs" / "screenshots" / "review-input.png"
    candidate.parent.mkdir(parents=True)
    candidate.write_bytes(_safe_png())

    assert scan_paths(tmp_path, [candidate]) == []


@pytest.mark.parametrize("chunk_type", [b"tEXt", b"zTXt", b"iTXt", b"eXIf"])
def test_scan_paths_rejects_metadata_chunks_in_allowlisted_png(
    tmp_path: Path, chunk_type: bytes
) -> None:
    candidate = tmp_path / "docs" / "screenshots" / "review-findings.png"
    candidate.parent.mkdir(parents=True)
    candidate.write_bytes(_safe_png(((chunk_type, b"synthetic metadata"),)))

    violations = scan_paths(tmp_path, [candidate])

    assert [violation.rule for violation in violations] == ["png-metadata-chunk"]


def test_scan_paths_rejects_unknown_binary(tmp_path: Path) -> None:
    candidate = tmp_path / "assets" / "archive.bin"
    candidate.parent.mkdir()
    candidate.write_bytes(b"\x00\xff\x10synthetic")

    violations = scan_paths(tmp_path, [candidate])

    assert [violation.rule for violation in violations] == ["binary-not-allowlisted"]


def test_scan_git_history_finds_deleted_secret_and_forbidden_path(tmp_path: Path) -> None:
    _init_repository(tmp_path)
    candidate = tmp_path / "notes.txt"
    candidate.write_text("token = '" + "sk-" + "a" * 24 + "'\n", encoding="utf-8")
    forbidden = tmp_path / ".env.history"
    forbidden.write_text("DEMO=true\n", encoding="utf-8")
    _commit_all(tmp_path, "add temporary synthetic fixtures")
    candidate.unlink()
    forbidden.unlink()
    (tmp_path / "README.md").write_text("Safe current tree.\n", encoding="utf-8")
    _commit_all(tmp_path, "remove temporary synthetic fixtures")

    violations = check_public_boundary.scan_git_history(tmp_path)
    rules = {violation.rule for violation in violations}

    assert "credential-token-format" in rules
    assert "forbidden-artifact-path" in rules


def test_scan_git_history_rejects_non_github_noreply_email(tmp_path: Path) -> None:
    _init_repository(tmp_path, email="developer@example.test")
    (tmp_path / "README.md").write_text("Synthetic repository.\n", encoding="utf-8")
    _commit_all(tmp_path, "initial synthetic commit")

    violations = check_public_boundary.scan_git_history(tmp_path)

    assert {violation.rule for violation in violations} == {"non-github-noreply-email"}
    assert "developer" not in "\n".join(map(str, violations))


def test_scan_git_history_allows_safe_noreply_history(tmp_path: Path) -> None:
    _init_repository(tmp_path)
    (tmp_path / "README.md").write_text("Synthetic repository.\n", encoding="utf-8")
    _commit_all(tmp_path, "initial synthetic commit")

    assert check_public_boundary.scan_git_history(tmp_path) == []
