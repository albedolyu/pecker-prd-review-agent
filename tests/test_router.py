"""
router 模块单测 — 覆盖 route_intent 容错 + build_system_blocks cache_control 排列
"""

import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from router import route_intent, build_system_blocks


def _mk_client_response(text):
    """构造符合 client.create 返回格式的 mock (response.content[0].text)"""
    block = MagicMock()
    block.text = text
    resp = MagicMock()
    resp.content = [block]
    client = MagicMock()
    client.create.return_value = resp
    return client


class TestRouteIntent:
    def test_valid_tier_returned(self):
        client = _mk_client_response("opus")
        assert route_intent(client, "复杂项目评审") == "opus"

    def test_sonnet_tier(self):
        client = _mk_client_response("sonnet")
        assert route_intent(client, "普通 PRD") == "sonnet"

    def test_haiku_tier(self):
        client = _mk_client_response("haiku")
        assert route_intent(client, "简单标签") == "haiku"

    def test_invalid_tier_falls_back_to_sonnet(self):
        client = _mk_client_response("flash")
        assert route_intent(client, "foo") == "sonnet"

    def test_whitespace_and_case_normalized(self):
        client = _mk_client_response("  OPUS  \n")
        assert route_intent(client, "foo") == "opus"

    def test_client_exception_falls_back_to_sonnet(self):
        client = MagicMock()
        client.create.side_effect = RuntimeError("api down")
        assert route_intent(client, "foo") == "sonnet"


class TestBuildSystemBlocks:
    def test_single_block_no_prd_no_workspace(self):
        blocks = build_system_blocks("你是啄木鸟")
        assert len(blocks) == 1
        assert blocks[0]["type"] == "text"
        assert blocks[0]["text"] == "你是啄木鸟"
        assert blocks[0]["cache_control"] == {"type": "ephemeral"}

    def test_with_prd_content_adds_second_block(self):
        blocks = build_system_blocks("sys", prd_content="PRD 原文")
        assert len(blocks) == 2
        assert "PRD 原文" in blocks[1]["text"]
        assert blocks[1]["cache_control"] == {"type": "ephemeral"}

    def test_workspace_without_scratchpad_no_third_block(self, tmp_path):
        # read_scratchpad 在没有 scratchpad 文件时返回空串
        with patch("context_manager.read_scratchpad", return_value=""):
            blocks = build_system_blocks("sys", workspace=str(tmp_path))
        assert len(blocks) == 1

    def test_workspace_with_scratchpad_adds_third_block(self, tmp_path):
        with patch("context_manager.read_scratchpad", return_value="当前在 Phase 2"):
            blocks = build_system_blocks("sys", prd_content="PRD", workspace=str(tmp_path))
        assert len(blocks) == 3
        assert "当前在 Phase 2" in blocks[2]["text"]
        # scratchpad block 不应有 cache_control (会变)
        assert "cache_control" not in blocks[2]
