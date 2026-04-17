"""
api_adapter._parse_json_from_text 3 层 fallback 测试

重点覆盖 L3 (json-repair) — 处理 shadow run 里出现过的 CLI JSON parse 失败
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture
def parser():
    """跳过 __init__ 里的 shutil.which 等副作用,直接拿 method."""
    from api_adapter import ClaudeCodeCLIClient
    # 避开完整 __init__,用 bound method
    c = ClaudeCodeCLIClient.__new__(ClaudeCodeCLIClient)
    return c._parse_json_from_text


class TestL1PlainJson:
    def test_standard_object(self, parser):
        assert parser('{"items": [{"id": "R-001"}]}', "submit_review_items") == {
            "items": [{"id": "R-001"}]
        }

    def test_empty_returns_none(self, parser):
        assert parser("", "submit_review_items") is None
        assert parser(None, "submit_review_items") is None

    def test_whitespace_only(self, parser):
        assert parser("   \n  ", "submit_review_items") is None

    def test_markdown_fence_stripped(self, parser):
        text = '```json\n{"items": []}\n```'
        assert parser(text, "submit_review_items") == {"items": []}

    def test_markdown_fence_no_lang(self, parser):
        text = '```\n{"k": 1}\n```'
        assert parser(text, "submit_review_items") == {"k": 1}


class TestL2SliceBraces:
    def test_leading_prose_stripped(self, parser):
        text = 'Here is my review:\n{"items": [{"id": "R-001"}]}\nEnd'
        result = parser(text, "submit_review_items")
        assert result == {"items": [{"id": "R-001"}]}

    def test_trailing_prose_stripped(self, parser):
        text = '{"ok": true} -- done'
        assert parser(text, "submit_review_items") == {"ok": True}


class TestL3JsonRepair:
    """L3 fallback: 依赖 json-repair 包,这是 shadow run 新增的防御层."""

    def test_single_quotes(self, parser):
        """LLM 偶尔用单引号 (Python style),json-repair 能修."""
        text = "{'items': [{'id': 'R-001'}]}"
        result = parser(text, "submit_review_items")
        assert isinstance(result, dict)
        assert result.get("items") == [{"id": "R-001"}]

    def test_trailing_comma(self, parser):
        """末尾多余逗号."""
        text = '{"items": [{"id": "R-001"},],}'
        result = parser(text, "submit_review_items")
        assert isinstance(result, dict)
        assert len(result["items"]) == 1

    def test_python_true_false_none(self, parser):
        """LLM 偶尔用 Python 布尔/None。

        json-repair 0.50 版本里 True → True (好), None → "None" (string,可接受)。
        核心诉求是"不抛异常 + 返回 dict",精确类型映射次要。
        """
        text = '{"ok": True, "err": None, "items": []}'
        result = parser(text, "submit_review_items")
        assert isinstance(result, dict)
        assert result.get("ok") is True
        # "err" 存在即可,值可能是 None 或 "None" 字符串都算修复成功
        assert "err" in result
        assert result["items"] == []

    def test_unquoted_keys(self, parser):
        """无引号 key."""
        text = '{items: [{id: "R-001"}]}'
        result = parser(text, "submit_review_items")
        assert isinstance(result, dict)

    def test_unclosed_brace_attempts_repair(self, parser):
        """未闭合的 },json-repair 会尝试补齐."""
        text = '{"items": [{"id": "R-001"}'
        result = parser(text, "submit_review_items")
        # json-repair 通常能补,但即使补不了也返回 None 不崩
        assert result is None or isinstance(result, dict)

    def test_pure_garbage_returns_none(self, parser):
        """完全无法解析的垃圾返回 None,不抛."""
        result = parser("<<<not json at all@@@>>>", "submit_review_items")
        assert result is None


class TestEndToEnd:
    def test_failure_mode_from_shadow_2639chars(self, parser):
        """模拟 shadow run 里出现过的 2639 chars text_result 失败场景的特征:
        合法 json 外面裹着 markdown + 末尾 Python-style 常量。
        """
        # 构造一个实际 LLM 可能产出的混乱输出
        text = (
            "Here are the review items I found:\n\n"
            "```json\n"
            "{'dimension': 'quality',\n"
            " 'items': [\n"
            "   {'id': 'R-001', 'severity': 'must', 'confidence': 0.85,},\n"
            "   {'id': 'R-002', 'severity': 'should', 'pending': None,}\n"
            " ]}\n"
            "```\n"
            "Hope this helps!"
        )
        result = parser(text, "submit_review_items")
        # 应该能挖出 items 列表
        assert isinstance(result, dict)
        assert "items" in result
        assert len(result["items"]) >= 2
