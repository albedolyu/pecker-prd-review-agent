"""Data retention sweep for Pecker internal beta deployments.

Default mode is dry-run. Use ``--apply`` to archive or remove live data.
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import shutil
import sqlite3
import tarfile
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable


@dataclass(frozen=True)
class RetentionConfig:
    draft_days: int = 30
    eval_report_days: int = 90
    log_days: int = 14
    finding_days: int = 180
    event_store_max_mb: float = 500
    trash_days: int = 7

    @classmethod
    def from_env(cls) -> "RetentionConfig":
        return cls(
            draft_days=_env_int("PECKER_RETENTION_DRAFT_DAYS", 30),
            eval_report_days=_env_int("PECKER_RETENTION_EVAL_REPORT_DAYS", 90),
            log_days=_env_int("PECKER_RETENTION_LOG_DAYS", 14),
            finding_days=_env_int("PECKER_RETENTION_FINDING_DAYS", 180),
            event_store_max_mb=_env_float("PECKER_RETENTION_EVENT_STORE_MAX_MB", 500),
            trash_days=_env_int("PECKER_RETENTION_TRASH_DAYS", 7),
        )


@dataclass
class RetentionAction:
    category: str
    action: str
    path: str
    bytes: int = 0
    target: str | None = None
    detail: str | None = None


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    value = os.environ.get(name)
    if not value:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _now() -> datetime:
    return datetime.now()


def _is_older_than(path: Path, *, days: int, now: datetime) -> bool:
    cutoff = now - timedelta(days=days)
    return datetime.fromtimestamp(path.stat().st_mtime) < cutoff


def _safe_relative(path: Path, root: Path) -> Path:
    return path.resolve().relative_to(root.resolve())


def _trash_target(root: Path, path: Path, run_id: str) -> Path:
    return root / ".trash" / "retention" / run_id / _safe_relative(path, root)


def _move_to_trash(root: Path, path: Path, run_id: str) -> Path:
    target = _trash_target(root, path, run_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(path), str(target))
    return target


def _archive_tar(files: Iterable[Path], archive_path: Path) -> None:
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive_path, "w:gz") as tar:
        for path in files:
            if path.exists():
                tar.add(path, arcname=path.name)


def _action_dicts(actions: list[RetentionAction]) -> list[dict[str, Any]]:
    return [asdict(action) for action in actions]


def plan_retention_sweep(
    project_root: str | Path,
    *,
    config: RetentionConfig | None = None,
    now: datetime | None = None,
) -> list[RetentionAction]:
    root = Path(project_root)
    cfg = config or RetentionConfig.from_env()
    current = now or _now()
    actions: list[RetentionAction] = []

    draft_dir = root / ".pecker_drafts"
    if draft_dir.exists():
        for path in sorted(draft_dir.glob("*.json")):
            if path.is_file() and _is_older_than(path, days=cfg.draft_days, now=current):
                actions.append(
                    RetentionAction(
                        category="draft",
                        action="move_to_trash",
                        path=str(path),
                        bytes=path.stat().st_size,
                        detail=f"mtime>{cfg.draft_days}d",
                    )
                )

    event_store = root / "event_store.jsonl"
    max_bytes = int(cfg.event_store_max_mb * 1024 * 1024)
    if event_store.exists() and event_store.is_file() and event_store.stat().st_size > max_bytes:
        day = current.strftime("%Y%m%d")
        actions.append(
            RetentionAction(
                category="event_store",
                action="gzip_and_truncate",
                path=str(event_store),
                bytes=event_store.stat().st_size,
                target=str(root / f"event_store.{day}.jsonl.gz"),
                detail=f"size>{cfg.event_store_max_mb}MB",
            )
        )

    eval_dir = root / "eval_reports"
    if eval_dir.exists():
        for path in sorted(eval_dir.glob("*.json")):
            if path.is_file() and _is_older_than(path, days=cfg.eval_report_days, now=current):
                month = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m")
                actions.append(
                    RetentionAction(
                        category="eval_report",
                        action="tar_and_remove",
                        path=str(path),
                        bytes=path.stat().st_size,
                        target=str(eval_dir / "archive" / f"{month}.tar.gz"),
                        detail=f"mtime>{cfg.eval_report_days}d",
                    )
                )

    log_dir = root / "logs"
    if log_dir.exists():
        for path in sorted(log_dir.glob("*.log")):
            if path.is_file() and _is_older_than(path, days=cfg.log_days, now=current):
                month = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m")
                actions.append(
                    RetentionAction(
                        category="log",
                        action="tar_and_remove",
                        path=str(path),
                        bytes=path.stat().st_size,
                        target=str(log_dir / "archive" / f"{month}.tar.gz"),
                        detail=f"mtime>{cfg.log_days}d",
                    )
                )

    db = root / "review" / "finding_outcomes.db"
    old_count = _count_old_findings(db, cfg.finding_days, current)
    if old_count:
        actions.append(
            RetentionAction(
                category="finding_outcomes",
                action="archive_rows_and_vacuum",
                path=str(db),
                bytes=db.stat().st_size if db.exists() else 0,
                detail=f"{old_count} rows timestamp>{cfg.finding_days}d",
            )
        )

    trash_root = root / ".trash" / "retention"
    if trash_root.exists():
        for path in sorted(trash_root.iterdir()):
            if path.is_dir() and _is_older_than(path, days=cfg.trash_days, now=current):
                actions.append(
                    RetentionAction(
                        category="trash",
                        action="delete_trash_backup",
                        path=str(path),
                        bytes=_path_size(path),
                        detail=f"backup>{cfg.trash_days}d",
                    )
                )

    return actions


def run_retention_sweep(
    project_root: str | Path = ".",
    *,
    apply: bool = False,
    config: RetentionConfig | None = None,
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    cfg = config or RetentionConfig.from_env()
    current = _now()
    run_id = current.strftime("%Y%m%d%H%M%S")
    actions = plan_retention_sweep(root, config=cfg, now=current)

    if apply:
        _apply_actions(root, actions, cfg, current, run_id)

    return {
        "generated_at": current.isoformat(timespec="seconds"),
        "config": asdict(cfg),
        "summary": {
            "mode": "apply" if apply else "dry-run",
            "action_count": len(actions),
            "reclaimable_bytes": sum(action.bytes for action in actions),
        },
        "actions": _action_dicts(actions),
    }


def _apply_actions(
    root: Path,
    actions: list[RetentionAction],
    cfg: RetentionConfig,
    current: datetime,
    run_id: str,
) -> None:
    del cfg, current
    tar_groups: dict[str, list[RetentionAction]] = {}

    for action in actions:
        path = Path(action.path)
        if action.action == "move_to_trash" and path.exists():
            target = _move_to_trash(root, path, run_id)
            action.target = str(target)
        elif action.action == "gzip_and_truncate" and path.exists():
            target = _unique_path(Path(action.target or ""))
            with open(path, "rb") as src, gzip.open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
            path.write_text("", encoding="utf-8")
            action.target = str(target)
        elif action.action == "archive_rows_and_vacuum":
            _archive_old_findings(path, days=_extract_days(action.detail, default=180))
        elif action.action == "delete_trash_backup" and path.exists():
            shutil.rmtree(path)
        elif action.action == "tar_and_remove" and action.target:
            tar_groups.setdefault(action.target, []).append(action)

    for target, grouped in tar_groups.items():
        archive_path = _unique_path(Path(target))
        files = [Path(action.path) for action in grouped]
        _archive_tar(files, archive_path)
        for action, path in zip(grouped, files):
            if path.exists():
                path.unlink()
            action.target = str(archive_path)


def _unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.name
    for idx in range(1, 1000):
        candidate = path.with_name(f"{stem}.{idx}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"cannot allocate unique archive path for {path}")


def _path_size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    total = 0
    for child in path.rglob("*"):
        if child.is_file():
            total += child.stat().st_size
    return total


def _extract_days(detail: str | None, *, default: int) -> int:
    if not detail:
        return default
    marker = "timestamp>"
    if marker not in detail:
        return default
    tail = detail.split(marker, 1)[1]
    try:
        return int(tail.split("d", 1)[0])
    except (ValueError, IndexError):
        return default


def _count_old_findings(db_path: Path, days: int, now: datetime) -> int:
    if not db_path.exists():
        return 0
    cutoff = (now - timedelta(days=days)).isoformat(timespec="seconds")
    try:
        with sqlite3.connect(db_path) as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM finding_outcomes WHERE timestamp < ?",
                (cutoff,),
            ).fetchone()
        return int(row[0] if row else 0)
    except sqlite3.Error:
        return 0


def _archive_old_findings(db_path: Path, *, days: int) -> None:
    if not db_path.exists():
        return
    cutoff = (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")
    archived_at = datetime.now().isoformat(timespec="seconds")
    with sqlite3.connect(db_path) as conn:
        columns = [row[1] for row in conn.execute("PRAGMA table_info(finding_outcomes)")]
        if not columns:
            return
        select_cols = ", ".join(_quote_sql_name(col) for col in columns)
        archive_cols = ", ".join([_quote_sql_name(col) for col in columns] + ["archived_at"])
        conn.execute(
            f"CREATE TABLE IF NOT EXISTS findings_archive AS "
            f"SELECT {select_cols}, '' AS archived_at FROM finding_outcomes WHERE 0"
        )
        conn.execute(
            f"INSERT INTO findings_archive ({archive_cols}) "
            f"SELECT {select_cols}, ? FROM finding_outcomes WHERE timestamp < ?",
            (archived_at, cutoff),
        )
        conn.execute("DELETE FROM finding_outcomes WHERE timestamp < ?", (cutoff,))
        conn.commit()
        conn.execute("VACUUM")


def _quote_sql_name(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pecker retention sweep")
    parser.add_argument("--project-root", default=".", help="Pecker project root")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Only print planned actions")
    mode.add_argument("--apply", action="store_true", help="Apply retention actions")
    parser.add_argument("--format", choices=["json", "text"], default="text")
    args = parser.parse_args(argv)

    result = run_retention_sweep(args.project_root, apply=bool(args.apply))
    if args.format == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        _print_text(result)
    return 0


def _print_text(result: dict[str, Any]) -> None:
    summary = result["summary"]
    print(f"retention mode={summary['mode']} actions={summary['action_count']} reclaimable={summary['reclaimable_bytes']} bytes")
    for action in result["actions"]:
        target = f" -> {action['target']}" if action.get("target") else ""
        print(f"- [{action['category']}] {action['action']} {action['path']}{target}")


if __name__ == "__main__":
    raise SystemExit(main())
