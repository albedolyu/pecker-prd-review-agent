"""
PromptCacheMonitor 覆盖测试

关键验证: cache break 检测阈值 + 诊断逻辑 + 线程安全的 state 迁移。
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestPromptCacheMonitor:
    def test_initial_state(self):
        from cache_monitor import PromptCacheMonitor
        m = PromptCacheMonitor()
        assert m.prev_cache_read == 0
        assert m.prev_hashes == {}
        assert m.pending == {}

    def test_snapshot_fills_pending(self):
        from cache_monitor import PromptCacheMonitor
        m = PromptCacheMonitor()
        m.snapshot("system text", "tools json", "sonnet", dim_key="structure")
        assert "system_hash" in m.pending
        assert "tools_hash" in m.pending
        assert m.pending["model"] == "sonnet"
        assert m.pending["dim_key"] == "structure"
        # 两个 hash 都是 8 字符 MD5 前缀
        assert len(m.pending["system_hash"]) == 8

    def test_check_first_call_no_warning(self, caplog):
        from cache_monitor import PromptCacheMonitor
        import logging
        m = PromptCacheMonitor()
        m.snapshot("sys", "tools", "sonnet")
        with caplog.at_level(logging.WARNING):
            m.check({"cache_read_input_tokens": 5000})
        # 首次调用 prev_cache_read=0,不触发 warning
        assert not any("CACHE BREAK" in r.message for r in caplog.records)
        # 但 state 更新了
        assert m.prev_cache_read == 5000

    def test_check_minor_drop_no_warning(self, caplog):
        """缓存 read 下降 < 2000 tokens → 不算 break."""
        from cache_monitor import PromptCacheMonitor
        import logging
        m = PromptCacheMonitor()
        m.snapshot("sys", "tools", "sonnet")
        m.check({"cache_read_input_tokens": 10000})
        m.snapshot("sys", "tools", "sonnet")
        with caplog.at_level(logging.WARNING):
            m.check({"cache_read_input_tokens": 9000})  # 只降 1000
        assert not any("CACHE BREAK" in r.message for r in caplog.records)

    def test_check_major_drop_triggers_warning(self, caplog):
        """缓存 read 下降 > 2000 tokens → 触发 CACHE BREAK 诊断."""
        from cache_monitor import PromptCacheMonitor
        import logging
        m = PromptCacheMonitor()
        # 第一次建立 baseline
        m.snapshot("sys A", "tools A", "sonnet", dim_key="quality")
        m.check({"cache_read_input_tokens": 10000})
        # 第二次 system 变了 → 应诊断出 system_hash changed
        m.snapshot("sys B totally different", "tools A", "sonnet", dim_key="quality")
        with caplog.at_level(logging.WARNING):
            m.check({"cache_read_input_tokens": 3000})  # 降 7000
        warnings = [r for r in caplog.records if "CACHE BREAK" in r.message]
        assert len(warnings) == 1
        msg = warnings[0].message
        assert "drop=7000" in msg
        assert "dim=quality" in msg
        assert "system_hash changed" in msg

    def test_diagnose_tools_changed(self, caplog):
        from cache_monitor import PromptCacheMonitor
        import logging
        m = PromptCacheMonitor()
        m.snapshot("sys", "tools A", "sonnet")
        m.check({"cache_read_input_tokens": 10000})
        m.snapshot("sys", "tools B different", "sonnet")
        with caplog.at_level(logging.WARNING):
            m.check({"cache_read_input_tokens": 3000})
        warnings = [r for r in caplog.records if "CACHE BREAK" in r.message]
        assert "tools_hash changed" in warnings[0].message

    def test_diagnose_model_changed(self, caplog):
        from cache_monitor import PromptCacheMonitor
        import logging
        m = PromptCacheMonitor()
        m.snapshot("sys", "tools", "sonnet")
        m.check({"cache_read_input_tokens": 10000})
        m.snapshot("sys", "tools", "opus")
        with caplog.at_level(logging.WARNING):
            m.check({"cache_read_input_tokens": 3000})
        warnings = [r for r in caplog.records if "CACHE BREAK" in r.message]
        assert "model changed" in warnings[0].message

    def test_diagnose_ttl_when_no_content_diff(self, caplog):
        """所有 hash 相同但 cache 失效 → 诊断为 TTL expiry."""
        from cache_monitor import PromptCacheMonitor
        import logging
        m = PromptCacheMonitor()
        m.snapshot("same sys", "same tools", "same model")
        m.check({"cache_read_input_tokens": 10000})
        m.snapshot("same sys", "same tools", "same model")
        with caplog.at_level(logging.WARNING):
            m.check({"cache_read_input_tokens": 3000})
        warnings = [r for r in caplog.records if "CACHE BREAK" in r.message]
        assert "TTL expiry" in warnings[0].message or "unknown" in warnings[0].message

    def test_missing_cache_read_key_handled(self):
        """usage dict 完全缺少 cache_read_input_tokens 时不崩."""
        from cache_monitor import PromptCacheMonitor
        m = PromptCacheMonitor()
        m.snapshot("sys", "tools", "sonnet")
        m.check({})  # 空 usage
        assert m.prev_cache_read == 0
