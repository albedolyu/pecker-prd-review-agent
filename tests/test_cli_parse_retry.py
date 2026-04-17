"""CLI JSON parse 失败时 subprocess 级 retry 测试.

Shadow run 见过 2.5% parse 失败 (根因: streaming 截断或偶发输出被打断),
retry 一次通常就好。本测试验证:
1. parse 失败 → _create_once 被调用 2 次
2. 第一次 fail 第二次成功 → 返回第二次的结果
3. 连续 2 次失败 → 抛 APIError,不再重试
4. 非 parse 错误(如 quota)不触发 retry
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from clients.claude_cli import ClaudeCodeCLIClient
from exceptions import APIError, QuotaExhaustedError


class _FakeClient(ClaudeCodeCLIClient):
    """绕过 __init__ 的 shutil.which / TokenTracker 构造,直接注入状态."""

    def __init__(self, _create_once_side_effect):
        from clients.token_tracker import TokenTracker

        self.claude_bin = "claude"
        self.tracker = TokenTracker()
        self._workspace = None
        self._node_bin, self._cli_js = None, None
        self._side_effect = _create_once_side_effect
        self._calls = 0

    def _create_once(self, *args, **kwargs):
        self._calls += 1
        effect = self._side_effect[self._calls - 1]
        if isinstance(effect, Exception):
            raise effect
        return effect


class TestCliParseRetry:
    def test_parse_fail_then_success(self):
        """第一次 parse 失败,第二次成功 → 返回第二次结果."""
        success_response = object()  # 伪 UnifiedResponse
        client = _FakeClient([
            APIError("CLI JSON parse failed for tool submit_review_items (text 450 chars)"),
            success_response,
        ])

        result = client.create("sonnet", 4000, "sys", [{"role": "user", "content": "x"}])
        assert result is success_response
        assert client._calls == 2  # retry 生效

    def test_parse_fail_twice_raises(self):
        """连续 2 次 parse 失败 → 抛 APIError,不再 retry."""
        first = APIError("CLI JSON parse failed for tool submit_review_items")
        second = APIError("CLI JSON parse failed for tool submit_review_items")
        client = _FakeClient([first, second])

        with pytest.raises(APIError) as exc_info:
            client.create("sonnet", 4000, "sys", [{"role": "user", "content": "x"}])
        assert "parse failed" in str(exc_info.value).lower()
        assert client._calls == 2  # 只 retry 1 次,不会第 3 次

    def test_non_json_output_retries(self):
        """'claude -p 输出非 JSON' 也触发 retry."""
        success = object()
        client = _FakeClient([
            APIError("claude -p 输出非 JSON: Expecting value\n前 200 字: partial..."),
            success,
        ])

        result = client.create("sonnet", 4000, "sys", [{"role": "user", "content": "x"}])
        assert result is success
        assert client._calls == 2

    def test_quota_error_no_retry(self):
        """QuotaExhaustedError 不触发 retry — ops 问题 retry 也没用."""
        client = _FakeClient([
            QuotaExhaustedError("Claude CLI 配额已用完"),
        ])

        with pytest.raises(QuotaExhaustedError):
            client.create("sonnet", 4000, "sys", [{"role": "user", "content": "x"}])
        assert client._calls == 1  # 没 retry

    def test_timeout_error_no_retry(self):
        """subprocess 超时不触发 retry — 一次 600s 已经很长."""
        client = _FakeClient([
            APIError("claude -p 子进程 600s 超时"),
        ])

        with pytest.raises(APIError) as exc_info:
            client.create("sonnet", 4000, "sys", [{"role": "user", "content": "x"}])
        assert "超时" in str(exc_info.value)
        assert client._calls == 1  # 没 retry

    def test_first_call_success_no_retry(self):
        """第一次就成功 → 只调用 1 次."""
        success = object()
        client = _FakeClient([success])

        result = client.create("sonnet", 4000, "sys", [{"role": "user", "content": "x"}])
        assert result is success
        assert client._calls == 1
