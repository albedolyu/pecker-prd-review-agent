"""Rule impact evidence report.

Compares PM-confirmed ground-truth decisions across two windows and attaches the
current rule_performance_history impact_score for each touched rule.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


def build_rule_impact_report(
    project_root: str | Path,
    *,
    before_start: str,
    before_end: str,
    after_start: str,
    after_end: str,
) -> dict[str, Any]:
    root = Path(project_root)
    windows = {
        "before": (_parse_date(before_start), _parse_date(before_end)),
        "after": (_parse_date(after_start), _parse_date(after_end)),
    }
    records = list(_iter_ground_truth_items(root))
    current_scores = _load_current_rule_scores(root)
    buckets: dict[str, dict[str, Any]] = defaultdict(_empty_rule_bucket)

    for record in records:
        window_name = _window_name(record["timestamp"], windows)
        if not window_name:
            continue
        rule_id = record["rule_id"]
        if not rule_id:
            continue
        bucket = buckets[rule_id]
        bucket["rule_id"] = rule_id
        bucket["rule_name"] = current_scores.get(rule_id, {}).get("name", "")
        _add_action(bucket[window_name], record)

    rules = []
    for rule_id, bucket in sorted(buckets.items()):
        score_info = current_scores.get(rule_id, {})
        bucket["impact_score_current"] = score_info.get("impact_score")
        if not bucket["rule_name"]:
            bucket["rule_name"] = score_info.get("name", "")
        for window in ("before", "after"):
            reasons = bucket[window].pop("_reject_reasons", Counter())
            bucket[window]["reject_reason_category"] = (
                reasons.most_common(1)[0][0] if reasons else ""
            )
        rules.append(bucket)

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "windows": {
            "before": {"start": before_start, "end": before_end},
            "after": {"start": after_start, "end": after_end},
        },
        "summary": {
            "before_total": sum(_rule_total(row["before"]) for row in rules),
            "after_total": sum(_rule_total(row["after"]) for row in rules),
            "rule_count": len(rules),
        },
        "rules": rules,
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# 规则调权效果报告",
        "",
        f"- 生成时间: {report.get('generated_at', '')}",
        f"- 对照窗口: {report['windows']['before']['start']} ~ {report['windows']['before']['end']}",
        f"- 观察窗口: {report['windows']['after']['start']} ~ {report['windows']['after']['end']}",
        f"- 命中规则数: {report['summary']['rule_count']}",
        f"- 样本量: before={report['summary']['before_total']} / after={report['summary']['after_total']}",
        "",
        "| rule_id | 规则 | before 确认/驳回/漏检 | after 确认/驳回/漏检 | 当前 impact_score | after 主要驳回原因 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for row in report.get("rules", []):
        before = row["before"]
        after = row["after"]
        lines.append(
            "| {rule_id} | {name} | {bc}/{br}/{bm} | {ac}/{ar}/{am} | {score} | {reason} |".format(
                rule_id=row["rule_id"],
                name=row.get("rule_name") or "",
                bc=before["confirmed"],
                br=before["rejected"],
                bm=before["missed"],
                ac=after["confirmed"],
                ar=after["rejected"],
                am=after["missed"],
                score="" if row.get("impact_score_current") is None else row["impact_score_current"],
                reason=after.get("reject_reason_category") or "",
            )
        )
    return "\n".join(lines) + "\n"


def write_rule_impact_report(report: dict[str, Any], output_dir: str | Path) -> Path:
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    week = _week_label(datetime.now())
    path = out_dir / f"rule_impact_{week}.md"
    path.write_text(render_markdown(report), encoding="utf-8")
    return path


def _empty_rule_bucket() -> dict[str, Any]:
    return {
        "rule_id": "",
        "rule_name": "",
        "before": {"confirmed": 0, "rejected": 0, "missed": 0, "_reject_reasons": Counter()},
        "after": {"confirmed": 0, "rejected": 0, "missed": 0, "_reject_reasons": Counter()},
        "impact_score_current": None,
    }


def _rule_total(row: dict[str, Any]) -> int:
    return int(row.get("confirmed", 0)) + int(row.get("rejected", 0)) + int(row.get("missed", 0))


def _add_action(bucket: dict[str, Any], record: dict[str, Any]) -> None:
    action = record["action"]
    if action in {"accept", "edit"}:
        bucket["confirmed"] += 1
    elif action == "reject":
        bucket["rejected"] += 1
        reason = record.get("reason_category") or "未填写"
        bucket["_reject_reasons"][reason] += 1
    elif action == "missed" or record.get("missed"):
        bucket["missed"] += 1


def _iter_ground_truth_items(root: Path):
    gt_dir = root / "eval" / "ground_truth"
    if not gt_dir.is_dir():
        return
    for path in sorted(gt_dir.glob("*.json")):
        payload = _load_json(path)
        if not isinstance(payload, dict):
            continue
        timestamp = _payload_timestamp(payload, path)
        items = payload.get("items")
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            yield {
                "timestamp": timestamp,
                "rule_id": str(item.get("rule_id") or item.get("id") or "").strip(),
                "action": str(item.get("action") or "").strip(),
                "reason_category": str(item.get("reason_category") or "").strip(),
                "missed": bool(item.get("missed")),
            }


def _load_current_rule_scores(root: Path) -> dict[str, dict[str, Any]]:
    scores: dict[str, dict[str, Any]] = {}
    for path in sorted(root.glob("workspace*/output/rule_performance_history.json")):
        payload = _load_json(path)
        if not isinstance(payload, dict):
            continue
        for rule_id, entry in payload.items():
            if rule_id == "__meta__" or not isinstance(entry, dict):
                continue
            total = int((entry.get("stats") or {}).get("total") or 0)
            previous = scores.get(rule_id)
            if previous and previous.get("_total", 0) > total:
                continue
            scores[rule_id] = {
                "name": entry.get("name") or "",
                "impact_score": entry.get("impact_score"),
                "_total": total,
            }
    return scores


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None


def _payload_timestamp(payload: dict[str, Any], path: Path) -> datetime:
    value = payload.get("timestamp")
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            pass
    match = re.search(r"_(\d{9,})\.json$", path.name)
    if match:
        return datetime.fromtimestamp(int(match.group(1)))
    return datetime.fromtimestamp(path.stat().st_mtime)


def _window_name(timestamp: datetime, windows: dict[str, tuple[datetime, datetime]]) -> str:
    for name, (start, end) in windows.items():
        if start <= timestamp < end:
            return name
    return ""


def _parse_date(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _week_label(dt: datetime) -> str:
    year, week, _ = dt.isocalendar()
    return f"{year}-W{week:02d}"


def _default_windows() -> dict[str, str]:
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    after_start = today - timedelta(days=7)
    before_start = after_start - timedelta(days=7)
    return {
        "before_start": before_start.date().isoformat(),
        "before_end": after_start.date().isoformat(),
        "after_start": after_start.date().isoformat(),
        "after_end": today.date().isoformat(),
    }


def main(argv: list[str] | None = None) -> int:
    defaults = _default_windows()
    parser = argparse.ArgumentParser(description="Build rule impact evidence report")
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--before-start", default=defaults["before_start"])
    parser.add_argument("--before-end", default=defaults["before_end"])
    parser.add_argument("--after-start", default=defaults["after_start"])
    parser.add_argument("--after-end", default=defaults["after_end"])
    parser.add_argument("--output-dir", default="eval_reports")
    parser.add_argument("--format", choices=["json", "markdown"], default="markdown")
    args = parser.parse_args(argv)
    report = build_rule_impact_report(
        args.project_root,
        before_start=args.before_start,
        before_end=args.before_end,
        after_start=args.after_start,
        after_end=args.after_end,
    )
    if args.format == "json":
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        path = write_rule_impact_report(report, Path(args.project_root) / args.output_dir)
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
