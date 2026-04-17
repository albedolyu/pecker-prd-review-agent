"""
Worker 空提交重试测试 — 覆盖 parallel_review._is_empty_tool_submission
和 _worker_core 的 empty-retry 分支

背景: 2026-04-16 真实数据显示 data_quality / quality worker 有 50% session 里
submit_review_items 被调用但 items=[]。之前代码只重试"没调 tool"场景,空提交直接沉默。
本文件验证新加的 retry 分支生效。
"""

import os
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ============================================================
# Response fixture helpers
# ============================================================

def _tool_use_block(items_list, name="submit_review_items"):
    """构造 submit_review_items tool_use block。"""
    return SimpleNamespace(
        type="tool_use",
        name=name,
        id="toolu_test",
        input={"items": items_list},
    )


def _text_block(text):
    return SimpleNamespace(type="text", text=text)


def _response(blocks, stop_reason="end_turn", input_tok=100, output_tok=50):
    return SimpleNamespace(
        content=blocks,
        stop_reason=stop_reason,
        usage={
            "input_tokens": input_tok,
            "output_tokens": output_tok,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
        },
    )


# ============================================================
# _is_empty_tool_submission
# ============================================================

class TestIsEmptyToolSubmission:
    def test_no_tool_use_returns_false(self):
        from parallel_review import _is_empty_tool_submission
        resp = _response([_text_block("just text")])
        assert _is_empty_tool_submission(resp) is False

    def test_tool_with_items_returns_false(self):
        from parallel_review import _is_empty_tool_submission
        resp = _response([_tool_use_block([{"id": "R-001", "issue": "foo"}])])
        assert _is_empty_tool_submission(resp) is False

    def test_tool_with_empty_items_returns_true(self):
        from parallel_review import _is_empty_tool_submission
        resp = _response([_tool_use_block([])])
        assert _is_empty_tool_submission(resp) is True

    def test_tool_with_missing_items_key_returns_true(self):
        """input 里没 items 字段也算空提交。"""
        from parallel_review import _is_empty_tool_submission
        resp = SimpleNamespace(content=[
            SimpleNamespace(type="tool_use", name="submit_review_items",
                            id="t1", input={}),
        ])
        assert _is_empty_tool_submission(resp) is True

    def test_other_tool_name_ignored(self):
        """不是 submit_review_items 的 tool_use 不判空提交。"""
        from parallel_review import _is_empty_tool_submission
        resp = _response([_tool_use_block([], name="other_tool")])
        assert _is_empty_tool_submission(resp) is False

    def test_mixed_text_and_empty_tool_is_empty(self):
        """前面有文本解释,tool_use items 空,仍判空提交。"""
        from parallel_review import _is_empty_tool_submission
        resp = _response([_text_block("I found no issues."), _tool_use_block([])])
        assert _is_empty_tool_submission(resp) is True


# ============================================================
# _worker_core empty-retry 分支
# ============================================================

# 注意: _worker_core 涉及非常多模块级依赖 (dimensions / wiki_keywords / cache_monitor 等),
# 这里用最小 mock 只覆盖 retry 分支逻辑。关键是验证:
# 1. 空提交时,_call 会被调用第二次 (重试)
# 2. 重试返回 items 时,最终 items 非空
# 3. telemetry["empty_retry_used"] = True

def _make_minimal_worker_env(monkeypatch):
    """为 _worker_core 建立最小运行环境 (mock 掉所有外部依赖)。"""
    # dimensions / wiki_keywords
    fake_dim = {
        "name": "测试维度",
        "model": "sonnet",
        "effort": "medium",
        "checklist": [{"rule_id": "R-TEST-001"}],
    }
    monkeypatch.setattr(
        "parallel_review.get_review_dimensions",
        lambda workspace=None: {"test_dim": fake_dim},
    )
    monkeypatch.setattr(
        "parallel_review.get_wiki_keywords", lambda workspace=None: [],
    )
    # system / messages 构造
    monkeypatch.setattr(
        "parallel_review._build_worker_system",
        lambda *a, **kw: "dynamic system prompt",
    )
    monkeypatch.setattr(
        "parallel_review._build_worker_messages",
        lambda *a, **kw: [{"role": "user", "content": "prd body"}],
    )
    # cache monitor (no-op)
    fake_cm = MagicMock()
    monkeypatch.setattr(
        "parallel_review.PromptCacheMonitor", lambda: fake_cm,
        raising=False,
    )
    # compute_call_cost_usd
    monkeypatch.setattr("api_adapter.compute_call_cost_usd",
                        lambda model, usage: 0.001)


