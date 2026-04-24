"""T5 calibration_runner 单测 (2026-04-24).

不跑 pecker (offline mode), 用小 fixture 的 GT + output 跑计算流水.
"""
from __future__ import annotations

import json
import os
import sys

import pytest


_SCRIPTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "scripts"))
sys.path.insert(0, _SCRIPTS_DIR)


def _make_gt(items):
    return {"workspace": "test-ws", "prd": "test.md", "items": items}


def _make_output(items):
    return {"items": items}


# ============================================================
# 匹配 + 分类
# ============================================================

class TestMatchAndClassify:
    def test_tp_fp_fn_basic(self):
        from calibration_runner import _match_pecker_to_gt, classify

        gt_items = [
            {"id": "gt-1", "rule_id": "RC-001", "location": "第1节", "issue": "问题A", "severity": "must", "is_true_positive": True},
            {"id": "gt-2", "rule_id": "RC-002", "location": "第2节", "issue": "问题B", "severity": "should", "is_true_positive": True},
            {"id": "gt-3", "rule_id": "RC-003", "location": "第3节", "issue": "误报C", "severity": "must", "is_true_positive": False},
        ]
        pecker_items = [
            # 匹配 gt-1 (true positive) → TP
            {"id": "R-001", "rule_id": "RC-001", "location": "第1节", "issue": "问题A 具体表现", "severity": "must"},
            # 匹配 gt-3 (GT 标误报) → FP
            {"id": "R-002", "rule_id": "RC-003", "location": "第3节", "issue": "误报C", "severity": "must"},
            # 没匹配 → FP (pecker 找了 GT 没的)
            {"id": "R-003", "rule_id": "RC-999", "location": "第9节", "issue": "无中生有", "severity": "should"},
        ]

        pairs, matched_idx = _match_pecker_to_gt(pecker_items, gt_items)
        tp, fp, fn = classify(pairs, gt_items, matched_idx)

        assert len(tp) == 1
        assert tp[0]["pecker"]["id"] == "R-001"
        assert len(fp) == 2
        assert {p["pecker"]["id"] for p in fp} == {"R-002", "R-003"}
        assert len(fn) == 1   # gt-2 (true positive) 未匹配
        assert fn[0]["gt"]["id"] == "gt-2"


# ============================================================
# metrics
# ============================================================

class TestMetrics:
    def test_precision_recall_f1(self):
        from calibration_runner import compute_metrics
        m = compute_metrics(tp=[1, 2, 3], fp=[4], fn=[5])   # 用长度计算即可
        assert m["tp"] == 3
        assert m["fp"] == 1
        assert m["fn"] == 1
        # precision = 3 / 4 = 0.75
        assert m["precision"] == 0.75
        # recall = 3 / 4 = 0.75
        assert m["recall"] == 0.75
        # f1 = 0.75
        assert m["f1"] == 0.75

    def test_zero_division_safe(self):
        from calibration_runner import compute_metrics
        m = compute_metrics(tp=[], fp=[], fn=[])
        assert m == {"tp": 0, "fp": 0, "fn": 0, "precision": 0.0, "recall": 0.0, "f1": 0.0}


# ============================================================
# action / reject_reason 分布
# ============================================================

class TestActionDistribution:
    def test_accept_edit_rate_from_gt(self):
        from calibration_runner import compute_action_distribution
        items = [
            {"id": "1", "action": "accept", "is_true_positive": True},
            {"id": "2", "action": "accept", "is_true_positive": True},
            {"id": "3", "action": "edit", "is_true_positive": True},
            {"id": "4", "action": "reject", "is_true_positive": False, "reason_category": "false_positive"},
            {"id": "5", "action": "reject", "is_true_positive": False, "reason_category": "wiki_missing"},
        ]
        out = compute_action_distribution(items)
        assert out["actions"] == {"accept": 2, "edit": 1, "reject": 2}
        # accept+edit = 3/5 = 0.6
        assert out["accept_edit_rate"] == 0.6
        assert out["reject_rate"] == 0.4
        assert out["reject_reasons"] == {"false_positive": 1, "wiki_missing": 1}

    def test_reject_without_reason_category(self):
        from calibration_runner import compute_action_distribution
        items = [{"id": "1", "action": "reject"}]   # 没 reason_category
        out = compute_action_distribution(items)
        assert out["reject_reasons"] == {"uncategorized": 1}

    def test_empty(self):
        from calibration_runner import compute_action_distribution
        out = compute_action_distribution([])
        assert out["accept_edit_rate"] == 0.0
        assert out["actions"] == {}


