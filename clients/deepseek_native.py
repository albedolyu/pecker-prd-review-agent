"""DeepSeek 原生客户端 (OpenAI 兼容 API, 通过 https://api.deepseek.com).

设计目标:
- 与 AnthropicNativeClient.create() 签名 + UnifiedResponse 输出 1:1 兼容
- 自动把 Anthropic 风格 tool schema (input_schema) 转成 OpenAI function calling
- 自动把 OpenAI tool_calls 反向转成 Anthropic 风格 tool_use blocks
- tool_choice 兼容映射: Anthropic {"type":"any"} → OpenAI "required"
                       Anthropic {"type":"tool","name":X} → OpenAI {function: {name: X}}

加入 DeepSeek 是为了让 worker 维度走独立 API key,绕开 OAuth burst (单 OAT 多进程争抢
导致 401 风暴, 见 STATUS.md). 苍鹰仍走 Anthropic Opus 保深度推理。
"""

import json
import os
import random
import time

from clients.shared import RETRY_POLICIES, UnifiedResponse, _gen_req_id
from clients.token_tracker import TokenTracker

# Metrics 埋点 — 失败 silent skip, 不阻 LLM 调用主流程
try:
    from review.metrics_store import record_event as _record_event
except Exception:
    def _record_event(*args, **kwargs):  # noqa: ARG001
        return False