class TestWorkerEmptyRetry:
    def test_empty_submission_triggers_retry(self, monkeypatch):
        """首轮空提交 → 触发 retry → 第二轮返回 items,最终 items 非空 + telemetry 标记。"""
        _make_minimal_worker_env(monkeypatch)

        from parallel_review import _worker_core

        first = _response([_tool_use_block([])])
        retry_items = [{"id": "R-001", "issue": "补充发现", "severity": "should",
                        "rule_id": "R-TEST-001"}]
        second = _response([_tool_use_block(retry_items)])
        client = MagicMock()
        client.create.side_effect = [first, second]

        # 避免真实 sleep 拖慢单测
        monkeypatch.setattr("parallel_review.time.sleep", lambda _: None)
        monkeypatch.setattr("parallel_review.random.uniform", lambda a, b: 0)

        result = _worker_core(
            client=client, dim_key="test_dim",
            prd_content="PRD", wiki_pages={}, model_tiers={"sonnet": "s-m"},
        )

        assert client.create.call_count == 2, "应触发一次 retry"
        assert len(result["items"]) == 1
        assert result["items"][0]["issue"] == "补充发现"
        assert result["telemetry"]["empty_retry_used"] is True
        assert result["telemetry"]["turns_used"] == 2

    def test_empty_submission_retry_still_empty_accepted(self, monkeypatch):
        """retry 后仍空 → 接受空结果,不再重试,telemetry 仍标记。"""
        _make_minimal_worker_env(monkeypatch)

        from parallel_review import _worker_core

        first = _response([_tool_use_block([])])
        second = _response([_tool_use_block([])])  # retry 仍空
        client = MagicMock()
        client.create.side_effect = [first, second]

        monkeypatch.setattr("parallel_review.time.sleep", lambda _: None)
        monkeypatch.setattr("parallel_review.random.uniform", lambda a, b: 0)

        result = _worker_core(
            client=client, dim_key="test_dim",
            prd_content="PRD", wiki_pages={}, model_tiers={"sonnet": "s-m"},
        )

        assert client.create.call_count == 2
        assert len(result["items"]) == 0
        assert result["telemetry"]["empty_retry_used"] is True

    def test_productive_first_turn_no_retry(self, monkeypatch):
        """首轮就有 items → 不触发 retry,telemetry 标记为 False。"""
        _make_minimal_worker_env(monkeypatch)

        from parallel_review import _worker_core

        first_items = [{"id": "R-001", "issue": "foo", "severity": "must",
                        "rule_id": "R-TEST-001"}]
        first = _response([_tool_use_block(first_items)])
        client = MagicMock()
        client.create.side_effect = [first]

        result = _worker_core(
            client=client, dim_key="test_dim",
            prd_content="PRD", wiki_pages={}, model_tiers={"sonnet": "s-m"},
        )

        assert client.create.call_count == 1, "productive 不应重试"
        assert len(result["items"]) == 1
        assert result["telemetry"]["empty_retry_used"] is False
        assert result["telemetry"]["turns_used"] == 1

    def test_empty_retry_exception_swallowed_gracefully(self, monkeypatch):
        """retry 调用抛异常 → 最终 items=0 但不崩 worker,telemetry 已标。"""
        _make_minimal_worker_env(monkeypatch)

        from parallel_review import _worker_core

        first = _response([_tool_use_block([])])
        client = MagicMock()
        client.create.side_effect = [first, RuntimeError("second call boom")]

        monkeypatch.setattr("parallel_review.time.sleep", lambda _: None)
        monkeypatch.setattr("parallel_review.random.uniform", lambda a, b: 0)

        result = _worker_core(
            client=client, dim_key="test_dim",
            prd_content="PRD", wiki_pages={}, model_tiers={"sonnet": "s-m"},
        )

        assert client.create.call_count == 2
        assert len(result["items"]) == 0
        assert result["telemetry"]["empty_retry_used"] is True
