"""Triage recent Goshawk final-reviewer failures from session JSONL files."""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List


def classify_failure_type(event: Dict[str, Any]) -> str:
    error = str(event.get("error") or "")
    verdict = str(event.get("verdict") or "")
    if not error and verdict != "SILENT":
        return "success"
    low = error.lower()
    if "timeout" in low or "timed out" in low:
        return "timeout"
    if "jsondecode" in low or "json decode" in low or "parse" in low or "unexpected eof" in low:
        return "json_parse"
    if "401" in low or "authentication_error" in low or "failed to authenticate" in low:
        return "auth_401"
    if "os.pathlike" in low or "winerror 206" in low or "文件名或扩展名太长" in error:
        return "filesystem_path"
    if "empty" in low or "empty output" in low or verdict == "SILENT":
        return "empty_output"
    if "os.pathlike" in low or "nonetype" in low or "winerror 206" in low or "filename or extension" in low or "文件名或扩展名太长" in error:
        return "filesystem_path"
    return "other"


def triage_goshawk_failures(project_root: Path | str, recent: int = 50) -> Dict[str, Any]:
    events = _load_recent_final_events(Path(project_root), recent=recent)
    by_type: Dict[str, Dict[str, Any]] = {}
    type_counts: Counter[str] = Counter()
    type_samples: dict[str, list[str]] = defaultdict(list)
    model_counts: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "failed": 0})

    failed = 0
    for event in events:
        failure_type = classify_failure_type(event)
        model = _model_name(event)
        model_counts[model]["total"] += 1
        if failure_type == "success":
            continue
        failed += 1
        model_counts[model]["failed"] += 1
        type_counts[failure_type] += 1
        sample = _sample_error(event)
        if sample and len(type_samples[failure_type]) < 3:
            type_samples[failure_type].append(sample)

    for failure_type, count in type_counts.most_common():
        by_type[failure_type] = {
            "count": count,
            "samples": type_samples.get(failure_type, []),
        }

    total = len(events)
    return {
        "recent": recent,
        "total": total,
        "failed": failed,
        "failure_rate": round(failed / total, 4) if total else 0.0,
        "by_type": by_type,
        "by_model": dict(sorted(model_counts.items())),
    }


def _load_recent_final_events(project_root: Path, recent: int) -> List[Dict[str, Any]]:
    session_files = sorted(
        project_root.glob("workspace-*/output/sessions/*.jsonl"),
        key=lambda path: path.name,
    )[-max(1, recent * 3):]
    events: List[Dict[str, Any]] = []
    for path in session_files:
        for event in _read_jsonl(path):
            if event.get("type") == "final_reviewer_done":
                event = dict(event)
                event["_session_file"] = str(path)
                events.append(event)
    return events[-max(1, recent):]


def _read_jsonl(path: Path) -> Iterable[Dict[str, Any]]:
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict):
                yield event
    except OSError:
        return


def _model_name(event: Dict[str, Any]) -> str:
    for key in ("model", "model_used", "route_model", "provider_model"):
        value = event.get(key)
        if value:
            return str(value)
    return "unknown"


def _sample_error(event: Dict[str, Any]) -> str:
    error = str(event.get("error") or event.get("message") or event.get("verdict") or "")
    return " ".join(error.split())[:240]


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Triage recent Goshawk failures.")
    parser.add_argument("--project-root", default=".", help="Repository root.")
    parser.add_argument("--recent", type=int, default=50, help="Recent final reviewer events to inspect.")
    parser.add_argument("--format", choices=("json", "text"), default="text")
    args = parser.parse_args(list(argv) if argv is not None else None)

    report = triage_goshawk_failures(Path(args.project_root), recent=args.recent)
    if args.format == "json":
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"Goshawk failures: {report['failed']}/{report['total']} ({report['failure_rate']:.1%})")
        for failure_type, info in report["by_type"].items():
            print(f"- {failure_type}: {info['count']}")
            for sample in info["samples"]:
                print(f"  sample: {sample}")
        print("By model:")
        for model, info in report["by_model"].items():
            print(f"- {model}: failed={info['failed']} total={info['total']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
