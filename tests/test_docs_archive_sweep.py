import json
import subprocess
import sys
from datetime import date
from pathlib import Path


PROJECT_ROOT = Path(__file__).parent.parent


def test_dated_docs_before_current_month_are_suggested_for_archive(tmp_path):
    from scripts.docs_archive_sweep import collect_archive_suggestions

    docs_root = tmp_path / "docs"
    docs_root.mkdir()
    (docs_root / "audit_frontend_sync_2026_04_28.md").write_text("old", encoding="utf-8")
    (docs_root / "optimization_plan_2026_05_11.md").write_text("current", encoding="utf-8")

    result = collect_archive_suggestions(docs_root, current_date=date(2026, 5, 11))

    assert [move.source.name for move in result.moves] == ["audit_frontend_sync_2026_04_28.md"]
    assert result.moves[0].target.as_posix() == "archive/2026-04/audit_frontend_sync_2026_04_28.md"


def test_archive_sweep_skips_existing_archive_and_research_dirs(tmp_path):
    from scripts.docs_archive_sweep import collect_archive_suggestions

    docs_root = tmp_path / "docs"
    (docs_root / "archive" / "2026-04").mkdir(parents=True)
    (docs_root / "research").mkdir()
    (docs_root / "archive" / "2026-04" / "old_2026_04_01.md").write_text("archived", encoding="utf-8")
    (docs_root / "research" / "research_2026_04_26.md").write_text("research", encoding="utf-8")

    result = collect_archive_suggestions(docs_root, current_date=date(2026, 5, 11))

    assert result.moves == []


def test_archive_sweep_cli_outputs_json_dry_run(tmp_path):
    docs_root = tmp_path / "docs"
    docs_root.mkdir()
    (docs_root / "timing_profile_2026_04_26.md").write_text("old", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(PROJECT_ROOT / "scripts" / "docs_archive_sweep.py"),
            "--docs-root",
            str(docs_root),
            "--current-date",
            "2026-05-11",
            "--dry-run",
            "--format",
            "json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["dry_run"] is True
    assert payload["moves"][0]["target"] == "archive/2026-04/timing_profile_2026_04_26.md"


def test_docs_readme_declares_governance_sections():
    content = (PROJECT_ROOT / "docs" / "README.md").read_text(encoding="utf-8")

    assert "当前生效" in content
    assert "本月工作" in content
    assert "历史归档" in content
    assert "scripts/docs_archive_sweep.py --dry-run" in content
