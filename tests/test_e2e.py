"""
端到端测试 -- 用 mock API 验证完整评审流程
"""

import os
import sys
import json
import tempfile
import pytest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ============================================================
# Mock 工具
# ============================================================

def _make_mock_response(items, dimension="测试维度"):
    """构建一个模拟的 tool_use 响应"""
    tool_input = {"dimension": dimension, "items": items}
    tool_block = MagicMock()
    tool_block.type = "tool_use"
    tool_block.name = "submit_review_items"
    tool_block.input = tool_input

    response = MagicMock()
    response.content = [tool_block]
    response.stop_reason = "tool_use"
    response.usage = {"input_tokens": 100, "output_tokens": 50}
    return response


def _make_text_response(text):
    """构建一个纯文本响应（没调 tool）"""
    text_block = MagicMock()
    text_block.type = "text"
    text_block.text = text

    response = MagicMock()
    response.content = [text_block]
    response.stop_reason = "end_turn"
    response.usage = {"input_tokens": 100, "output_tokens": 50}
    return response


SAMPLE_ITEMS = [
    {
        "rule_id": "RC-009",
        "location": "§2.2",
        "issue": "跨表字段未标注优先级",
        "suggestion": "补充优先级说明",
        "severity": "must",
        "evidence_type": "B",
        "evidence_content": "RC-009 规则原文",
    },
    {
        "rule_id": "RC-010",
        "location": "§3.6",
        "issue": "数值阈值未标注来源",
        "suggestion": "标注来源",
        "severity": "must",
        "evidence_type": "B",
        "evidence_content": "RC-010 规则原文",
    },
]


# ============================================================
# 测试 1：完整评审流程 mock
# ============================================================

class TestFullReviewPipeline:
    def test_parallel_review_sync_mock(self):
        """mock API，验证 parallel_review_sync 能走完完整流程"""
        from parallel_review import parallel_review_sync

        mock_client = MagicMock()
        mock_client.create.return_value = _make_mock_response(SAMPLE_ITEMS)

        result = parallel_review_sync(
            mock_client, "这是一篇测试 PRD", {},
            {"opus": "test", "sonnet": "test", "haiku": "test"},
        )

        assert "merged_items" in result
        assert "workers" in result
        assert len(result["workers"]) == 4  # 4 个维度
        # 每个 Worker 都返回了 2 条 items，合并去重后应 <= 8
        assert len(result["merged_items"]) > 0
        for item in result["merged_items"]:
            assert "rule_id" in item
            assert "issue" in item
            assert "dimension" in item


# ============================================================
# 测试 2：多数投票
# ============================================================

class TestMajorityVoteIntegration:
    def test_keeps_items_appearing_twice(self):
        """2/3 轮出现的 item 应该保留"""
        from parallel_review import majority_vote

        run1 = [
            {"id": "R-001", "rule_id": "RC-009", "location": "§2.2", "issue": "跨表字段未标注优先级", "severity": "must"},
            {"id": "R-002", "rule_id": "V-03", "location": "§1.1", "issue": "信息密度低", "severity": "should"},
        ]
        run2 = [
            {"id": "R-001", "rule_id": "RC-009", "location": "§2.2", "issue": "字段映射缺优先级", "severity": "must"},
            {"id": "R-002", "rule_id": "RC-010", "location": "§3.6", "issue": "数值未标注来源", "severity": "must"},
        ]
        run3 = [
            {"id": "R-001", "rule_id": "RC-009", "location": "§2.2", "issue": "跨表优先级缺失", "severity": "must"},
        ]

        voted = majority_vote([run1, run2, run3], min_votes=2)

        # RC-009 出现 3 次，必须保留
        rule_ids = [item["rule_id"] for item in voted]
        assert "RC-009" in rule_ids

        # V-03 只出现 1 次，应该被过滤
        assert "V-03" not in rule_ids

    def test_empty_rounds(self):
        """全空轮次应返回空"""
        from parallel_review import majority_vote
        assert majority_vote([[], [], []], min_votes=2) == []


# ============================================================
# 测试 3：苍鹰 apply_advisor_result
# ============================================================

class TestGoshawkApplyAdvisor:
    def test_removes_false_positive_and_adds_finding(self):
        """验证误报移除 + 补充添加"""
        from goshawk_advisor import apply_advisor_result

        items = [
            {"id": "R-001", "rule_id": "RC-009", "severity": "must", "issue": "问题1"},
            {"id": "R-002", "rule_id": "RC-010", "severity": "must", "issue": "问题2"},
        ]
        advisor_result = {
            "flagged_as_false_positive": [
                {"item_id": "R-001", "reason": "PRD 其他位置已解释", "recommendation": "移除"},
            ],
            "additional_findings": [
                {
                    "rule_id": "RC-005",
                    "location": "§4",
                    "issue": "缺少四态 UI",
                    "suggestion": "补充",
                    "severity": "must",
                    "evidence_type": "B",
                    "evidence_content": "RC-005",
                },
            ],
            "conflict_resolutions": [],
        }

        result = apply_advisor_result(items, advisor_result)

        # R-001 被移除
        result_ids = [i["id"] for i in result]
        assert "R-001" not in result_ids

        # R-002 保留
        assert "R-002" in result_ids

        # 苍鹰补充项被添加
        assert any(i.get("rule_id") == "RC-005" for i in result)


# ============================================================
# 测试 4：文本兜底解析
# ============================================================

class TestWorkerToolFallback:
    def test_parse_items_from_text(self):
        """模型没调 tool 但返回了 JSON 文本时，能提取改进项"""
        from parallel_review import _parse_items_from_text

        text = """以下是评审结果：
[
  {"rule_id": "RC-009", "location": "§2.2", "issue": "字段映射缺优先级", "suggestion": "补充", "severity": "must", "evidence_type": "B", "evidence_content": "RC-009"}
]
"""
        items = _parse_items_from_text(text)
        assert len(items) == 1
        assert items[0]["rule_id"] == "RC-009"

    def test_parse_empty_text(self):
        """空文本返回空列表"""
        from parallel_review import _parse_items_from_text
        assert _parse_items_from_text("没有 JSON 内容") == []

    def test_parse_malformed_json(self):
        """畸形 JSON 不崩溃"""
        from parallel_review import _parse_items_from_text
        assert _parse_items_from_text("[{broken json}") == []


# ============================================================
# 测试 5：安全围栏
# ============================================================

class TestSecuritySearchBlocked:
    def test_search_files_in_sessions_blocked(self):
        """搜索 .sessions/ 路径应该被拦截"""
        from security import safe_execute_tool

        with tempfile.TemporaryDirectory() as workspace:
            # 创建 .sessions 目录
            sessions_dir = os.path.join(workspace, "output", ".sessions")
            os.makedirs(sessions_dir)
            with open(os.path.join(sessions_dir, "test.jsonl"), "w") as f:
                f.write('{"secret": "data"}')

            result = safe_execute_tool(
                "search_files",
                {"pattern": "secret", "path": "output/.sessions/"},
                workspace,
            )
            assert "[blocked]" in result

    def test_list_directory_in_sessions_blocked(self):
        """列举 .sessions/ 目录应该被拦截"""
        from security import safe_execute_tool

        with tempfile.TemporaryDirectory() as workspace:
            sessions_dir = os.path.join(workspace, "output", ".sessions")
            os.makedirs(sessions_dir)

            result = safe_execute_tool(
                "list_directory",
                {"path": "output/.sessions/"},
                workspace,
            )
            assert "[blocked]" in result
