"""
API 适配层 -- Anthropic 原生客户端
"""

import os


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

    def create(self, model, max_tokens, system, messages, tools=None, tool_choice=None):
        kwargs = {
            "model": model,
            "max_tokens": max_tokens,
            "system": system if system else "",
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = tools
        if tool_choice:
            kwargs["tool_choice"] = tool_choice

        try:
            response = self.client.messages.create(**kwargs)
        except Exception as e:
            import time
            print(f"\n  [retry] API 调用失败，3 秒后重试: {str(e)[:80]}", flush=True)
            time.sleep(3)
            try:
                response = self.client.messages.create(**kwargs)
            except Exception as e2:
                return UnifiedResponse(
                    text_blocks=[{"type": "text", "text": f"[API error] {e2}"}],
                    tool_calls=[], stop_reason="end_turn",
                    usage={"input_tokens": 0, "output_tokens": 0}, model=model,
                )

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

        return UnifiedResponse(
            text_blocks=text_blocks,
            tool_calls=tool_calls,
            stop_reason=response.stop_reason,
            usage={
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
            },
            model=response.model,
        )


# ============================================================
# 工厂函数
# ============================================================

def create_client(api_key=None, base_url=None, **kwargs):
    """创建 API 客户端"""
    api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
    base_url = base_url or os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com")
    return AnthropicNativeClient(api_key, base_url)
