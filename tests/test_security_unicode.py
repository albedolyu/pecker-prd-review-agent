"""
security.sanitize_unicode 覆盖测试 (Round 12)

这是 prompt injection 防御的最后一道门 (隐形字符过滤)。错一处就可能让恶意 PRD
把 BOM / 零宽字符 / 格式字符 插入 wiki,影响后续读取。
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestSanitizeUnicode:
    def test_plain_ascii_unchanged(self):
        from security import sanitize_unicode
        assert sanitize_unicode("hello world") == "hello world"

    def test_chinese_kept(self):
        from security import sanitize_unicode
        assert sanitize_unicode("产品需求") == "产品需求"

    def test_zero_width_space_removed(self):
        """U+200B (ZWSP) 属于 Cf 类别,应被移除."""
        from security import sanitize_unicode
        dirty = "hello\u200bworld"
        clean = sanitize_unicode(dirty)
        assert "\u200b" not in clean
        assert clean == "helloworld"

    def test_zero_width_non_joiner_removed(self):
        """U+200C (ZWNJ) 同样被移除."""
        from security import sanitize_unicode
        assert "\u200c" not in sanitize_unicode("a\u200cb")

    def test_left_to_right_mark_removed(self):
        """U+200E (LRM) / U+200F (RLM) 属于 Cf."""
        from security import sanitize_unicode
        assert "\u200e" not in sanitize_unicode("a\u200eb")
        assert "\u200f" not in sanitize_unicode("a\u200fb")

    def test_bom_removed(self):
        """U+FEFF BOM 属于 Cf."""
        from security import sanitize_unicode
        assert "\ufeff" not in sanitize_unicode("\ufeffhello")

    def test_nfkc_normalization(self):
        """全角 ＡＢＣ → 半角 ABC."""
        from security import sanitize_unicode
        assert sanitize_unicode("ＡＢＣ") == "ABC"

    def test_non_string_passthrough(self):
        """非 str 原样返回,不崩."""
        from security import sanitize_unicode
        assert sanitize_unicode(None) is None
        assert sanitize_unicode(123) == 123
        assert sanitize_unicode([1, 2]) == [1, 2]

    def test_mixed_content(self):
        """一长串混合内容,隐藏字符清掉,可见内容保留."""
        from security import sanitize_unicode
        dirty = "正\u200b常\u200c 内\ufeff容 ＡＢＣ"
        clean = sanitize_unicode(dirty)
        assert "\u200b" not in clean
        assert "\u200c" not in clean
        assert "\ufeff" not in clean
        assert "正" in clean
        assert "常" in clean
        assert "ABC" in clean  # 全角转半角

    def test_empty_string(self):
        from security import sanitize_unicode
        assert sanitize_unicode("") == ""

    def test_only_invisible_chars(self):
        """全部是 Cf 字符 → 返回空串."""
        from security import sanitize_unicode
        assert sanitize_unicode("\u200b\u200c\u200d\ufeff") == ""

    def test_emoji_kept(self):
        """emoji 不应被移除 (是 So Symbol,不在 Cf/Co/Cn 黑名单)."""
        from security import sanitize_unicode
        result = sanitize_unicode("hello 🚀 world")
        assert "🚀" in result
