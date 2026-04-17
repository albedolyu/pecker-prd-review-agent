"""Token 用量 + 成本追踪 + token 预估.

从 api_adapter.py 拆出 (2026-04-16):
- TokenTracker: 线程安全的累积统计 (input/output/cache_read/cache_creation)
- compute_call_cost_usd: 单次调用成本 (CC cost-tracker.ts querySource 模式)
- estimate_tokens / estimate_message_tokens: 本地粗估,参考 CC tokenEstimation.ts
"""

import json
import threading

from clients.shared import MODEL_PRICING


class TokenTracker:
    """累积 token 用量统计（含 prompt cache 维度）"""
    def __init__(self):
        self._lock = threading.Lock()
        self.calls = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.cache_creation_tokens = 0
        self.cache_read_tokens = 0
        self.by_model = {}  # model_name -> {"input": N, "output": N, "cache_creation": N, "cache_read": N, "calls": N}

    def record(self, model, input_tokens, output_tokens, cache_creation=0, cache_read=0):
        with self._lock:
            self._record_unsafe(model, input_tokens, output_tokens, cache_creation, cache_read)

    def _record_unsafe(self, model, input_tokens, output_tokens, cache_creation=0, cache_read=0):
        self.calls += 1
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.cache_creation_tokens += cache_creation
        self.cache_read_tokens += cache_read
        if model not in self.by_model:
            self.by_model[model] = {"input": 0, "output": 0, "cache_creation": 0, "cache_read": 0, "calls": 0}
        self.by_model[model]["input"] += input_tokens
        self.by_model[model]["output"] += output_tokens
        self.by_model[model]["cache_creation"] += cache_creation
        self.by_model[model]["cache_read"] += cache_read
        self.by_model[model]["calls"] += 1

    def total_cost_usd(self):
        """计算总成本（参考 CC cost-tracker.ts）"""
        cost = 0.0
        for model, stats in self.by_model.items():
            p = None
            for k, v in MODEL_PRICING.items():
                if k in model:
                    p = v
                    break
            if not p:
                p = MODEL_PRICING.get("claude-sonnet-4-6", {"input": 3.0, "output": 15.0, "cache_read": 0.3, "cache_write": 3.75})
            cost += stats["input"] * p["input"] / 1_000_000
            cost += stats["output"] * p["output"] / 1_000_000
            cost += stats.get("cache_read", 0) * p["cache_read"] / 1_000_000
            cost += stats.get("cache_creation", 0) * p["cache_write"] / 1_000_000
        return cost

    def summary(self):
        """返回格式化的用量摘要字符串"""
        lines = [
            f"API 调用: {self.calls} 次",
            f"Token 总量: input={self.input_tokens:,} output={self.output_tokens:,} total={self.input_tokens + self.output_tokens:,}",
            f"预估成本: ${self.total_cost_usd():.4f}",
        ]
        if self.cache_creation_tokens or self.cache_read_tokens:
            lines.append(f"Prompt Cache: creation={self.cache_creation_tokens:,} read={self.cache_read_tokens:,}")
        if self.by_model:
            lines.append("按模型:")
            for model, stats in sorted(self.by_model.items()):
                short = model.replace("claude-", "")
                cache_info = ""
                if stats['cache_creation'] or stats['cache_read']:
                    cache_info = f" cache_w={stats['cache_creation']:,} cache_r={stats['cache_read']:,}"
                lines.append(f"  {short}: {stats['calls']}次 in={stats['input']:,} out={stats['output']:,}{cache_info}")
        return "\n".join(lines)


# ============================================================
# 单次调用成本 (CC cost-tracker.ts querySource 归因)
# ============================================================


def compute_call_cost_usd(model, usage):
    """从 model 名和 usage dict 计算单次调用成本 USD"""
    pricing = None
    for k, v in MODEL_PRICING.items():
        if k in (model or ""):
            pricing = v
            break
    if not pricing:
        # fallback: sonnet 定价
        pricing = MODEL_PRICING.get("claude-sonnet-4-6", {"input": 3.0, "output": 15.0, "cache_read": 0.3, "cache_write": 3.75})
    cost = 0.0
    cost += (usage.get("input_tokens", 0) or 0) * pricing["input"] / 1_000_000
    cost += (usage.get("output_tokens", 0) or 0) * pricing["output"] / 1_000_000
    cost += (usage.get("cache_read_input_tokens", 0) or 0) * pricing["cache_read"] / 1_000_000
    cost += (usage.get("cache_creation_input_tokens", 0) or 0) * pricing["cache_write"] / 1_000_000
    return round(cost, 6)


# ============================================================
# Token 预估 (CC tokenEstimation.ts:203-224)
# ============================================================


def estimate_tokens(content, bytes_per_token=4):
    """本地粗估 token 数（不调 API），4 bytes/token 是 CC 的默认值"""
    if isinstance(content, str):
        return len(content.encode("utf-8")) // bytes_per_token
    if isinstance(content, list):
        return sum(estimate_tokens(c, bytes_per_token) for c in content)
    if isinstance(content, dict):
        return estimate_tokens(json.dumps(content, ensure_ascii=False), bytes_per_token)
    return 0


def estimate_message_tokens(messages):
    """估算整个 messages 列表的 token（含 4/3 安全系数，CC 惯例）"""
    total = sum(estimate_tokens(m.get("content", "")) for m in messages)
    return int(total * 4 / 3)
