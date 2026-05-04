from __future__ import annotations

import json


def test_safe_file_label_handles_chinese_and_spaces():
    from scripts.run_review_case import safe_file_label

    assert safe_file_label("积分抵扣支付 v2") == "case_v2"
    assert safe_file_label("labor arbitration v5.1") == "labor_arbitration_v5_1"


def test_render_markdown_marks_partial_and_recovered():
    from scripts.run_review_case import render_markdown

    payload = {
        "case_label": "demo",
        "workspace": "C:/ws",
        "prd_files": ["a.md"],
        "elapsed_s": 12.3,
        "merged_count": 2,
        "verification_summary": {"total": 2, "verified": 2},
        "completion": {
            "status": "partial",
            "failed_workers": ["structure"],
            "recovered_workers": ["quality"],
        },
        "worker_events": [
            {"dim": "quality", "model": "gpt-5.5", "items": 2, "duration_ms": 1000, "error": None},
            {"dim": "structure", "model": None, "items": 0, "duration_ms": None, "error": "timeout"},
        ],
        "items": [],
    }

    text = render_markdown(payload)

    assert "Completion: `partial`" in text
    assert "Recovered workers: `quality`" in text
    assert "Failed workers: `structure`" in text


def test_write_reports_uses_ascii_filename(tmp_path):
    from scripts.run_review_case import write_reports

    payload = {
        "case_label": "积分抵扣支付",
        "file_label": "积分抵扣支付",
        "workspace": "C:/ws",
        "prd_files": ["prd.md"],
        "elapsed_s": 1.0,
        "merged_count": 0,
        "worker_events": [],
        "items": [],
        "completion": {"status": "complete", "failed_workers": [], "recovered_workers": []},
    }

    paths = write_reports(payload, tmp_path, timestamp="20260505_120000")

    assert paths["json"].name == "gpt_route_case_20260505_120000.json"
    assert paths["md"].name == "gpt_route_case_20260505_120000.md"
    assert paths["pm_revision"].name == "gpt_route_case_20260505_120000_pm_revision.md"
    saved = json.loads(paths["json"].read_text(encoding="utf-8"))
    assert saved["case_label"] == "积分抵扣支付"
    assert saved["report_paths"]["pm_revision"].endswith("_pm_revision.md")


def _pm_payload(items):
    return {
        "case_label": "demo",
        "workspace": "C:/ws",
        "prd_files": ["prd.md"],
        "elapsed_s": 10.0,
        "merged_count": len(items),
        "completion": {"status": "complete", "failed_workers": [], "recovered_workers": []},
        "verification_summary": {"total": len(items), "verified": len(items), "reliability": 1.0},
        "worker_events": [],
        "items": [
            {
                "id": item.get("id", f"R-{idx:03d}"),
                "dimension": item["dimension"],
                "rule_id": item.get("rule_id", "V-01"),
                "severity": item["severity"],
                "title": item["title"],
                "location": item.get("location", "1.1"),
                "suggestion": item.get("suggestion", "补充验收标准。"),
                "confidence": item.get("confidence", 0.8),
                "verification_status": "verified",
            }
            for idx, item in enumerate(items, 1)
        ],
        "verified_items": [
            {
                "id": item.get("id", f"R-{idx:03d}"),
                "dimension": item["dimension"],
                "rule_id": item.get("rule_id", "V-01"),
                "severity": item["severity"],
                "issue": item["title"],
                "location": item.get("location", "1.1"),
                "suggestion": item.get("suggestion", "补充验收标准。"),
                "confidence_score": item.get("confidence", 0.8),
                "verification_status": "verified",
            }
            for idx, item in enumerate(items, 1)
        ],
    }


def test_build_pm_summary_recommends_revision_for_blocking_items():
    from scripts.run_review_case import build_pm_summary

    payload = _pm_payload([
        {"dimension": "结构层", "severity": "must", "title": "缺少异常流。"},
        {"dimension": "质量层", "severity": "should", "title": "验收标准不完整。"},
    ])

    summary = build_pm_summary(payload)

    assert summary["verdict"] == "建议补充后再评审"
    assert summary["blocking_count"] == 1
    assert summary["rework_risk"] == "中"
    assert summary["priority_items"][0]["id"] == "R-001"
    assert "可直接粘贴" in summary["priority_items"][0]["prd_patch_label"]


