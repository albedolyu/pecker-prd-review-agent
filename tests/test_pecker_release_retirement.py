from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_pecker_release_snapshot_is_retired_from_runtime_tree():
    assert not (PROJECT_ROOT / "pecker-release").exists()


def test_runtime_scans_no_longer_special_case_pecker_release():
    checked_files = [
        PROJECT_ROOT / ".gitignore",
        PROJECT_ROOT / "pyproject.toml",
        PROJECT_ROOT / "scripts" / "doc_coherence.py",
        PROJECT_ROOT / "tests" / "test_config_env.py",
    ]

    for path in checked_files:
        assert "pecker-release" not in path.read_text(encoding="utf-8")
