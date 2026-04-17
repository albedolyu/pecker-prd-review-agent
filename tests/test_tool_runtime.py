"""
tool_runtime 模块单测 — 覆盖 tool_loop 主体逻辑 + 辅助函数

策略: 用 mock client 构造响应序列,验证:
- 正常 end_turn 终止
- tool_use 循环 (assistant → tool_result → assistant)
- 只读工具并发分支 + 写工具串行分支
- wall-clock 超时抛 AgentTimeoutError
- API error 提前 break
- 大结果落盘 + 预览
- brief_input 各种入参形态
"""

import os
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ============================================================
# Helper: 构造 fake response / tool_use block
# ============================================================

def _text_block(text: str):
    return SimpleNamespace(type="text", text=text)


def _tool_use_block(block_id: str, name: str, inputs: dict):
    return SimpleNamespace(type="tool_use", id=block_id, name=name, input=inputs)


def _response(blocks, stop_reason: str = "end_turn"):
    return SimpleNamespace(content=blocks, stop_reason=stop_reason)


def _mk_client(responses):
    """每次 create 返回 responses 队列里下一个 response。"""
    client = MagicMock()
    client.create.side_effect = list(responses)
    return client


# ============================================================
# brief_input
# ============================================================

class TestBriefInput:
    def test_path(self):
        from tool_runtime import brief_input
        assert brief_input({"path": "raw/foo.md"}) == "raw/foo.md"

    def test_short_command(self):
        from tool_runtime import brief_input
        assert brief_input({"command": "ls -la"}) == "ls -la"

    def test_long_command_truncated(self):
        from tool_runtime import brief_input
        cmd = "a" * 100
        result = brief_input({"command": cmd})
        assert result.endswith("...")
        assert len(result) == 63  # 60 + "..."

    def test_pattern(self):
        from tool_runtime import brief_input
        assert brief_input({"pattern": "def foo"}) == "def foo"

    def test_empty(self):
        from tool_runtime import brief_input
        assert brief_input({}) == ""
        assert brief_input({"other_field": "x"}) == ""


# ============================================================
# process_tool_result
# ============================================================