class DeepSeekNativeClient:
    """通过 OpenAI SDK 调 DeepSeek API"""

    def __init__(self, api_key=None, base_url=None):
        from openai import OpenAI
        api_key = api_key or os.environ.get("DEEPSEEK_API_KEY")
        if not api_key:
            raise RuntimeError(
                "DeepSeekNativeClient 未拿到 API key — 在 .env 设 DEEPSEEK_API_KEY=sk-..."
            )
        base_url = base_url or os.environ.get("DEEPSEEK_BASE_URL") or "https://api.deepseek.com"
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.tracker = TokenTracker()

    # ---------- schema 转换 ----------

    @staticmethod
    def _to_openai_tools(tools):
        """Anthropic tool schema → OpenAI function calling schema."""
        if not tools:
            return None
        result = []
        for t in tools:
            result.append({
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": t.get("input_schema", {"type": "object", "properties": {}}),
                },
            })
        return result

    @staticmethod
    def _to_openai_tool_choice(tool_choice):
        """Anthropic tool_choice → OpenAI tool_choice."""
        if tool_choice is None:
            return None
        if isinstance(tool_choice, str):
            return tool_choice
        ttype = tool_choice.get("type")
        if ttype in ("any", "required"):
            return "required"
        if ttype == "auto":
            return "auto"
        if ttype == "tool" and tool_choice.get("name"):
            return {"type": "function", "function": {"name": tool_choice["name"]}}
        return None

    @staticmethod
    def _to_openai_messages(system, messages):
        """Anthropic 风格 messages (+ system 字符串/数组) → OpenAI messages."""
        out = []
        if system:
            if isinstance(system, list):
                sys_text = "\n\n".join(
                    s.get("text", "") if isinstance(s, dict) else str(s) for s in system
                )
            else:
                sys_text = str(system)
            if sys_text.strip():
                out.append({"role": "system", "content": sys_text})

        for m in messages:
            role = m.get("role", "user")
            content = m.get("content", "")
            if isinstance(content, list):
                # content blocks: [{type:text,text:...}, {type:tool_result,...}, ...] 简化:只取 text
                text_parts = []
                for blk in content:
                    if isinstance(blk, dict):
                        if blk.get("type") == "text":
                            text_parts.append(blk.get("text", ""))
                        elif blk.get("type") == "tool_result":
                            tr_content = blk.get("content", "")
                            if isinstance(tr_content, list):
                                tr_content = "\n".join(
                                    b.get("text", "") for b in tr_content if isinstance(b, dict)
                                )
                            text_parts.append(f"[tool_result] {tr_content}")
                content = "\n".join(text_parts)
            out.append({"role": role, "content": content})
        return out

    # ---------- 主入口 ----------

    def create(self, model, max_tokens, system, messages, tools=None, tool_choice=None,
               temperature=0.2, retry_policy="foreground"):
        """Metrics 包装: 失败时记 llm.api_call status=failure."""
        _start = time.time()
        try:
            return self._create_inner(model, max_tokens, system, messages,
                                       tools=tools, tool_choice=tool_choice,
                                       temperature=temperature, retry_policy=retry_policy,
                                       _metric_start=_start)
        except Exception as _e:
            try:
                _record_event(
                    "llm.api_call",
                    workspace=os.environ.get("WORKSPACE"),
                    duration_ms=int((time.time() - _start) * 1000),
                    model=model,
                    status="failure",
                    details={
                        "vendor": "deepseek_native",
                        "error": str(_e)[:200],
                        "retry_policy": retry_policy,
                    },
                )
            except Exception:
                pass
            raise

    def _create_inner(self, model, max_tokens, system, messages, tools=None, tool_choice=None,
                      temperature=0.2, retry_policy="foreground", _metric_start=None):
        from logger import get_logger
        log = get_logger("api")

        policy = RETRY_POLICIES.get(retry_policy, RETRY_POLICIES["foreground"])
        max_retries = policy["max_retries"]

        kwargs = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": self._to_openai_messages(system, messages),
            "temperature": temperature,
        }
        oai_tools = self._to_openai_tools(tools)
        if oai_tools:
            kwargs["tools"] = oai_tools
        oai_tc = self._to_openai_tool_choice(tool_choice)
        if oai_tc is not None:
            kwargs["tool_choice"] = oai_tc

        req_id = _gen_req_id()
        tool_hint = (tools[0]["name"] if tools and isinstance(tools[0], dict) else "none")
        log.info(f"[ds_client] req={req_id} tool={tool_hint} model={model} policy={retry_policy}")

        max_budget = float(os.environ.get("MAX_BUDGET_USD", "0"))
        if max_budget > 0 and self.tracker.total_cost_usd() >= max_budget:
            from exceptions import APIError
            raise APIError(f"预算已耗尽: ${self.tracker.total_cost_usd():.2f} >= ${max_budget:.2f}")

        response = None
        last_err = None
        for attempt in range(max_retries + 1):
            try:
                response = self.client.chat.completions.create(**kwargs)
                break
            except Exception as e:
                last_err = e
                if attempt == max_retries:
                    from exceptions import APIError
                    log.error(f"[ds_client] req={req_id} {max_retries + 1} 次均失败: {e}")
                    raise APIError(f"DeepSeek API 调用 {max_retries + 1} 次均失败: {e}")
                prev_id = req_id
                req_id = _gen_req_id()
                delay = 2 ** (attempt + 1) + random.uniform(0, 1)
                log.warning(f"[ds_client] req={req_id} retryOf={prev_id} 异常重试 {delay:.1f}s: {str(e)[:80]}")
                time.sleep(delay)

        if response is None:
            from exceptions import APIError
            raise APIError(f"DeepSeek 所有重试均失败: {last_err}")

        choice = response.choices[0]
        msg = choice.message

        text_blocks = []
        if msg.content:
            text_blocks.append({"type": "text", "text": msg.content})

        tool_calls = []
        if msg.tool_calls:
            for tc in msg.tool_calls:
                try:
                    parsed_input = json.loads(tc.function.arguments)
                except (json.JSONDecodeError, TypeError):
                    parsed_input = {"_raw": tc.function.arguments}
                tool_calls.append({
                    "id": tc.id,
                    "name": tc.function.name,
                    "input": parsed_input,
                })

        # OpenAI finish_reason → Anthropic stop_reason
        finish = choice.finish_reason
        stop_reason_map = {
            "stop": "end_turn",
            "length": "max_tokens",
            "tool_calls": "tool_use",
            "function_call": "tool_use",
            "content_filter": "stop_sequence",
        }
        stop_reason = stop_reason_map.get(finish, finish)
        is_truncated = (finish == "length")

        usage = response.usage
        in_tokens = getattr(usage, "prompt_tokens", 0)
        out_tokens = getattr(usage, "completion_tokens", 0)
        # DeepSeek 自带 prompt cache,字段名 prompt_cache_hit_tokens / prompt_cache_miss_tokens
        cache_read = getattr(usage, "prompt_cache_hit_tokens", 0) or 0
        cache_creation = 0  # DeepSeek 自动管理,不区分写入

        unified = UnifiedResponse(
            text_blocks=text_blocks,
            tool_calls=tool_calls,
            stop_reason=stop_reason,
            usage={
                "input_tokens": in_tokens,
                "output_tokens": out_tokens,
                "cache_creation_input_tokens": cache_creation,
                "cache_read_input_tokens": cache_read,
            },
            model=response.model,
            truncated=is_truncated,
        )
        self.tracker.record(response.model, in_tokens, out_tokens, cache_creation, cache_read)
        if is_truncated:
            log.warning(f"[ds_client] req={req_id} stop_reason=length, 输出被截断")

        # Metrics 埋点: llm.api_call (deepseek_native success)
        try:
            _record_event(
                "llm.api_call",
                workspace=os.environ.get("WORKSPACE"),
                duration_ms=int((time.time() - _metric_start) * 1000) if _metric_start else 0,
                model=response.model,
                status="success",
                details={
                    "vendor": "deepseek_native",
                    "tokens_in": in_tokens,
                    "tokens_out": out_tokens,
                    "cache_read": cache_read,
                    "retry_policy": retry_policy,
                    "truncated": is_truncated,
                },
            )
        except Exception:
            pass

        return unified
