from __future__ import annotations


def _report(items, completion=None):
    return {
        "items": items,
        "merged_count": len(items),
        "completion": completion or {"status": "complete", "failed_workers": [], "recovered_workers": []},
    }


def test_gate_passes_when_current_keeps_coverage_above_thresholds():
    from scripts.output_regression_gate import evaluate_output_regression

    baseline = _report([
        {"dimension": "结构层", "rule_id": "S-1"},
        {"dimension": "质量层", "rule_id": "Q-1"},
        {"dimension": "AI Coding 友好度", "rule_id": "A-1"},
        {"dimension": "数据质量", "rule_id": "D-1"},
        {"dimension": "结构层", "rule_id": "S-2"},
    ])
    current = _report([
        {"dimension": "结构层", "rule_id": "S-1"},
        {"dimension": "质量层", "rule_id": "Q-1"},
        {"dimension": "AI Coding 友好度", "rule_id": "A-1"},
        {"dimension": "数据质量", "rule_id": "D-1"},
    ])

    result = evaluate_output_regression(baseline, current)

    assert result["status"] == "pass"
    assert result["metrics"]["item_ratio"] == 0.8


def test_gate_fails_when_total_items_drop_too_much():
    from scripts.output_regression_gate import evaluate_output_regression

    baseline = _report([{"dimension": "结构层", "rule_id": f"S-{i}"} for i in range(10)])
    current = _report([{"dimension": "结构层", "rule_id": f"S-{i}"} for i in range(6)])

    result = evaluate_output_regression(baseline, current)

    assert result["status"] == "fail"
    assert any(f["code"] == "ITEM_COUNT_DROP" for f in result["failures"])


def test_gate_fails_when_core_dimension_goes_zero():
    from scripts.output_regression_gate import evaluate_output_regression

    baseline = _report([
        {"dimension": "结构层", "rule_id": "S-1"},
        {"dimension": "质量层", "rule_id": "Q-1"},
        {"dimension": "AI Coding 友好度", "rule_id": "A-1"},
        {"dimension": "数据质量", "rule_id": "D-1"},
    ])
    current = _report([
        {"dimension": "结构层", "rule_id": "S-1"},
        {"dimension": "质量层", "rule_id": "Q-1"},
        {"dimension": "AI Coding 友好度", "rule_id": "A-1"},
    ])

    result = evaluate_output_regression(baseline, current)

    assert result["status"] == "fail"
    assert any(f["code"] == "DIMENSION_ZERO" and f["dimension"] == "数据质量" for f in result["failures"])


def test_gate_fails_when_rule_coverage_drops_too_much():
    from scripts.output_regression_gate import evaluate_output_regression

    baseline = _report([{"dimension": "结构层", "rule_id": f"R-{i}"} for i in range(10)])
    current = _report([{"dimension": "结构层", "rule_id": f"R-{i}"} for i in range(6)] + [
        {"dimension": "结构层", "rule_id": "R-0"},
        {"dimension": "结构层", "rule_id": "R-1"},
    ])

    result = evaluate_output_regression(baseline, current)

    assert result["status"] == "fail"
    assert any(f["code"] == "RULE_COVERAGE_DROP" for f in result["failures"])


def test_gate_fails_when_report_is_partial():
    from scripts.output_regression_gate import evaluate_output_regression

    baseline = _report([{"dimension": "结构层", "rule_id": "S-1"}])
    current = _report(
        [{"dimension": "结构层", "rule_id": "S-1"}],
        completion={"status": "partial", "failed_workers": ["quality"], "recovered_workers": []},
    )

    result = evaluate_output_regression(baseline, current)

    assert result["status"] == "fail"
    assert any(f["code"] == "PARTIAL_REVIEW" for f in result["failures"])

