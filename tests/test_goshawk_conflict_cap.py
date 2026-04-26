"""P0-2.5 苍鹰 conflict_resolutions 上限单测 (2026-04-26 sprint Day3).

承接 sprint Day3 实证 (memory pecker_sprint_day3_2026_04_26):
同 PRD 同 codebase 两轮 merged_to_facet 4→9 (差 125%), 苍鹰判定本身 sampling-noisy.
P0-2.5 修法: prompt 加"不确定不合并" + schema maxItems=3 + parser 兜底截断.

本文件只测 parser 兜底截断行为 (其他 prompt 改动 + schema 改动靠 e2e/手动验证).
"""
from __future__ import annotations

import pytest


def _mock_response(conflicts, additional=None, flagged=None):
    """构造一个假 response.content[0] = tool_use, name = submit_advisor_review."""
    class MockBlock:
        def __init__(self):
            self.type = "tool_use"
            self.name = "submit_advisor_review"
            self.input = {
                "flagged_as_false_positive": flagged or [],
                "additional_findings": additional or [],
                "conflict_resolutions": conflicts,
                "confidence": 0.8,
            }

    class MockResponse:
        content = [MockBlock()]

    return MockResponse()


def _make_conflict(items_, idx):
    return {
        "items": items_,
        "resolution": f"裁决 #{idx}",
        "reason": f"理由 #{idx}",
    }


class TestConflictCap:
    def test_under_cap_passes_all(self):
        """conflict 数 <= 3 → 全保留."""
        from goshawk_advisor import _extract_advisor_result, MAX_CONFLICT_RESOLUTIONS

        conflicts = [
            _make_conflict(["R-001", "R-002"], 1),
            _make_conflict(["R-003", "R-004"], 2),
        ]
        out = _extract_advisor_result(_mock_response(conflicts))
        assert len(out["conflict_resolutions"]) == 2

    def test_at_cap_passes_all(self):
        from goshawk_advisor import _extract_advisor_result, MAX_CONFLICT_RESOLUTIONS

        conflicts = [_make_conflict([f"R-{i:03d}", f"R-{i+1:03d}"], i) for i in range(MAX_CONFLICT_RESOLUTIONS)]
        out = _extract_advisor_result(_mock_response(conflicts))
        assert len(out["conflict_resolutions"]) == MAX_CONFLICT_RESOLUTIONS

    def test_above_cap_truncated(self):
        """conflict 数 > 3 → 截到 3 + log warning."""
        from goshawk_advisor import _extract_advisor_result, MAX_CONFLICT_RESOLUTIONS

        # 模型返回 9 条 (Run 2 实测情况)
        conflicts = [_make_conflict([f"R-{i:03d}", f"R-{i+1:03d}"], i) for i in range(9)]
        out = _extract_advisor_result(_mock_response(conflicts))
        assert len(out["conflict_resolutions"]) == MAX_CONFLICT_RESOLUTIONS == 3
        # 截断保留前 3 条 (按模型返回顺序), 不重排
        assert out["conflict_resolutions"][0]["resolution"] == "裁决 #0"
        assert out["conflict_resolutions"][1]["resolution"] == "裁决 #1"
        assert out["conflict_resolutions"][2]["resolution"] == "裁决 #2"

    def test_empty_conflicts(self):
        from goshawk_advisor import _extract_advisor_result
        out = _extract_advisor_result(_mock_response([]))
        assert out["conflict_resolutions"] == []

    def test_constants_value(self):
        """guardrail: MAX_CONFLICT_RESOLUTIONS 不能改成 0 (会破坏冲突调解功能)."""
        from goshawk_advisor import MAX_CONFLICT_RESOLUTIONS
        assert MAX_CONFLICT_RESOLUTIONS >= 1
        assert MAX_CONFLICT_RESOLUTIONS <= 5   # 合理上限
