from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_rule_perf_impact_report_compares_two_windows(tmp_path: Path) -> None:
    from scripts.rule_perf_impact_report import build_rule_impact_report

    _write_json(
        tmp_path / "eval" / "ground_truth" / "before.json",
        {
            "timestamp": int(datetime(2026, 5, 1, 10, 0).timestamp()),
            "items": [
                {"id": "R-1", "rule_id": "V-01", "action": "accept"},
                {
                    "id": "R-2",
                    "rule_id": "V-02",
                    "action": "reject",
                    "reason_category": "false_positive",
                },
            ],
        },
    )
    _write_json(
        tmp_path / "eval" / "ground_truth" / "after.json",
        {
            "timestamp": int(datetime(2026, 5, 8, 10, 0).timestamp()),
            "items": [
                {"id": "R-3", "rule_id": "V-01", "action": "edit"},
                {"id": "R-4", "rule_id": "V-01", "action": "missed"},
                {
                    "id": "R-5",
                    "rule_id": "V-02",
                    "action": "reject",
                    "reason_category": "rule_too_strict",
                },
            ],
        },
    )
    _write_json(
        tmp_path / "workspace-alpha" / "output" / "rule_performance_history.json",
        {
            "V-01": {
                "name": "结构层",
                "impact_score": 0.71,
                "stats": {"confirmed": 3, "rejected": 0, "missed": 1, "total": 4},
            },
            "V-02": {
                "name": "体验层",
                "impact_score": 0.31,
                "stats": {"confirmed": 0, "rejected": 2, "missed": 0, "total": 2},
                "reject_by_reason": {"rule_too_strict": 1},
            },
        },
    )

    report = build_rule_impact_report(
        tmp_path,
        before_start="2026-05-01",
        before_end="2026-05-02",
        after_start="2026-05-08",
        after_end="2026-05-09",
    )

    by_rule = {row["rule_id"]: row for row in report["rules"]}
    assert by_rule["V-01"]["before"]["confirmed"] == 1
    assert by_rule["V-01"]["after"]["confirmed"] == 1
    assert by_rule["V-01"]["after"]["missed"] == 1
    assert by_rule["V-01"]["impact_score_current"] == 0.71
    assert by_rule["V-02"]["after"]["reject_reason_category"] == "rule_too_strict"
    assert report["summary"]["after_total"] == 3


def test_rule_impact_markdown_report_is_written(tmp_path: Path) -> None:
    from scripts.rule_perf_impact_report import render_markdown, write_rule_impact_report

    report = {
        "generated_at": "2026-05-11T10:00:00",
        "windows": {
            "before": {"start": "2026-05-01", "end": "2026-05-02"},
            "after": {"start": "2026-05-08", "end": "2026-05-09"},
        },
        "summary": {"before_total": 1, "after_total": 2, "rule_count": 1},
        "rules": [
            {
                "rule_id": "V-01",
                "rule_name": "结构层",
                "before": {"confirmed": 1, "rejected": 0, "missed": 0},
                "after": {
                    "confirmed": 1,
                    "rejected": 1,
                    "missed": 0,
                    "reject_reason_category": "model_noise",
                },
                "impact_score_current": 0.42,
            }
        ],
    }

    md = render_markdown(report)
    path = write_rule_impact_report(report, tmp_path / "eval_reports")

    assert "规则调权效果报告" in md
    assert "| V-01 | 结构层 |" in md
    assert path.name.startswith("rule_impact_")
    assert "model_noise" in path.read_text(encoding="utf-8")


def test_rule_impact_golden_manifest_locks_small_costed_set(tmp_path: Path) -> None:
    from eval.route_eval.rule_impact_golden import build_golden_plan

    manifest = tmp_path / "eval" / "route_eval" / "datasets" / "data" / "business_prd_gt" / "manifest.json"
    _write_json(
        manifest,
        {
            "records": [
                {
                    "id": "alpha",
                    "workspace": "workspace-alpha",
                    "prd_path": "prd/alpha.md",
                    "ground_truth": [{"id": "GT-1"}, {"id": "GT-2"}],
                },
                {
                    "id": "beta",
                    "workspace": "workspace-beta",
                    "prd_path": "prd/beta.md",
                    "ground_truth": [{"id": "GT-3"}],
                },
            ]
        },
    )

    plan = build_golden_plan(tmp_path, limit=10)

    assert plan["name"] == "rule_impact_golden"
    assert len(plan["cases"]) == 2
    assert plan["run_modes"] == ["current_impact_score", "neutral_baseline_0_5"]
    assert plan["estimated_worker_calls"] == 16
    assert plan["cases"][0]["ground_truth_count"] == 2


def test_admin_usage_loads_recent_rule_impact_reports(tmp_path: Path) -> None:
    from api.routes.admin_usage import _load_rule_impact_reports

    report_dir = tmp_path / "eval_reports"
    (report_dir / "rule_impact_2026-W19.md").parent.mkdir(parents=True, exist_ok=True)
    (report_dir / "rule_impact_2026-W19.md").write_text(
        "# 规则调权效果报告\n\nsummary A\n",
        encoding="utf-8",
    )

    reports = _load_rule_impact_reports(tmp_path, limit=4)

    assert reports[0]["filename"] == "rule_impact_2026-W19.md"
    assert reports[0]["title"] == "规则调权效果报告"
