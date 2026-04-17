"""
context_manager AutocompactManager + token 估算测试 (Round 13)

autocompact 是长会话防炸的最后一道闸。熔断、阈值、序列化三处错一个都会导致:
- 炸 context 窗
- 无脑触发 compact 把有用上下文丢了
- 序列化错误导致 Haiku 摘要乱码

测试重点: should_compact / compact 路径 / is_circuit_broken / 序列化 tool blocks。
"""

import os
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestEstimateTokensRough:
    def test_empty_string(self):
        from context_manager import estimate_tokens_rough
        assert estimate_tokens_rough("") == 0

    def test_ascii_roughly_one_token_per_4_chars(self):
        from context_manager import estimate_tokens_rough
        # "hello world" = 11 bytes / 4 = 2 tokens
        assert estimate_tokens_rough("hello world") == 2

    def test_chinese_counted_by_utf8_bytes(self):
        from context_manager import estimate_tokens_rough
        # 每个中文字符 3 bytes UTF-8 → 3/4 tokens
        # "你好" = 6 bytes / 4 = 1
        assert estimate_tokens_rough("你好") == 1

    def test_list_sums(self):
        from context_manager import estimate_tokens_rough
        assert estimate_tokens_rough(["abcd", "efgh"]) == 2

    def test_dict_json_estimated(self):
        from context_manager import estimate_tokens_rough
        # {"k": "v"} → json 字符串 → byte count / 4
        assert estimate_tokens_rough({"k": "v"}) > 0

    def test_other_types_zero(self):
        from context_manager import estimate_tokens_rough
        assert estimate_tokens_rough(42) == 0
        assert estimate_tokens_rough(None) == 0


class TestEstimateMessagesTokens:
    def test_empty_messages_zero(self):
        from context_manager import estimate_messages_tokens
        assert estimate_messages_tokens([]) == 0

    def test_safety_multiplier_applied(self):
        """内部 *4/3 安全系数."""
        from context_manager import estimate_messages_tokens
        # "abcd" = 1 token raw, *4/3 = 1.33 → int = 1
        # "abcdefgh" = 2 tokens raw, *4/3 = 2.66 → int = 2
        result = estimate_messages_tokens([{"content": "abcdefgh"}])
        assert result == 2

    def test_multiple_messages_summed(self):
        from context_manager import estimate_messages_tokens
        msgs = [{"content": "abcd" * 100} for _ in range(3)]
        # 每个 100 tokens, 3 条 = 300, *4/3 = 400
        assert estimate_messages_tokens(msgs) == 400


