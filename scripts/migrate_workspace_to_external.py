"""Plan or move workspace-* directories to an external storage root."""
from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path
from typing import Any


def plan_workspace_migration(
    project_root: str | Path,
    target_root: str | Path,
    *,
    include_sample: bool = False,
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    target = Path(target_root).resolve()
    moves = []
    for source in sorted(root.glob("workspace-*")):
        if not source.is_dir():
            continue
        if source.name == "workspace-sample" and not include_sample:
            continue
        moves.append(
            {
                "source": str(source),
                "target": str(target / source.name),
                "status": "target_exists" if (target / source.name).exists() else "planned",
            }
        )
    return {
        "summary": {
            "mode": "dry-run",
            "project_root": str(root),
            "target_root": str(target),
            "move_count": len([move for move in moves if move["status"] == "planned"]),
            "skip_count": len([move for move in moves if move["status"] != "planned"]),
        },
        "moves": moves,
    }


def apply_workspace_migration(plan: dict[str, Any]) -> dict[str, Any]:
    target_root = Path(plan["summary"]["target_root"])
    target_root.mkdir(parents=True, exist_ok=True)
    applied = []
    for move in plan["moves"]:
        source = Path(move["source"])
        target = Path(move["target"])
        if move["status"] != "planned" or not source.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(target))
        move["status"] = "moved"
        applied.append(move)
    plan["summary"]["mode"] = "apply"
    plan["summary"]["applied_count"] = len(applied)
    return plan


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Migrate workspace-* directories out of repo")
    parser.add_argument("--project-root", default=".")
    parser.add_argument(
        "--target-root",
        default=os.environ.get("PECKER_WORKSPACE_ROOT", ""),
        help="External workspace storage root, or PECKER_WORKSPACE_ROOT",
    )
    parser.add_argument("--include-sample", action="store_true")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Only print planned moves")
    mode.add_argument("--apply", action="store_true", help="Move directories")
    args = parser.parse_args(argv)
    if not args.target_root:
        parser.error("--target-root or PECKER_WORKSPACE_ROOT is required")
    plan = plan_workspace_migration(
        args.project_root,
        args.target_root,
        include_sample=args.include_sample,
    )
    if args.apply:
        plan = apply_workspace_migration(plan)
    print(json.dumps(plan, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
