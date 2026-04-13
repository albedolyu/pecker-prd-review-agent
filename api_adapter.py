"""
API 适配层 -- Anthropic 原生客户端
"""

import os


# ============================================================
# Token 用量追踪
# ============================================================

class TokenTracker:
    """累积 token 用量统计"""
    def __init__(self):
        self.calls = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.by_model = {}  # model_name -> {"input": N, "output": N, "calls": N}

    def record(self, model, input_tokens, output_tokens):
        self.calls += 1
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        if model not in self.by_model:
            self.by_model[model] = {"input": 0, "output": 0, "calls": 0}
        self.by_model[model]["input"] += input_tokens
        self.by_model[model]["output"] += output_tokens
        self.by_model[model]["calls"] += 1

    def summary(self):
        """返回格式化的用量摘要字符串"""
        lines = [
            f"API 调用: {self.calls} 次",
            f"Token 总量: input={self.input_tokens:,} output={self.output_tokens:,} total={self.input_tokens + self.output_tokens:,}",
        ]
        if self.by_model:
            lines.append("按模型:")
            for model, stats in sorted(self.by_model.items()):
                # 简化模型名（去掉 claude- 前缀）
                short = model.replace("claude-", "")
                lines.append(f"  {short}: {stats['calls']}次 in={stats['input']:,} out={stats['output']:,}")
        return "\n".join(lines)


# ============================================================
# 统一响应对象
# ============================================================

class UnifiedResponse:
    """统一的 API 响应"""
    def __init__(self, text_blocks, tool_calls, stop_reason, usage, model):
        self.text_blocks = text_blocks
        self.tool_calls = tool_calls
        self.stop_reason = stop_reason
        self.usage = usage
        self.model = model

    @property
    def content(self):
        blocks = []
        for tb in self.text_blocks:
            blocks.append(_DotDict(tb))
        for tc in self.tool_calls:
            blocks.append(_DotDict({"type": "tool_use", **tc}))
        return blocks


class _DotDict(dict):
    """让 dict 支持 .属性 访问"""
    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError:
            raise AttributeError(key)


# ============================================================
# Anthropic 原生客户端
# ============================================================

class AnthropicNativeClient:
    """直接用 Anthropic SDK"""

    def __init__(self, api_key, base_url):
        import anthropic
        # 清掉 Claude Code 注入的旧 auth token
        os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)
        self.client = anthropic.Anthropic(api_key=api_key, base_url=base_url)
        self.tracker = TokenTracker()

    def create(self, model, max_tokens, system, messages, tools=None, tool_choice=None, temperature=0.2):
        kwargs = {
            "model": model,
            "max_tokens": max_tokens,
            "system": system if system else "",
            "messages": messages,
            "temperature": temperature,
        }
        if tools:
            kwargs["tools"] = tools
        if tool_choice:
            kwargs["tool_choice"] = tool_choice

        try:
            response = self.client.messages.create(**kwargs)
        except Exception as e:
            import time
            from logger import get_logger
            log = get_logger("api")
            log.warning(f"API 调用失败，3 秒后重试: {str(e)[:80]}")
            time.sleep(3)
            try:
                response = self.client.messages.create(**kwargs)
            except Exception as e2:
                from exceptions import APIError
                log.error(f"API 重试失败: {e2}")
                raise APIError(f"API 调用两次均失败: {e2}")

        text_blocks = []
        tool_calls = []
        for block in response.content:
            if block.type == "text":
                text_blocks.append({"type": "text", "text": block.text})
            elif block.type == "tool_use":
                tool_calls.append({
                    "id": block.id,
                    "name": block.name,
                    "input": block.input,
                })

        unified = UnifiedResponse(
            text_blocks=text_blocks,
            tool_calls=tool_calls,
            stop_reason=response.stop_reason,
            usage={
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
            },
            model=response.model,
        )
        self.tracker.record(response.model, response.usage.input_tokens, response.usage.output_tokens)
        return unified


# ============================================================
# 工厂函数
# ============================================================

def create_client(api_key=None, base_url=None, **kwargs):
    """创建 API 客户端"""
    api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
    base_url = base_url or os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com")
    return AnthropicNativeClient(api_key, base_url)
