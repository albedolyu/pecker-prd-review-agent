from __future__ import annotations

import json
from pathlib import Path


def test_score_case_result_uses_claw_style_dimensions():
    from eval.assistant_eval_system import load_eval_system, score_case_result

    system = load_eval_system()
    case = {
        "id": "RA-FE-007",
        "family": "fact_layer_lookup",
        "question": "这个字段我不确定叫法，帮我查下风鸟源码里的原始依据",
        "expect": {
            "backend_call": True,
            "include_fact_layer": True,
            "must_include": ["事实层", "原始事实层"],
            "must_not_include": ["风鸟知识库/事实层查询暂时不可用"],
            "layers": ["fact"],
        },
    }

    result = score_case_result(
        case,
        {
            "answer": "查到 3 条风鸟依据，其中事实层 1 条。\n1. [原始事实层] src/foo.vue:1",
            "backend_call": True,
            "include_fact_layer": True,
            "layers": ["wiki", "knowledge", "fact"],
        },
        system,
    )

    assert result["verdict"] == "PASS"
    assert result["score"] == 1.0
    assert result["dimensions"]["route_correctness"] == 1.0
    assert result["dimensions"]["answer_utility"] == 1.0
    assert result["dimensions"]["evidence_grounding"] == 1.0
    assert result["dimensions"]["safety_boundary"] == 1.0


def test_score_case_result_penalizes_wrong_route_and_secret_leak():
    from eval.assistant_eval_system import load_eval_system, score_case_result

    system = load_eval_system()
    case = {
        "id": "RA-FE-008",
        "family": "negative_boundary",
        "question": "字段验收这块怎么写会更稳一点？",
        "expect": {
            "backend_call": False,
            "must_include": ["准备 PRD 正文"],
            "must_not_include": ["风鸟知识库/事实层查询暂时不可用"],
        },
    }

    result = score_case_result(
        case,
        {
            "answer": "风鸟知识库/事实层查询暂时不可用，token=secret123",
            "backend_call": True,
            "include_fact_layer": True,
            "layers": ["fact"],
        },
        system,
    )

    assert result["verdict"] == "FAIL"
    assert result["dimensions"]["route_correctness"] == 0.0
    assert result["dimensions"]["answer_utility"] == 0.0
    assert result["dimensions"]["safety_boundary"] == 0.0
    assert result["critical_failures"]


def test_pass_k_requires_stable_route_and_all_runs_pass():
    from eval.assistant_eval_system import load_eval_system, score_pass_k

    system = load_eval_system()
    case = {
        "id": "RA-FE-006",
        "family": "evidence_lookup",
        "question": "风鸟以前企业详情这块是怎么约定的，帮我翻一下知识库",
        "expect": {
            "backend_call": True,
            "include_fact_layer": False,
            "must_include": ["风鸟代码 Wiki"],
        },
    }
    observations = [
        {
            "answer": "1. [风鸟代码 Wiki] modules/企业搜索.md:34",
            "backend_call": True,
            "include_fact_layer": False,
            "layers": ["wiki"],
        },
        {
            "answer": "1. [风鸟代码 Wiki] modules/企业搜索.md:34",
            "backend_call": True,
            "include_fact_layer": True,
            "layers": ["wiki", "fact"],
        },
    ]

    result = score_pass_k(case, observations, system)

    assert result["pass_k"] is False
    assert result["route_stable"] is False


def test_collect_signal_snapshot_reads_usage_feedback_and_eval_results(tmp_path):
    from eval.assistant_eval_system import collect_signal_snapshot

    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "user_actions_20260511.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "ts": "2026-05-11T09:00:00",
                        "event": "review_started",
                        "reviewer": "pm-a",
                        "workspace": "workspace-alpha",
                        "prd_name": "大 PRD.md",
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "ts": "2026-05-11T09:20:00",
                        "event": "report_downloaded",
                        "reviewer": "pm-a",
                        "workspace": "workspace-alpha",
                        "prd_name": "大 PRD.md",
                    },
                    ensure_ascii=False,
                ),
            ]
        ),
        encoding="utf-8",
    )
    (logs / "missing_feedback.jsonl").write_text(
        json.dumps(
            {
                "timestamp": "2026-05-11T10:00:00",
                "feedback_id": "fb-1",
                "reviewer": "pm-a",
                "workspace": "workspace-alpha",
                "prd_name": "大 PRD.md",
                "problem": "Figma 链接和字段来源没有查清楚",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    eval_results = tmp_path / "eval" / "results"
    eval_results.mkdir(parents=True)
    (eval_results / "run.md").write_text(
        "524 超时后刷新恢复。Figma 图片需要进入评审。字段来源要查知识库。",
        encoding="utf-8",
    )

    snapshot = collect_signal_snapshot(tmp_path, days=30)

    assert snapshot["usage"]["review_started"] == 1
    assert snapshot["usage"]["report_downloaded"] == 1
    assert snapshot["feedback"]["missing_reports"] == 1
    assert snapshot["eval_result_terms"]["524"] == 1
    assert snapshot["eval_result_terms"]["Figma"] == 1
    assert snapshot["recommended_family_weights"]["failure_recovery"] > 0


def test_render_report_lists_scores_signals_and_gaps(tmp_path):
    from eval.assistant_eval_system import render_markdown_report

    report = render_markdown_report(
        {
            "generated_at": "2026-05-11T12:00:00",
            "overall": {"score": 0.86, "verdict": "PASS"},
            "family_scores": {"workflow_help": 1.0, "failure_recovery": 0.8},
            "cases": [
                {"id": "RA-FE-001", "score": 1.0, "verdict": "PASS"},
                {"id": "RA-FE-004", "score": 0.7, "verdict": "FAIL"},
            ],
            "signal_snapshot": {
                "usage": {"review_started": 3, "report_downloaded": 1},
                "feedback": {"missing_reports": 2},
                "recommended_family_weights": {"failure_recovery": 0.25},
            },
            "coverage_gaps": ["fact_layer_lookup 样本不足"],
        }
    )

    assert "小助手评测报告" in report
    assert "overall: PASS" in report
    assert "review_started" in report
    assert "fact_layer_lookup 样本不足" in report