def test_build_pm_view_separates_pm_and_engineering_items():
    from scripts.run_review_case import build_pm_view

    payload = _pm_payload([
        {"dimension": "结构层", "severity": "must", "title": "缺少异常流。"},
        {"dimension": "AI Coding 友好度", "severity": "should", "title": "接口字段不利于实现。"},
    ])

    view = build_pm_view(payload)

    assert view["pm_count"] == 1
    assert view["engineering_count"] == 1
    assert view["pm_items"][0]["dimension"] == "结构层"
    assert view["engineering_items"][0]["dimension"] == "AI Coding 友好度"


def test_output_change_summary_explains_item_and_rule_drop():
    from scripts.run_review_case import output_change_summary

    previous = _pm_payload([
        {"dimension": "结构层", "severity": "must", "title": f"old {idx}", "rule_id": f"R-{idx}"}
        for idx in range(10)
    ])
    current = _pm_payload([
        {"dimension": "结构层", "severity": "must", "title": f"new {idx}", "rule_id": f"R-{idx}"}
        for idx in range(7)
    ])

    change = output_change_summary(current, previous)

    assert change["status"] == "drop_risk"
    assert change["item_delta"] == -3
    assert change["item_ratio"] == 0.7
    assert "明显变少" in change["pm_explanation"]


def test_pm_revision_markdown_contains_paste_ready_suggestions():
    from scripts.run_review_case import render_pm_revision_markdown

    payload = _pm_payload([
        {
            "dimension": "质量层",
            "severity": "must",
            "title": "验收标准不完整。",
            "location": "3.2",
            "suggestion": "补充成功、失败、无权限三类验收标准。",
        },
    ])

    text = render_pm_revision_markdown(payload)

    assert "# PM 建议修订版 - demo" in text
    assert "3.2" in text
    assert "补充成功、失败、无权限三类验收标准。" in text


def test_render_markdown_includes_pm_sections():
    from scripts.run_review_case import enrich_pm_payload, render_markdown

    payload = enrich_pm_payload(_pm_payload([
        {"dimension": "结构层", "severity": "must", "title": "缺少异常流。"},
    ]))

    text = render_markdown(payload)

    assert "## PM 结论卡" in text
    assert "## PM 优先修改清单" in text
    assert "## PM 反馈标签" in text


def test_build_testability_summary_blocks_case_generation_when_acceptance_is_missing():
    from scripts.run_review_case import build_testability_summary

    payload = _pm_payload([
        {
            "dimension": "质量层",
            "severity": "must",
            "title": "缺少验收标准，无法判断成功和失败结果。",
            "location": "4.1",
            "suggestion": "补充成功、失败、无权限三类验收标准。",
        },
        {
            "dimension": "结构层",
            "severity": "should",
            "title": "边界条件描述较弱。",
        },
    ])

    summary = build_testability_summary(payload)

    assert summary["testability_verdict"] == "blocked"
    assert summary["blocking_gap_count"] == 1
    assert summary["estimated_case_coverage"] == "低"
    assert summary["untestable_gaps"][0]["handoff_type"] == "blocking_test_generation"


def test_build_zhiqu_handoff_contains_scenario_matrix_and_traceability():
    from scripts.run_review_case import build_zhiqu_handoff

    payload = _pm_payload([
        {
            "id": "R-100",
            "dimension": "质量层",
            "severity": "must",
            "title": "缺少异常流，无法生成失败路径用例。",
            "location": "3.2",
            "suggestion": "补充失败、超时、无权限三类异常处理。",
            "rule_id": "V-09",
        },
    ])
    payload["review_id"] = "review_demo"
    payload["prd_hash"] = "abc123"

    handoff = build_zhiqu_handoff(payload)

    assert handoff["target_agent"] == "zhiqu_test_case_agent"
    assert handoff["review_id"] == "review_demo"
    assert handoff["source_trace"]["prd_hash"] == "abc123"
    assert handoff["testability_verdict"] == "blocked"
    assert handoff["scenario_matrix"][0]["source_item_id"] == "R-100"
    assert handoff["traceability"][0]["review_item_id"] == "R-100"


def test_write_reports_emits_zhiqu_handoff_json(tmp_path):
    from scripts.run_review_case import write_reports

    payload = _pm_payload([
        {
            "dimension": "质量层",
            "severity": "must",
            "title": "缺少验收标准。",
        },
    ])

    paths = write_reports(payload, tmp_path, timestamp="20260505_130000")

    assert paths["zhiqu_handoff"].name == "gpt_route_demo_20260505_130000_zhiqu_handoff.json"
    handoff = json.loads(paths["zhiqu_handoff"].read_text(encoding="utf-8"))
    saved = json.loads(paths["json"].read_text(encoding="utf-8"))
    assert handoff["target_agent"] == "zhiqu_test_case_agent"
    assert saved["report_paths"]["zhiqu_handoff"].endswith("_zhiqu_handoff.json")
