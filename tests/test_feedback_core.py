"""
feedback.py 核心函数覆盖测试 (Round 11)

_normalize_status 和 _match_signal_to_item 是信号匹配/评分闭环的门环,
错一处会影响 rule score EMA 反馈的正确性,进而影响 worker prompt 演化。
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestNormalizeStatus:
    def test_none_returns_unknown(self):
        from feedback import _normalize_status
        assert _normalize_status(None) == "unknown"
        assert _normalize_status("") == "unknown"

    def test_confirmed_variants(self):
        from feedback import _normalize_status
        assert _normalize_status("已确认") == "confirmed"
        assert _normalize_status("用户接受") == "confirmed"
        assert _normalize_status("✅ ok") == "confirmed"

    def test_rejected_variants(self):
        from feedback import _normalize_status
        assert _normalize_status("驳回") == "rejected"
        assert _normalize_status("❌ no") == "rejected"

    def test_pending_variants(self):
        from feedback import _normalize_status
        assert _normalize_status("待确定") == "pending"
        assert _normalize_status("⚠ 稍后") == "pending"

    def test_unknown_falls_through(self):
        from feedback import _normalize_status
        assert _normalize_status("abc xyz") == "unknown"

    def test_mixed_keywords_takes_first_match(self):
        """'确认' 和 '驳回' 都出现 → confirmed (先检查到)."""
        from feedback import _normalize_status
        result = _normalize_status("先确认后被驳回")
        # 按源码逻辑,确认 在 驳回 之前检查 → confirmed
        assert result == "confirmed"


class TestMatchSignalToItem:
    def _item(self, location="搜索接口", problem="未说明错误码"):
        return {"location": location, "problem": problem, "id": "R-001"}

    def test_empty_item_no_match(self):
        from feedback import _match_signal_to_item
        matched, conf = _match_signal_to_item(
            {"content": "anything"}, {"location": "", "problem": ""},
        )
        assert matched is False
        assert conf == 0.0

    def test_file_path_match_gives_points(self):
        """signal.file 包含 location 关键词 → 路径 +2 + 关键词 +N ≥ 2 → 命中."""
        from feedback import _match_signal_to_item
        item = self._item(location="搜索接口", problem="未说明错误码")
        signal = {"file": "src/搜索接口.py", "content": "fix bug"}
        matched, conf = _match_signal_to_item(signal, item)
        assert matched is True
        assert conf > 0

    def test_keyword_content_match(self):
        from feedback import _match_signal_to_item
        # item_text 分词结果: ["搜索接口", "字段映射缺失"]
        # signal.content 必须精确包含这些整词才能计 +1,2+ 分才命中
        item = self._item(location="搜索接口", problem="字段映射缺失")
        signal = {
            "file": "unrelated.py",
            "content": "修复 字段映射缺失 相关 bug,搜索接口 对接",
        }
        matched, conf = _match_signal_to_item(signal, item)
        assert matched is True

    def test_type_affinity_assumption(self):
        from feedback import _match_signal_to_item
        item = {"location": "X", "problem": "未说明超时处理"}
        signal = {"type": "assumption", "content": "assumption timeout",
                  "file": "x.py"}
        matched, conf = _match_signal_to_item(signal, item)
        # type affinity: "未说明" 在 item → +1;但只 1 分不够 2,
        # 加上关键词命中凑分
        # 这个 case 本质验证 type_affinity 的键值表配置不崩
        assert isinstance(conf, float)
        assert 0 <= conf <= 1.0

    def test_confidence_capped_at_one(self):
        from feedback import _match_signal_to_item
        # 造一个所有维度都命中的 signal,验证 confidence ≤ 1.0
        item = {"location": "搜索接口字段映射", "problem": "字段映射 未说明 待确认"}
        signal = {
            "type": "assumption",
            "file": "搜索接口字段映射.py",
            "content": "字段映射 未说明 待确认 搜索接口 搜索 映射",
        }
        matched, conf = _match_signal_to_item(signal, item)
        assert matched is True
        assert conf <= 1.0

    def test_stop_words_filtered(self):
        """只有 stop word 命中 → 不应计分。"""
        from feedback import _match_signal_to_item
        item = {"location": "第3章", "problem": "的 和 与"}
        signal = {"content": "第 的 章 节", "file": "x.py"}
        matched, conf = _match_signal_to_item(signal, item)
        assert matched is False

    def test_path_match_used_only_once(self):
        """即使 file 路径中多段匹配 item 关键词,路径加分最多 +2(break)."""
        from feedback import _match_signal_to_item
        item = {"location": "搜索-接口-字段", "problem": "问题"}
        signal = {"file": "搜索/接口/字段.py", "content": ""}
        # path 命中 +2 + 可能的 keyword +1..
        # 本测试只验证不超出合理范围
        matched, conf = _match_signal_to_item(signal, item)
        # 即使匹配也 ≤ 1
        assert conf <= 1.0
