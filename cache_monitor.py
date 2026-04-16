"""
Pattern 18: Prompt Cache Break Detection (CC 模式)

检测 Anthropic API 的 prompt cache 失效并诊断原因。
每个 Worker 持有独立的 PromptCacheMonitor 实例(线程安全)。

用法:
    monitor = PromptCacheMonitor()
    monitor.snapshot(system_text, tools_json, model, dim_key="structure")
    response = client.create(...)
    monitor.check(response.usage)
"""

import hashlib

from logger import get_logger

log = get_logger("api")


class PromptCacheMonitor:
    """CC 模式: 检测 prompt cache 失效并诊断原因。

    每个 worker 线程一个实例,无共享状态,天然线程安全。
    """

    def __init__(self):
        self.prev_cache_read = 0
        self.prev_hashes = {}
        self.pending = {}

    def snapshot(self, system_text: str, tools_json: str, model: str, dim_key: str = ""):
        """API 调用前做快照,记录各段的 hash 用于后续 diff 诊断。"""
        self.pending = {
            "system_hash": hashlib.md5(system_text.encode()).hexdigest()[:8],
            "tools_hash": hashlib.md5(tools_json.encode()).hexdigest()[:8],
            "model": model,
            "dim_key": dim_key,
        }

    def check(self, usage: dict):
        """API 响应后检查 cache break。

        当 cache_read_input_tokens 比上次大幅下降(> 2000 tokens)时,
        说明 prompt cache 失效,log warning 并诊断原因。
        """
        cache_read = usage.get("cache_read_input_tokens", 0)
        if self.prev_cache_read > 0 and (self.prev_cache_read - cache_read) > 2000:
            reasons = self._diagnose()
            drop = self.prev_cache_read - cache_read
            dim_key = self.pending.get("dim_key", "?")
            log.warning(
                f"[CACHE BREAK] dim={dim_key} drop={drop} tokens, reasons={reasons}"
            )
        self.prev_cache_read = cache_read
        self.prev_hashes = self.pending.copy()

    def _diagnose(self) -> list:
        """对比 snapshot 前后各段 hash,找出变化的部分。"""
        reasons = []
        for key in ("system_hash", "tools_hash", "model"):
            old = self.prev_hashes.get(key)
            new = self.pending.get(key)
            if old and new and old != new:
                reasons.append(f"{key} changed: {old}->{new}")
        return reasons or ["unknown (possible TTL expiry)"]
