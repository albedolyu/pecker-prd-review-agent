"""
goshawk_advisor 空提交重试 + verdict 分类测试 (Round 3)

覆盖:
- _is_empty_advisor_submission 各种 response shape
- advisor_review 首轮空提交 → retry 分支
- verdict 精细化: SILENT / EMPTY_APPROVAL / REVIEWED
"""

import os
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _tool_use(fps=None, adds=None, confs=None, confidence=0.0,
              name="submit_advisor_review"):
    return SimpleNamespace(
        type="tool_use", name=name, id="t1",
        input={
            "flagged_as_false_positive": fps or [],
            "additional_findings": adds or [],
            "conflict_resolutions": confs or [],
            "confidence": confidence,
        },
    )


def _text(t):
    return SimpleNamespace(type="text", text=t)


def _resp(blocks, stop="end_turn", input_tok=100, output_tok=50):
    return SimpleNamespace(
        content=blocks, stop_reason=stop,
        usage={"input_tokens": input_tok, "output_tokens": output_tok},
    )


def _resp_without_usage(blocks, stop="end_turn"):
    return SimpleNamespace(content=blocks, stop_reason=stop)


# ============================================================
# _is_empty_advisor_submission
# ============================================================

class TestIsEmptyAdvisorSubmission:
    def test_no_tool_use(self):
        from goshawk_advisor import _is_empty_advisor_submission
        assert _is_empty_advisor_submission(_resp([_text("foo")])) is False

    def test_tool_with_all_empty(self):
        from goshawk_advisor import _is_empty_advisor_submission
        assert _is_empty_advisor_submission(_resp([_tool_use()])) is True

    def test_tool_with_fps_not_empty(self):
        from goshawk_advisor import _is_empty_advisor_submission
        r = _resp([_tool_use(fps=[{"id": "R-001"}])])
        assert _is_empty_advisor_submission(r) is False

    def test_tool_with_additional_not_empty(self):
        from goshawk_advisor import _is_empty_advisor_submission
        r = _resp([_tool_use(adds=[{"issue": "补充"}])])
        assert _is_empty_advisor_submission(r) is False

    def test_tool_with_conflict_not_empty(self):
        from goshawk_advisor import _is_empty_advisor_submission
        r = _resp([_tool_use(confs=[{"resolution": "x"}])])
        assert _is_empty_advisor_submission(r) is False

    def test_other_tool_name_ignored(self):
        from goshawk_advisor import _is_empty_advisor_submission
        r = _resp([_tool_use(name="some_other_tool")])
        assert _is_empty_advisor_submission(r) is False


# ============================================================
# advisor_review 空重试 + verdict 分类
# ============================================================

def _setup_advisor_env(monkeypatch):
    """屏蔽 GOSHAWK_ART 打印 + time.sleep."""
    monkeypatch.setattr("goshawk_advisor.GOSHAWK_ART", "", raising=False)
    monkeypatch.setattr("goshawk_advisor.random.uniform", lambda a, b: 0, raising=False)
    import time as _t
    monkeypatch.setattr(_t, "sleep", lambda *_a, **_kw: None)