class TestProcessToolResult:
    def test_empty_result(self, tmp_path):
        from tool_runtime import process_tool_result
        assert "执行完成" in process_tool_result("", "read_file", str(tmp_path))
        assert "执行完成" in process_tool_result("   \n", "read_file", str(tmp_path))

    def test_blocked_passthrough(self, tmp_path):
        from tool_runtime import process_tool_result
        msg = "[blocked] path outside workspace"
        assert process_tool_result(msg, "read_file", str(tmp_path)) == msg

    def test_error_passthrough(self, tmp_path):
        from tool_runtime import process_tool_result
        msg = "[error] boom"
        assert process_tool_result(msg, "read_file", str(tmp_path)) == msg

    def test_small_result_unchanged(self, tmp_path):
        from tool_runtime import process_tool_result
        msg = "hello world"
        assert process_tool_result(msg, "read_file", str(tmp_path)) == msg

    def test_large_result_persisted(self, tmp_path):
        from tool_runtime import process_tool_result, TOOL_RESULT_PERSIST_THRESHOLD
        # 构造一个超过阈值且有换行的大串
        line = "abcdefghij\n"
        big = line * ((TOOL_RESULT_PERSIST_THRESHOLD // len(line)) + 200)
        result = process_tool_result(big, "search_files", str(tmp_path))
        # 1. 返回里带预览 + 提示
        assert "[完整结果已保存至" in result
        assert f"{len(big)} 字符" in result
        # 2. 实际磁盘落盘
        persist_dir = os.path.join(str(tmp_path), "output", ".tool_results")
        files = os.listdir(persist_dir)
        assert len(files) == 1
        assert files[0].startswith("search_files_")
        # 3. 预览不超过 2KB
        preview_part = result.split("\n...\n")[0]
        assert len(preview_part) <= 2000


# ============================================================
# _execute_tool_calls (分流 + 并发)
# ============================================================

class TestExecuteToolCalls:
    def test_single_safe_call_serial(self, tmp_path):
        """单个只读工具走串行分支。"""
        from tool_runtime import _execute_tool_calls
        tc = _tool_use_block("id1", "read_file", {"path": "a.md"})
        with patch("tool_runtime.safe_execute_tool", return_value="content A") as mock_exec:
            executed = _execute_tool_calls([tc], str(tmp_path))
        assert executed == {"id1": "content A"}
        assert mock_exec.call_count == 1

    def test_multiple_safe_calls_concurrent(self, tmp_path):
        """多个只读工具走并发分支。"""
        from tool_runtime import _execute_tool_calls
        tcs = [
            _tool_use_block(f"id{i}", "read_file", {"path": f"{i}.md"})
            for i in range(3)
        ]
        with patch("tool_runtime.safe_execute_tool",
                   side_effect=lambda name, inp, ws: f"result-{inp['path']}") as mock_exec:
            executed = _execute_tool_calls(tcs, str(tmp_path))
        assert executed == {"id0": "result-0.md", "id1": "result-1.md", "id2": "result-2.md"}
        assert mock_exec.call_count == 3

    def test_unsafe_call_serial(self, tmp_path):
        """写工具强制串行。"""
        from tool_runtime import _execute_tool_calls
        tc = _tool_use_block("w1", "write_file", {"path": "x", "content": "y"})
        with patch("tool_runtime.is_concurrency_safe_tool", return_value=False), \
             patch("tool_runtime.safe_execute_tool", return_value="wrote") as mock_exec:
            executed = _execute_tool_calls([tc], str(tmp_path))
        assert executed == {"w1": "wrote"}
        mock_exec.assert_called_once()

    def test_concurrent_exception_captured(self, tmp_path):
        """并发 future 抛异常时,结果打 [error] 前缀不传染其他。"""
        from tool_runtime import _execute_tool_calls
        tcs = [
            _tool_use_block("ok", "read_file", {"path": "ok.md"}),
            _tool_use_block("bad", "read_file", {"path": "bad.md"}),
        ]

        def _side(name, inp, ws):
            if inp["path"] == "bad.md":
                raise RuntimeError("disk burn")
            return "good"

        with patch("tool_runtime.safe_execute_tool", side_effect=_side):
            executed = _execute_tool_calls(tcs, str(tmp_path))
        assert executed["ok"] == "good"
        assert executed["bad"].startswith("[error]")
        assert "disk burn" in executed["bad"]


# ============================================================
# tool_loop 主循环
# ============================================================

class TestToolLoop:
    def test_end_turn_terminates_immediately(self, tmp_path):
        """一轮 end_turn 后应该 break,不再继续调 client.create。"""
        from tool_runtime import tool_loop
        client = _mk_client([_response([_text_block("done")], stop_reason="end_turn")])
        msgs = tool_loop(client, "sonnet", [], [{"role": "user", "content": "hi"}],
                         str(tmp_path), max_turns=5)
        assert client.create.call_count == 1
        # 最后一条 assistant 消息是文本聚合
        assert msgs[-1]["role"] == "assistant"
        assert "done" in msgs[-1]["content"]

    def test_tool_use_then_end_turn(self, tmp_path):
        """第一轮 tool_use → 执行工具 → 第二轮 end_turn。"""
        from tool_runtime import tool_loop
        tu = _tool_use_block("t1", "read_file", {"path": "x.md"})
        client = _mk_client([
            _response([_text_block("让我读一下"), tu], stop_reason="tool_use"),
            _response([_text_block("ok 看完了")], stop_reason="end_turn"),
        ])
        with patch("tool_runtime.safe_execute_tool", return_value="file body"):
            msgs = tool_loop(client, "sonnet", [],
                             [{"role": "user", "content": "read it"}],
                             str(tmp_path), max_turns=5)
        assert client.create.call_count == 2
        # 消息序列: user(原) / assistant(tool_use) / user(tool_result) / assistant(text)
        roles = [m["role"] for m in msgs]
        assert roles == ["user", "assistant", "user", "assistant"]
        # tool_result block 包含真实结果
        tr = msgs[2]["content"][0]
        assert tr["type"] == "tool_result"
        assert tr["tool_use_id"] == "t1"
        assert "file body" in tr["content"]

    def test_wall_clock_timeout_raises(self, tmp_path):
        """limit=0 时首轮就触发 AgentTimeoutError。"""
        from tool_runtime import tool_loop
        from exceptions import AgentTimeoutError
        client = _mk_client([_response([_text_block("x")], stop_reason="end_turn")])
        with pytest.raises(AgentTimeoutError) as ei:
            # wall_clock_limit=-1 保证 elapsed > limit
            tool_loop(client, "sonnet", [], [{"role": "user", "content": "x"}],
                      str(tmp_path), max_turns=5, wall_clock_limit=-1)
        assert "超时" in str(ei.value)
        # client 根本没被调用,因为第一轮就超时了
        assert client.create.call_count == 0

    def test_api_error_breaks_loop(self, tmp_path):
        """text block 以 [API error] 开头时立即 break。"""
        from tool_runtime import tool_loop
        client = _mk_client([
            _response([_text_block("[API error] 503 upstream")], stop_reason="end_turn"),
        ])
        msgs = tool_loop(client, "sonnet", [], [{"role": "user", "content": "x"}],
                         str(tmp_path), max_turns=5)
        # 只调了一次,之后 break
        assert client.create.call_count == 1

    def test_max_turns_respected(self, tmp_path):
        """stop_reason 非 end_turn 且无 tool_use 时会继续 '请继续。',
        max_turns 上限到了就终止不抛异常。"""
        from tool_runtime import tool_loop
        # 构造 3 个都没 tool_use 也不 end_turn 的响应
        client = _mk_client([
            _response([_text_block(f"turn{i}")], stop_reason="other")
            for i in range(3)
        ])
        msgs = tool_loop(client, "sonnet", [], [{"role": "user", "content": "x"}],
                         str(tmp_path), max_turns=3)
        assert client.create.call_count == 3

    def test_turn_callback_invoked(self, tmp_path):
        """turn_callback 每轮尾调用一次。"""
        from tool_runtime import tool_loop
        tu = _tool_use_block("t1", "read_file", {"path": "x.md"})
        client = _mk_client([
            _response([tu], stop_reason="tool_use"),
            _response([_text_block("ok")], stop_reason="end_turn"),
        ])
        cb = MagicMock()
        with patch("tool_runtime.safe_execute_tool", return_value="body"):
            tool_loop(client, "sonnet", [], [{"role": "user", "content": "x"}],
                      str(tmp_path), max_turns=5, turn_callback=cb)
        # 第一轮有 tool_use 会触发 cb,第二轮 end_turn 前 break(cb 不调用)
        assert cb.call_count == 1
