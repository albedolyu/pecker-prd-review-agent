from __future__ import annotations

from pathlib import Path

import pytest


def _make_workspace(root: Path, name: str, *, owner: str = "tester") -> Path:
    ws = root / name
    (ws / "prd").mkdir(parents=True, exist_ok=True)
    (ws / "wiki").mkdir(parents=True, exist_ok=True)
    (ws / "prd" / "demo.md").write_text("# demo\n", encoding="utf-8")
    (ws / "wiki" / "index.md").write_text("# wiki\n", encoding="utf-8")
    (ws / ".pecker_acl.json").write_text(
        f'{{"owner":"{owner}","readers":[]}}',
        encoding="utf-8",
    )
    return ws


@pytest.mark.asyncio
async def test_workspace_discovery_reads_project_root_by_default(tmp_path: Path, monkeypatch) -> None:
    from api.routes.workspaces import list_workspaces

    monkeypatch.delenv("PECKER_WORKSPACE_ROOT", raising=False)
    _make_workspace(tmp_path, "workspace-alpha")
    _make_workspace(tmp_path, "workspace-sample")

    rows = await list_workspaces(project_root=tmp_path, user={"reviewer": "tester"})

    assert [row.name for row in rows] == ["workspace-alpha", "workspace-sample"]
    assert rows[0].prd_count == 1
    assert rows[0].wiki_page_count == 1


@pytest.mark.asyncio
async def test_workspace_discovery_uses_external_root_but_keeps_sample(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from api.routes.workspaces import list_workspaces

    external = tmp_path / "external"
    project = tmp_path / "project"
    _make_workspace(external, "workspace-alpha")
    _make_workspace(project, "workspace-sample")
    monkeypatch.setenv("PECKER_WORKSPACE_ROOT", str(external))

    rows = await list_workspaces(project_root=project, user={"reviewer": "tester"})

    by_name = {row.name: row for row in rows}
    assert sorted(by_name) == ["workspace-alpha", "workspace-sample"]
    assert by_name["workspace-alpha"].path == str(external / "workspace-alpha")
    assert by_name["workspace-sample"].path == str(project / "workspace-sample")


def test_get_workspace_dir_resolves_external_root(tmp_path: Path, monkeypatch) -> None:
    import api.deps as deps

    external = tmp_path / "external"
    project = tmp_path / "project"
    _make_workspace(external, "workspace-alpha")
    _make_workspace(project, "workspace-sample")
    monkeypatch.setattr(deps, "_PROJECT_ROOT", project)
    monkeypatch.setenv("PECKER_WORKSPACE_ROOT", str(external))

    assert deps.get_workspace_dir("workspace-alpha") == external / "workspace-alpha"
    assert deps.get_workspace_dir("workspace-sample") == project / "workspace-sample"


def test_migrate_workspace_to_external_dry_run_keeps_files_in_place(tmp_path: Path) -> None:
    from scripts.migrate_workspace_to_external import plan_workspace_migration

    project = tmp_path / "project"
    target = tmp_path / "external"
    alpha = _make_workspace(project, "workspace-alpha")
    _make_workspace(project, "workspace-sample")

    plan = plan_workspace_migration(project, target)

    assert plan["summary"]["mode"] == "dry-run"
    assert plan["summary"]["move_count"] == 1
    assert plan["moves"][0]["source"] == str(alpha)
    assert plan["moves"][0]["target"] == str(target / "workspace-alpha")
    assert alpha.exists()