class TestAdvisorReviewVerdict:
    def test_first_turn_productive_verdict_reviewed(self, monkeypatch):
        """首轮就有输出 → verdict=REVIEWED, empty_retry_used=False."""
        _setup_advisor_env(monkeypatch)
        from goshawk_advisor import advisor_review

        r1 = _resp([_tool_use(fps=[{"id": "R-001"}], confidence=0.85)])
        client = MagicMock()
        client.create.return_value = r1

        result = advisor_review(client, "PRD body", [{"id": "R-001"}])
        assert result["verdict"] == "REVIEWED"
        assert result["empty_retry_used"] is False
        assert client.create.call_count == 1

    def test_empty_submission_then_retry_with_findings(self, monkeypatch):
        """首轮空提交 → retry 返回 findings → verdict=REVIEWED + retry 标记."""
        _setup_advisor_env(monkeypatch)
        from goshawk_advisor import advisor_review

        r1 = _resp([_tool_use()])  # 全空
        r2 = _resp([_tool_use(adds=[{"issue": "漏了"}], confidence=0.8)])
        client = MagicMock()
        client.create.side_effect = [r1, r2]

        result = advisor_review(client, "PRD body", [{"id": "R-001"}])
        assert result["verdict"] == "REVIEWED"
        assert result["empty_retry_used"] is True
        assert len(result["additional_findings"]) == 1
        assert client.create.call_count == 2

    def test_empty_submission_retry_confidence_backed(self, monkeypatch):
        """retry 仍三空但 confidence 显式上调 → 视为 EMPTY_APPROVAL + 采纳新 confidence."""
        _setup_advisor_env(monkeypatch)
        from goshawk_advisor import advisor_review

        r1 = _resp([_tool_use(confidence=0.0)])
        r2 = _resp([_tool_use(confidence=0.9)])  # 仍三空,但显式背书
        client = MagicMock()
        client.create.side_effect = [r1, r2]

        result = advisor_review(client, "PRD body", [{"id": "R-001"}])
        assert result["verdict"] == "EMPTY_APPROVAL"
        assert result["confidence"] == 0.9
        assert result["empty_retry_used"] is True

    def test_silent_no_tool_called_at_all(self, monkeypatch):
        """首轮无 tool + catchup 也失败 → verdict=SILENT."""
        _setup_advisor_env(monkeypatch)
        from goshawk_advisor import advisor_review

        r1 = _resp([_text("I think nothing's wrong.")])
        r2 = _resp([_text("Still just text, no tool.")])
        client = MagicMock()
        client.create.side_effect = [r1, r2]

        result = advisor_review(client, "PRD body", [{"id": "R-001"}])
        assert result["verdict"] == "SILENT"

    def test_silent_retry_raises_still_silent(self, monkeypatch):
        """首轮无 tool,retry 抛异常 → 保持 SILENT verdict."""
        _setup_advisor_env(monkeypatch)
        from goshawk_advisor import advisor_review

        r1 = _resp([_text("no tool")])
        client = MagicMock()
        client.create.side_effect = [r1, RuntimeError("network boom")]

        # 注意: advisor_review 第一层有 max_retries=2 指数退避,会把 r1 消费掉作首轮
        # 然后 catchup (for no_tool) 捕获 RuntimeError 不 raise
        # 但 max_retries 的 except 不捕获 has_tool retry 里的异常
        try:
            result = advisor_review(client, "PRD body", [{"id": "R-001"}])
        except RuntimeError:
            pytest.fail("catchup 应 swallow 异常,不向外抛")
        assert result["verdict"] == "SILENT"

    def test_empty_approval_no_retry_if_retry_also_empty_no_confidence(self, monkeypatch):
        """retry 后仍三空 + confidence 未上调 → EMPTY_APPROVAL,保持首次结果."""
        _setup_advisor_env(monkeypatch)
        from goshawk_advisor import advisor_review

        r1 = _resp([_tool_use(confidence=0.0)])
        r2 = _resp([_tool_use(confidence=0.0)])
        client = MagicMock()
        client.create.side_effect = [r1, r2]

        result = advisor_review(client, "PRD body", [{"id": "R-001"}])
        assert result["verdict"] == "EMPTY_APPROVAL"
        assert result["confidence"] == 0.0
        assert result["empty_retry_used"] is True

    def test_successful_review_tolerates_missing_usage_metadata(self, monkeypatch):
        """结构化终审已成功时,缺失 usage 元数据不应把结果变成异常."""
        _setup_advisor_env(monkeypatch)
        from goshawk_advisor import advisor_review

        client = MagicMock()
        client.create.return_value = _resp_without_usage(
            [_tool_use(fps=[{"id": "R-001"}], confidence=0.85)]
        )

        result = advisor_review(client, "PRD body", [{"id": "R-001"}])

        assert result["verdict"] == "REVIEWED"
        assert result["usage"] == {"input_tokens": 0, "output_tokens": 0}
