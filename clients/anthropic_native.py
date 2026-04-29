"""Anthropic 原生客户端 (直连 SDK,不通过 Claude CLI).

从 api_adapter.py 拆出 (2026-04-16):
- 分级重试策略 (foreground/worker/advisor/router)
- 连续 529 自动模型降级 (opus → sonnet → haiku)
- context overflow 动态 max_tokens 调整
- 流式调用 + 空闲看门狗
- 预算检查 (MAX_BUDGET_USD env var)

当前生产只走 Claude CLI,这个 client 保留仅为历史兼容 + 后续切换备选。
"""

import os
import random

from clients.shared import (
    FALLBACK_MODELS,
    FLOOR_MAX_TOKENS,
    MAX_CONSECUTIVE_OVERLOADS,
    RETRY_POLICIES,
    UnifiedResponse,
    _gen_req_id,
)
from clients.token_tracker import TokenTracker

# Metrics 埋点 — 失败 silent skip, 不阻 LLM 调用主流程
try:
    from review.metrics_store import record_event as _record_event
except Exception:
    def _record_event(*args, **kwargs):  # noqa: ARG001
        return False


class AnthropicNativeClient:
    """直接用 Anthropic SDK"""

    def __init__(self, api_key=None, base_url=None):
        # factory.get_client 用 cls() 0 参实例化, 这里从 env 兜底读
        # 优先级: 显式传参 > ANTHROPIC_API_KEY > API_KEY (.env 别名)
        import anthropic
        api_key = api_key or os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("API_KEY")
        if not api_key:
            raise RuntimeError(
                "AnthropicNativeClient 未拿到 API key — "
                "在 .env 设 API_KEY=sk-ant-... 或 export ANTHROPIC_API_KEY"
            )
        base_url = base_url or os.environ.get("ANTHROPIC_BASE_URL") or None
        # 清掉 Claude Code 注入的旧 auth token
        os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)
        self.client = anthropic.Anthropic(api_key=api_key, base_url=base_url)
        self.tracker = TokenTracker()

    def create(self, model, max_tokens, system, messages, tools=None, tool_choice=None, temperature=0.2, retry_policy="foreground"):
        """Metrics 包装: 失败时记 llm.api_call status=failure, 成功时由内层 record success."""
        import time as _t
        _start = _t.time()
        try:
            return self._create_inner(model, max_tokens, system, messages,
                                       tools=tools, tool_choice=tool_choice,
                                       temperature=temperature, retry_policy=retry_policy)
        except Exception as _e:
            try:
                _record_event(
                    "llm.api_call",
                    workspace=os.environ.get("WORKSPACE"),
                    duration_ms=int((_t.time() - _start) * 1000),
                    model=model,
                    status="failure",
                    details={
                        "vendor": "anthropic_native",
                        "error": str(_e)[:200],
                        "retry_policy": retry_policy,
                    },
                )
            except Exception:
                pass
            raise

    def _create_inner(self, model, max_tokens, system, messages, tools=None, tool_choice=None, temperature=0.2, retry_policy="foreground"):
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

        # 分级重试 + 模型降级 + context overflow 动态调整
        import time
        import anthropic as _anthropic
        from logger import get_logger
        log = get_logger("api")

        # Metrics 埋点: 记起始时间, 在 return / raise 时统一 record llm.api_call
        _llm_metric_start = time.time()
        _llm_metric_workspace = os.environ.get("WORKSPACE")
        policy = RETRY_POLICIES.get(retry_policy, RETRY_POLICIES["foreground"])
        max_retries = policy["max_retries"]
        consecutive_overloads = 0
        current_model = kwargs["model"]
        response = None

        # retry chain ID (CC requestLogId + retryOfRequestLogID 模式)
        req_id = _gen_req_id()
        tool_hint = (tools[0]["name"] if tools and isinstance(tools[0], dict) else "none")
        log.info(f"[cc_client] req={req_id} tool={tool_hint} model={current_model} policy={retry_policy}")
        original_req_id = req_id  # 链首

        # 预算检查（参考 CC QueryEngine.ts 的 maxBudgetUsd）
        max_budget = float(os.environ.get("MAX_BUDGET_USD", "0"))
        if max_budget > 0 and self.tracker.total_cost_usd() >= max_budget:
            from exceptions import APIError
            raise APIError(f"预算已耗尽: ${self.tracker.total_cost_usd():.2f} >= ${max_budget:.2f}")

        for attempt in range(max_retries + 1):
            try:
                response = self.client.messages.create(**kwargs)
                consecutive_overloads = 0  # 成功则重置
                break
            except _anthropic.RateLimitError as e:
                consecutive_overloads += 1
                # 先检查策略：不允许重试 overload 的直接失败（不走降级）
                if not policy["retry_overload"]:
                    from exceptions import APIError
                    raise APIError(f"API 限流，{retry_policy} 策略不重试: {e}")
                # 模型降级（CC withRetry.ts:326-350）
                if consecutive_overloads >= MAX_CONSECUTIVE_OVERLOADS:
                    fallback = FALLBACK_MODELS.get(current_model)
                    if fallback:
                        log.warning(f"连续 {consecutive_overloads} 次限流，{current_model} → {fallback}")
                        current_model = fallback
                        kwargs["model"] = fallback
                        consecutive_overloads = 0
                        prev_id = req_id
                        req_id = _gen_req_id()
                        log.info(f"[cc_client] req={req_id} retryOf={prev_id} tool={tool_hint} 降级重试")
                        continue  # 用新模型立即重试
                if attempt == max_retries:
                    from exceptions import APIError
                    raise APIError(f"API 限流 {max_retries + 1} 次均失败: {e}")
                prev_id = req_id
                req_id = _gen_req_id()
                delay = 2 ** (attempt + 1) + random.uniform(0, 1)
                log.warning(f"[cc_client] req={req_id} retryOf={prev_id} tool={tool_hint} 限流重试 {delay:.1f}s")
                time.sleep(delay)
            except _anthropic.BadRequestError as e:
                # Context overflow 动态调整（CC withRetry.ts:388-427）
                err_msg = str(e)
                if "context" in err_msg.lower() and ("exceed" in err_msg.lower() or "length" in err_msg.lower()):
                    import re as _re
                    m = _re.search(r'(\d+)\s*\+\s*(\d+)\s*>\s*(\d+)', err_msg)
                    if m:
                        input_t, _, limit = int(m.group(1)), int(m.group(2)), int(m.group(3))
                        new_max = max(FLOOR_MAX_TOKENS, limit - input_t - 1000)
                        log.warning(f"Context overflow, max_tokens {kwargs['max_tokens']} → {new_max}")
                        kwargs["max_tokens"] = new_max
                        continue  # 重试
                from exceptions import APIError
                raise APIError(f"API 请求错误: {e}")
            except Exception as e:
                if attempt == max_retries:
                    from exceptions import APIError
                    log.error(f"[cc_client] req={req_id} tool={tool_hint} {max_retries + 1}次均失败: {e}")
                    raise APIError(f"API 调用 {max_retries + 1} 次均失败: {e}")
                prev_id = req_id
                req_id = _gen_req_id()
                delay = 2 ** (attempt + 1) + random.uniform(0, 1)
                log.warning(f"[cc_client] req={req_id} retryOf={prev_id} tool={tool_hint} 异常重试 {delay:.1f}s: {str(e)[:80]}")
                time.sleep(delay)

        # 成功时记录 chain (如果有过重试,req_id 已变)
        if response is not None and req_id != original_req_id:
            log.info(f"[cc_client] req={req_id} retryOf={original_req_id} tool={tool_hint} 重试成功")

        # 防止 overflow continue 耗尽重试后 response 仍为 None
        if response is None:
            from exceptions import APIError
            raise APIError("API 调用失败：所有重试均未获得有效响应（可能 context overflow 无法恢复）")

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

        # 1c: max_output_recovery — 检测输出截断 (CC max_tokens breaker)
        is_truncated = (response.stop_reason == "max_tokens")
        if is_truncated:
            log.warning(f"[cc_client] req={req_id} stop_reason=max_tokens, 输出被截断 (model={current_model})")

        unified = UnifiedResponse(
            text_blocks=text_blocks,
            tool_calls=tool_calls,
            stop_reason=response.stop_reason,
            usage={
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
                "cache_creation_input_tokens": getattr(response.usage, 'cache_creation_input_tokens', 0) or 0,
                "cache_read_input_tokens": getattr(response.usage, 'cache_read_input_tokens', 0) or 0,
            },
            model=response.model,
            truncated=is_truncated,
        )
        cache_creation = getattr(response.usage, 'cache_creation_input_tokens', 0) or 0
        cache_read = getattr(response.usage, 'cache_read_input_tokens', 0) or 0
        self.tracker.record(response.model, response.usage.input_tokens, response.usage.output_tokens, cache_creation, cache_read)

        # Metrics 埋点: llm.api_call (anthropic_native success)
        try:
            _record_event(
                "llm.api_call",
                workspace=_llm_metric_workspace,
                duration_ms=int((time.time() - _llm_metric_start) * 1000),
                model=response.model,
                status="success",
                details={
                    "vendor": "anthropic_native",
                    "tokens_in": response.usage.input_tokens,
                    "tokens_out": response.usage.output_tokens,
                    "cache_read": cache_read,
                    "retry_policy": retry_policy,
                    "truncated": is_truncated,
                },
            )
        except Exception:
            pass

        return unified

    def create_stream(self, model, max_tokens, system, messages, tools=None, tool_choice=None, temperature=0.2, retry_policy="foreground", idle_timeout=60):
        """
        流式调用（参考 CC claude.ts:1817-2211）
        yield 完整的 content block（text 或 tool_use），不 yield 中间 delta
        idle_timeout: 空闲超时秒数（CC 的 stream watchdog 模式）
        """
        import time
        from logger import get_logger
        log = get_logger("api")

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

        last_event_time = time.time()
        total_input = 0
        total_output = 0

        with self.client.messages.stream(**kwargs) as stream:
            for event in stream:
                now = time.time()
                # 空闲看门狗（CC claude.ts:1868-1927）
                if now - last_event_time > idle_timeout:
                    log.warning(f"Stream 空闲超时 ({idle_timeout}s)，中断")
                    break
                last_event_time = now

                # CC 模式：只在 content_block_stop 时 yield 完整块
                if hasattr(event, 'type'):
                    if event.type == "content_block_stop":
                        # 从 stream 获取最终消息用于 usage 统计
                        pass
                    elif event.type == "message_start" and hasattr(event, 'message'):
                        if hasattr(event.message, 'usage'):
                            total_input = event.message.usage.input_tokens

            # 获取最终响应
            final = stream.get_final_message()

        # 统计
        total_output = final.usage.output_tokens
        total_input = final.usage.input_tokens
        cache_creation = getattr(final.usage, 'cache_creation_input_tokens', 0) or 0
        cache_read = getattr(final.usage, 'cache_read_input_tokens', 0) or 0
        self.tracker.record(final.model, total_input, total_output, cache_creation, cache_read)

        # 转为 UnifiedResponse
        text_blocks = []
        tool_calls = []
        for block in final.content:
            if block.type == "text":
                text_blocks.append({"type": "text", "text": block.text})
            elif block.type == "tool_use":
                tool_calls.append({"id": block.id, "name": block.name, "input": block.input})

        return UnifiedResponse(
            text_blocks=text_blocks,
            tool_calls=tool_calls,
            stop_reason=final.stop_reason,
            usage={
                "input_tokens": total_input,
                "output_tokens": total_output,
                "cache_creation_input_tokens": cache_creation,
                "cache_read_input_tokens": cache_read,
            },
            model=final.model,
        )