class TestAutocompactManager:
    def test_should_compact_below_threshold_false(self):
        from context_manager import AutocompactManager
        mgr = AutocompactManager(max_context_tokens=200_000)
        # 小消息 → 不应触发
        msgs = [{"content": "hi"}]
        assert mgr.should_compact(msgs) is False

    def test_should_compact_above_threshold_true(self):
        from context_manager import AutocompactManager
        mgr = AutocompactManager(max_context_tokens=100)
        # 大消息 → 应触发
        big_msg = {"content": "abcd" * 200}  # 200 tokens * 4/3 = 266
        assert mgr.should_compact([big_msg]) is True

    def test_circuit_broken_disables_compact(self):
        from context_manager import AutocompactManager, MAX_COMPACT_FAILURES
        mgr = AutocompactManager(max_context_tokens=100)
        mgr.compact_failures = MAX_COMPACT_FAILURES
        assert mgr.is_circuit_broken is True
        # 熔断后即使大消息也不触发
        big_msg = {"content": "abcd" * 1000}
        assert mgr.should_compact([big_msg]) is False

    def test_compact_short_messages_passthrough(self):
        """消息数 ≤ KEEP_RECENT_MESSAGES → 原样返回."""
        from context_manager import AutocompactManager, KEEP_RECENT_MESSAGES
        mgr = AutocompactManager()
        msgs = [{"role": "user", "content": f"msg{i}"} for i in range(KEEP_RECENT_MESSAGES)]
        result = mgr.compact(MagicMock(), msgs, {"haiku": "h"})
        assert result == msgs

    def test_compact_success_resets_failures(self):
        from context_manager import AutocompactManager, KEEP_RECENT_MESSAGES
        mgr = AutocompactManager()
        mgr.compact_failures = 2

        # 构造足够多的消息
        msgs = [{"role": "user", "content": f"msg{i}"} for i in range(KEEP_RECENT_MESSAGES + 3)]
        # Mock client 返回一个 summary response
        client = MagicMock()
        client.create.return_value = SimpleNamespace(
            content=[SimpleNamespace(type="text", text="这是摘要")],
        )

        result = mgr.compact(client, msgs, {"haiku": "h", "sonnet": "s"})
        # 压缩后结构: [user(摘要), assistant("好的"), *recent_msgs]
        assert len(result) == 2 + KEEP_RECENT_MESSAGES
        assert "摘要" in result[0]["content"]
        assert mgr.compact_failures == 0

    def test_compact_failure_increments_counter(self):
        from context_manager import AutocompactManager, KEEP_RECENT_MESSAGES
        mgr = AutocompactManager()

        msgs = [{"role": "user", "content": f"msg{i}"}
                for i in range(KEEP_RECENT_MESSAGES + 3)]
        client = MagicMock()
        client.create.side_effect = RuntimeError("API boom")

        result = mgr.compact(client, msgs, {"haiku": "h"})
        # 失败 → 返回原始消息不崩
        assert result == msgs
        assert mgr.compact_failures == 1

    def test_compact_empty_summary_treated_as_failure(self):
        from context_manager import AutocompactManager, KEEP_RECENT_MESSAGES
        mgr = AutocompactManager()

        msgs = [{"role": "user", "content": f"msg{i}"}
                for i in range(KEEP_RECENT_MESSAGES + 3)]
        client = MagicMock()
        client.create.return_value = SimpleNamespace(
            content=[SimpleNamespace(type="text", text="   ")],  # 仅空白
        )

        result = mgr.compact(client, msgs, {"haiku": "h"})
        assert result == msgs
        assert mgr.compact_failures == 1

    def test_status_string_contains_key_fields(self):
        from context_manager import AutocompactManager
        mgr = AutocompactManager()
        mgr.total_tokens_saved = 1234
        mgr.compact_failures = 1
        s = mgr.status()
        assert "saved=1,234" in s
        assert "failures=1" in s
        assert "closed" in s  # 未熔断


class TestSerializeMessagesForSummary:
    def test_string_content(self):
        from context_manager import _serialize_messages_for_summary
        msgs = [{"role": "user", "content": "hello"}]
        text = _serialize_messages_for_summary(msgs)
        assert "[user] hello" in text

    def test_list_content_with_text_block(self):
        from context_manager import _serialize_messages_for_summary
        msgs = [{"role": "assistant",
                 "content": [{"type": "text", "text": "world"}]}]
        text = _serialize_messages_for_summary(msgs)
        assert "world" in text

    def test_tool_result_block_summarized(self):
        from context_manager import _serialize_messages_for_summary
        msgs = [{"role": "user", "content": [
            {"type": "tool_result", "content": "x" * 500},
        ]}]
        text = _serialize_messages_for_summary(msgs)
        assert "[tool result:" in text
        # 取前 100 字
        assert len(text) < 600

    def test_tool_use_block_summarized(self):
        from context_manager import _serialize_messages_for_summary
        msgs = [{"role": "assistant", "content": [
            {"type": "tool_use", "name": "read_file"},
        ]}]
        text = _serialize_messages_for_summary(msgs)
        assert "[tool call: read_file]" in text

    def test_long_message_truncated(self):
        from context_manager import _serialize_messages_for_summary
        msgs = [{"role": "user", "content": "x" * 2000}]
        text = _serialize_messages_for_summary(msgs)
        # 截断到 500 + "..."
        assert "..." in text