# ============================================================
# severity 切片
# ============================================================

class TestSlice:
    def test_severity_bucketing(self):
        from calibration_runner import compute_severity_dimension_slice
        tp = [{"pecker": {"severity": "must", "dimension": "结构层"}}]
        fp = [
            {"pecker": {"severity": "should", "dimension": "质量层"}},
            {"pecker": {"severity": "must", "dimension": "结构层"}},
        ]
        fn = [{"gt": {"severity": "must", "dimension": "数据质量"}}]
        out = compute_severity_dimension_slice(tp, fp, fn)
        assert out["by_severity"]["tp"] == {"must": 1}
        assert out["by_severity"]["fp"] == {"should": 1, "must": 1}
        assert out["by_severity"]["fn"] == {"must": 1}


# ============================================================
# 真 end-to-end: 给本项目的真实 ground truth (侵权软件模板) 和假 pecker output
# ============================================================

class TestEndToEndOnInfringementGT:
    """跑侵权软件 GT (31 条) 的子集 + 假 pecker output, 断言 workflow 不崩."""

    def test_partial_match_runs_through(self, tmp_path):
        from calibration_runner import (
            _extract_items, _match_pecker_to_gt, build_report, classify,
            compute_action_distribution, compute_metrics, compute_severity_dimension_slice,
        )

        gt_items = [
            {"id": "gt-A", "rule_id": "R-018", "location": "全文", "issue": "模板未替换",
             "severity": "must", "is_true_positive": True, "action": "accept", "dimension": "结构层"},
            {"id": "gt-B", "rule_id": "R-020", "location": "2.3 节", "issue": "送达公告残留",
             "severity": "must", "is_true_positive": True, "action": "accept", "dimension": "结构层"},
            {"id": "gt-noise", "rule_id": "CONFIRM-001", "location": "整体", "issue": "meta item",
             "severity": "should", "is_true_positive": False, "action": "reject",
             "reason_category": "false_positive", "dimension": "AI Coding 友好度"},
        ]
        gt_data = _make_gt(gt_items)
        pecker_output = _make_output([
            {"id": "R-001", "rule_id": "R-018", "location": "整体", "issue": "模板全文未替换",
             "severity": "must", "dimension": "结构层"},
            {"id": "R-006", "rule_id": "CONFIRM-001", "location": "整体", "issue": "meta item",
             "severity": "should", "dimension": "AI Coding 友好度"},
        ])

        pairs, matched = _match_pecker_to_gt(pecker_output["items"], gt_items)
        tp, fp, fn = classify(pairs, gt_items, matched)
        metrics = compute_metrics(tp, fp, fn)
        assert metrics["tp"] == 1   # R-001 matched gt-A
        assert metrics["fp"] == 1   # R-006 matched gt-noise (GT 标误报)
        assert metrics["fn"] == 1   # gt-B 漏了

        action = compute_action_distribution(gt_items)
        slices = compute_severity_dimension_slice(tp, fp, fn)

        report = build_report(gt_data, ["fake.json"], metrics, action, slices, overlap=None)
        assert "# Pecker Calibration Report" in report
        assert "Precision" in report
        assert "成功标准" in report
        assert "false_positive" in report   # reject_reasons 栏

    def test_write_to_file(self, tmp_path):
        """--out-file 写 markdown 到磁盘, 读回检查."""
        from calibration_runner import main
        gt_path = tmp_path / "gt.json"
        out_path = tmp_path / "output.json"
        report_path = tmp_path / "report.md"

        gt_path.write_text(json.dumps(_make_gt([
            {"id": "gt-1", "rule_id": "RC-001", "location": "x", "issue": "y",
             "severity": "must", "is_true_positive": True, "action": "accept"},
        ]), ensure_ascii=False), encoding="utf-8")
        out_path.write_text(json.dumps(_make_output([
            {"id": "R-001", "rule_id": "RC-001", "location": "x", "issue": "y matched"},
        ]), ensure_ascii=False), encoding="utf-8")

        import sys as _sys
        original_argv = _sys.argv
        try:
            _sys.argv = [
                "calibration_runner",
                "--ground-truth", str(gt_path),
                "--output", str(out_path),
                "--out-file", str(report_path),
            ]
            ret = main()
        finally:
            _sys.argv = original_argv
        assert ret == 0
        assert report_path.exists()
        text = report_path.read_text(encoding="utf-8")
        assert "# Pecker Calibration Report" in text
