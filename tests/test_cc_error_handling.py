"""R15: 单测 CLI 调用的错误分类

覆盖 `api_adapter.py` 的错误路径:
1. 配额耗尽 → QuotaExhaustedError(带 reset_hint)
2. 其他 CLI 返回码非 0 → APIError
3. JSON 解析失败 → APIError (不再静默返回空壳)

这是 P0-2 + P0-3 的回归保护。调 ClaudeCodeCLIClient.create() 级入口,mock
底层 subprocess.run 注入各种 CLI 返回形态。
"""
import json
import pytest
from unittest.mock import MagicMock, patch

from exceptions import APIError, QuotaExhaustedError


# --------------------------------------------------------------
# QuotaExhaustedError 基础行为
# --------------------------------------------------------------

def test_quota_error_is_subclass_of_api_error():
    """QuotaExhaustedError 必须继承 APIError,现有 except APIError 代码不受影响"""
    err = QuotaExhaustedError("配额用完", reset_hint="8am (America/Los_Angeles)")
    assert isinstance(err, APIError)
    assert err.reset_hint == "8am (America/Los_Angeles)"
    assert "配额用完" in str(err)


def test_quota_error_default_reset_hint_none():
    err = QuotaExhaustedError("配额用完")
    assert err.reset_hint is None


# --------------------------------------------------------------
# ClaudeCodeCLIClient 错误分类
# --------------------------------------------------------------

def _mock_proc(returncode=0, stdout="", stderr=""):
    p = MagicMock()
    p.returncode = returncode
    p.stdout = stdout
    p.stderr = stderr
    return p


@pytest.fixture
def cli_client():
    """最小化构造 ClaudeCodeCLIClient 不跑真实 CLI"""
    from api_adapter import ClaudeCodeCLIClient
    return ClaudeCodeCLIClient()


def test_quota_exhausted_raises_quota_error(cli_client):
    """CLI 返回 'hit your limit' 错误 → QuotaExhaustedError"""
    quota_stderr = (
        '{"type":"result","subtype":"success","is_error":true,"duration_ms":4611,'
        '"duration_api_ms":0,"num_turns":1,"result":"You\'ve hit your limit — '
        'resets 8am (America/Los_Angeles)","stop_reason":"end_turn"}'
    )
    with patch("subprocess.run", return_value=_mock_proc(returncode=1, stderr=quota_stderr)):
        with pytest.raises(QuotaExhaustedError) as exc_info:
            cli_client.create(
                model="sonnet",
                max_tokens=1000,
                system="",
                messages=[{"role": "user", "content": "test"}],
            )
    err = exc_info.value
    assert isinstance(err, APIError), "Quota error 应是 APIError 子类"
    assert "配额" in str(err) or "limit" in str(err).lower()


def test_quota_exhausted_extracts_reset_hint(cli_client):
    """reset 时间应该被正则提取出来"""
    quota_stderr = (
        '{"is_error":true,"result":"You\'ve hit your limit — '
        'resets 8am (America/Los_Angeles)"}'
    )
    with patch("subprocess.run", return_value=_mock_proc(returncode=1, stderr=quota_stderr)):
        with pytest.raises(QuotaExhaustedError) as exc_info:
            cli_client.create(
                model="sonnet",
                max_tokens=1000,
                system="",
                messages=[{"role": "user", "content": "test"}],
            )
    # reset_hint 字段应被设置(具体内容取决于 regex 匹配)
    # 只要不是 None 且包含 8am 就算正确
    assert exc_info.value.reset_hint is not None
    assert "8am" in exc_info.value.reset_hint


def test_non_quota_error_raises_plain_api_error(cli_client):
    """非配额原因的 returncode 非 0 → 普通 APIError,不是 QuotaExhaustedError"""
    with patch("subprocess.run",
               return_value=_mock_proc(returncode=1, stderr="some other crash: segfault")):
        with pytest.raises(APIError) as exc_info:
            cli_client.create(
                model="sonnet",
                max_tokens=1000,
                system="",
                messages=[{"role": "user", "content": "test"}],
            )
    assert not isinstance(exc_info.value, QuotaExhaustedError)


def test_cli_json_parse_failure_raises_api_error(cli_client):
    """结构化 tool 模式下 CLI 返回了 JSON wrapper 但 tool 参数解析失败 → APIError

    原行为: 返回空壳 ({}),上游当成功处理 items=[]
    新行为(P0-2): 抛 APIError,让上游走 worker error 上报链路
    """
    # 伪造 CLI 返回的 outer JSON wrapper
    cli_output = json.dumps({
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "result": "此处应有 JSON tool call 但没有,只有散文",
        "usage": {"input_tokens": 10, "output_tokens": 5},
        "modelUsage": {"claude-sonnet-4-6": {"inputTokens": 10}},
    })
    structured_tool = {
        "name": "submit_review_items",
        "description": "test",
        "input_schema": {
            "type": "object",
            "properties": {"items": {"type": "array"}},
            "required": ["items"],
        },
    }

    with patch("subprocess.run",
               return_value=_mock_proc(returncode=0, stdout=cli_output)):
        with pytest.raises(APIError) as exc_info:
            cli_client.create(
                model="sonnet",
                max_tokens=1000,
                system="",
                messages=[{"role": "user", "content": "test"}],
                tools=[structured_tool],
                tool_choice={"type": "any"},
            )
    msg = str(exc_info.value)
    assert "JSON" in msg or "parse" in msg.lower()


def test_successful_call_does_not_raise(cli_client):
    """正常 CLI 成功返回时不应抛错(sanity check 确保我们的改动没破坏 happy path)"""
    cli_output = json.dumps({
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "result": "hello world",
        "usage": {"input_tokens": 5, "output_tokens": 2},
        "modelUsage": {"claude-sonnet-4-6": {"inputTokens": 5, "outputTokens": 2}},
    })
    with patch("subprocess.run",
               return_value=_mock_proc(returncode=0, stdout=cli_output)):
        resp = cli_client.create(
            model="sonnet",
            max_tokens=100,
            system="",
            messages=[{"role": "user", "content": "hi"}],
        )
    # 没有 structured_tool,走文本模式,应能正常返回
    assert resp is not None
