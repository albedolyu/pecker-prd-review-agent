"""Read-only retention report for Pecker deployment data."""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

try:
    from scripts.retention_sweep import RetentionConfig, plan_retention_sweep
except ModuleNotFoundError:  # direct script execution: python scripts/retention_report.py
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from retention_sweep import RetentionConfig, plan_retention_sweep


def build_retention_report(
    project_root: str | Path = ".",
    *,
    config: RetentionConfig | None = None,
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    cfg = config or RetentionConfig.from_env()
    actions = plan_retention_sweep(root, config=cfg)
    live_sizes = _live_sizes(root)
    return {
        "project_root": str(root),
        "config": asdict(cfg),
        "summary": {
            "mode": "report",
            "action_count": len(actions),
            "reclaimable_bytes": sum(action.bytes for action in actions),
            "live_bytes": sum(live_sizes.values()),
        },
        "live_sizes": live_sizes,
        "actions": [asdict(action) for action in actions],
    }


def _live_sizes(root: Path) -> dict[str, int]:
    return {
        "drafts": _path_size(root / ".pecker_drafts"),
        "event_store": _path_size(root / "event_store.jsonl"),
        "eval_reports": _path_size(root / "eval_reports"),
        "logs": _path_size(root / "logs"),
        "finding_outcomes": _path_size(root / "review" / "finding_outcomes.db"),
    }


def _path_size(path: Path) -> int:
    if not path.exists():
        return 0
    if path.is_file():
        return path.stat().st_size
    return sum(child.stat().st_size for child in path.rglob("*") if child.is_file())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pecker retention report")
    parser.add_argument("--project-root", default=".", help="Pecker project root")
    parser.add_argument("--format", choices=["json", "text"], default="text")
    args = parser.parse_args(argv)
    report = build_retention_report(args.project_root)
    if args.format == "json":
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(
            "retention report "
            f"actions={report['summary']['action_count']} "
            f"reclaimable={report['summary']['reclaimable_bytes']} bytes "
            f"live={report['summary']['live_bytes']} bytes"
        )
        for action in report["actions"]:
            target = f" -> {action['target']}" if action.get("target") else ""
            print(f"- [{action['category']}] {action['action']} {action['path']}{target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
