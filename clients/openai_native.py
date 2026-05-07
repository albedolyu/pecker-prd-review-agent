"""OpenAI API client for GPT-primary team deployments.

This client uses ``OPENAI_API_KEY`` plus optional ``OPENAI_BASE_URL`` so the
team version is not tied to a single local OAuth/OAT session.  The default wire
can be switched with ``OPENAI_WIRE_API=responses|chat_completions``.
"""
from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, List, Optional

from clients.shared import RETRY_POLICIES, UnifiedResponse, _gen_req_id
from clients.token_tracker import TokenTracker

try:
    from review.metrics_store import record_event as _record_event
except Exception:
    def _record_event(*args, **kwargs):  # noqa: ARG001
        return False


class OpenAINativeClient:
    """OpenAI SDK client with the same create() contract as other Pecker clients."""

    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None):
        api_key = api_key or os.environ.get("OPENAI_API_KEY") or os.environ.get("API_KEY", "")
        if not api_key:
            raise RuntimeError("OpenAINativeClient: OPENAI_API_KEY/API_KEY 未配置")
        base_url = base_url or os.environ.get("OPENAI_BASE_URL") or None
        self.wire_api = (
            os.environ.get("OPENAI_WIRE_API")
            or os.environ.get("PECKER_OPENAI_WIRE_API")
            or "chat_completions"
        ).strip().lower()
        self.reasoning_effort = (
            os.environ.get("OPENAI_REASONING_EFFORT")
            or os.environ.get("PECKER_MODEL_REASONING_EFFORT")
            or ""
        ).strip()
        self.disable_response_storage = self._env_bool("OPENAI_DISABLE_RESPONSE_STORAGE") or self._env_bool(
            "PECKER_DISABLE_RESPONSE_STORAGE"
        )
        self.client = self._build_client(api_key, base_url)
        self.tracker = TokenTracker()

    def _build_client(self, api_key: str, base_url: Optional[str]):
        from openai import OpenAI

        kwargs: Dict[str, Any] = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        return OpenAI(**kwargs)

    @staticmethod
    def _flatten_content(content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: List[str] = []
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") == "text":
                        parts.append(str(block.get("text", "")))
                    elif block.get("type") == "tool_result":
                        parts.append(str(block.get("content", "")))
                else:
                    parts.append(str(block))
            return "\n".join(p for p in parts if p)
        return str(content or "")

    @classmethod
    def _messages(cls, system: Any, messages: List[Dict[str, Any]]) -> List[Dict[str, str]]:
        out: List[Dict[str, str]] = []
        system_text = cls._flatten_content(system)
        if system_text:
            out.append({"role": "system", "content": system_text})
        for msg in messages:
            role = msg.get("role", "user")
            if role not in {"system", "user", "assistant", "developer"}:
                role = "user"
            out.append({"role": role, "content": cls._flatten_content(msg.get("content", ""))})
        return out

    @staticmethod
    def _tool_choice(tool_choice: Any, selected_tool: Optional[Dict[str, Any]]) -> Any:
        if not selected_tool:
            return None
        if isinstance(tool_choice, dict) and tool_choice.get("type") == "tool":
            name = tool_choice.get("name") or selected_tool["name"]
        else:
            name = selected_tool["name"]
        return {"type": "function", "function": {"name": name}}

    @staticmethod
    def _tools(tools: Optional[List[Dict[str, Any]]]) -> Optional[List[Dict[str, Any]]]:
        if not tools:
            return None
        converted = []
        for tool in tools:
            converted.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool["name"],
                        "description": tool.get("description", ""),
                        "parameters": tool.get("input_schema", {"type": "object", "properties": {}}),
                    },
                }
            )
        return converted

    @staticmethod
    def _env_bool(name: str) -> bool:
        return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}

    @classmethod
    def _response_input(cls, system: Any, messages: List[Dict[str, Any]]) -> str:
        parts: List[str] = []
        system_text = cls._flatten_content(system)
        if system_text:
            parts.append(f"[SYSTEM]\n{system_text}")
        for msg in messages:
            role = msg.get("role", "user")
            if role not in {"user", "assistant", "developer"}:
                role = "user"
            parts.append(f"[{role.upper()}]\n{cls._flatten_content(msg.get('content', ''))}")
        return "\n\n".join(parts)

    @staticmethod
    def _response_tools(tools: Optional[List[Dict[str, Any]]]) -> Optional[List[Dict[str, Any]]]:
        if not tools:
            return None
        converted = []
        for tool in tools:
            converted.append(
                {
                    "type": "function",
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    "parameters": tool.get("input_schema", {"type": "object", "properties": {}}),
                }
            )
        return converted

    @staticmethod
    def _response_tool_choice(tool_choice: Any, selected_tool: Optional[Dict[str, Any]]) -> Any:
        if selected_tool:
            return {"type": "function", "name": selected_tool["name"]}
        if tool_choice in ("required", "auto", "none"):
            return tool_choice
        return None

    @staticmethod
    def _selected_tool(tools: Optional[List[Dict[str, Any]]], tool_choice: Any) -> Optional[Dict[str, Any]]:
        if not tools or not tool_choice:
            return None
        if isinstance(tool_choice, dict) and tool_choice.get("type") == "tool":
            name = tool_choice.get("name")
            return next((t for t in tools if t.get("name") == name), tools[0])
        if tool_choice in ("required", "any") or (
            isinstance(tool_choice, dict) and tool_choice.get("type") in ("any", "required")
        ):
            return tools[0]
        return None

    def create(
        self,
        model,
        max_tokens,
        system,
        messages,
        tools=None,
        tool_choice=None,
        temperature=0.2,
        retry_policy="foreground",
    ):
        start = time.time()
        try:
            return self._create_inner(
                model,
                max_tokens,
                system,
                messages,
                tools=tools,
                tool_choice=tool_choice,
                temperature=temperature,
                retry_policy=retry_policy,
                metric_start=start,
            )
        except Exception as exc:
            _record_event(
                "llm.api_call",
                workspace=os.environ.get("WORKSPACE"),
                duration_ms=int((time.time() - start) * 1000),
                model=model,
                status="failure",
                details={"vendor": "openai_native", "error": str(exc)[:200]},
            )
            raise

    def _create_inner(
        self,
        model,
        max_tokens,
        system,
        messages,
        *,
        tools=None,
        tool_choice=None,
        temperature=0.2,
        retry_policy="foreground",
        metric_start=None,
    ):
        policy = RETRY_POLICIES.get(retry_policy, RETRY_POLICIES["foreground"])
        max_retries = policy["max_retries"]
        selected_tool = self._selected_tool(tools, tool_choice)
        req_id = _gen_req_id()
        last_exc: Optional[Exception] = None

        if self.wire_api == "responses":
            params: Dict[str, Any] = {
                "model": model,
                "input": self._response_input(system, messages),
                "max_output_tokens": max_tokens,
            }
            if self.disable_response_storage:
                params["store"] = False
            if self.reasoning_effort:
                params["reasoning"] = {"effort": self.reasoning_effort}
            if temperature is not None and not self.reasoning_effort:
                params["temperature"] = temperature
            converted_tools = self._response_tools(tools)
            if converted_tools:
                params["tools"] = converted_tools
            converted_choice = self._response_tool_choice(tool_choice, selected_tool)
            if converted_choice:
                params["tool_choice"] = converted_choice

            for attempt in range(max_retries + 1):
                try:
                    response = self.client.responses.create(**params)
                    break
                except Exception as exc:  # noqa: BLE001
                    last_exc = exc
                    if attempt >= max_retries:
                        raise
                    time.sleep(2 ** (attempt + 1))
            else:
                raise last_exc or RuntimeError("OpenAI request failed")

            unified = self._to_unified_response_from_responses(
                response, model, req_id, selected_tool
            )
        else:
            params = {
                "model": model,
                "messages": self._messages(system, messages),
                "max_completion_tokens": max_tokens,
            }
            if temperature is not None:
                params["temperature"] = temperature
            converted_tools = self._tools(tools)
            if converted_tools:
                params["tools"] = converted_tools
            converted_choice = self._tool_choice(tool_choice, selected_tool)
            if converted_choice:
                params["tool_choice"] = converted_choice

            for attempt in range(max_retries + 1):
                try:
                    response = self.client.chat.completions.create(**params)
                    break
                except TypeError:
                    # Some OpenAI-compatible gateways still expect max_tokens.
                    params["max_tokens"] = params.pop("max_completion_tokens")
                    response = self.client.chat.completions.create(**params)
                    break
                except Exception as exc:  # noqa: BLE001
                    last_exc = exc
                    if attempt >= max_retries:
                        raise
                    time.sleep(2 ** (attempt + 1))
            else:
                raise last_exc or RuntimeError("OpenAI request failed")

            unified = self._to_unified_response(response, model, req_id, selected_tool)
        usage = unified.usage
        self.tracker.record(
            unified.model,
            usage.get("input_tokens", 0),
            usage.get("output_tokens", 0),
            usage.get("cache_creation_input_tokens", 0),
            usage.get("cache_read_input_tokens", 0),
        )
        _record_event(
            "llm.api_call",
            workspace=os.environ.get("WORKSPACE"),
            duration_ms=int((time.time() - metric_start) * 1000) if metric_start else 0,
            model=unified.model,
            status="success",
            details={
                "vendor": "openai_native",
                "tokens_in": usage.get("input_tokens", 0),
                "tokens_out": usage.get("output_tokens", 0),
                "retry_policy": retry_policy,
            },
        )
        return unified

    @staticmethod
    def _usage(response: Any) -> Dict[str, int]:
        usage = getattr(response, "usage", None)
        if not usage:
            return {
                "input_tokens": 0,
                "output_tokens": 0,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 0,
            }
        return {
            "input_tokens": int(getattr(usage, "prompt_tokens", 0) or 0),
            "output_tokens": int(getattr(usage, "completion_tokens", 0) or 0),
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
        }

    @staticmethod
    def _responses_usage(response: Any) -> Dict[str, int]:
        usage = getattr(response, "usage", None)
        if not usage:
            return {
                "input_tokens": 0,
                "output_tokens": 0,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 0,
            }
        return {
            "input_tokens": int(getattr(usage, "input_tokens", 0) or 0),
            "output_tokens": int(getattr(usage, "output_tokens", 0) or 0),
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
        }

    @staticmethod
    def _content_text(content: Any) -> str:
        if isinstance(content, str):
            return content
        text_parts: List[str] = []
        for block in content or []:
            if isinstance(block, dict):
                if block.get("type") in {"output_text", "text"}:
                    text_parts.append(str(block.get("text", "")))
            else:
                btype = getattr(block, "type", "")
                if btype in {"output_text", "text"}:
                    text_parts.append(str(getattr(block, "text", "")))
        return "\n".join(p for p in text_parts if p)

    @staticmethod
    def _to_unified_response_from_responses(
        response: Any,
        model: str,
        req_id: str,
        selected_tool: Optional[Dict[str, Any]],
    ) -> UnifiedResponse:
        text_blocks = []
        tool_calls = []

        for item in getattr(response, "output", None) or []:
            item_type = item.get("type") if isinstance(item, dict) else getattr(item, "type", "")
            if item_type == "function_call":
                name = item.get("name") if isinstance(item, dict) else getattr(item, "name", "")
                args_raw = item.get("arguments") if isinstance(item, dict) else getattr(item, "arguments", "")
                try:
                    args = json.loads(args_raw or "{}")
                except json.JSONDecodeError:
                    args = {}
                call_id = (
                    item.get("call_id") or item.get("id")
                    if isinstance(item, dict)
                    else getattr(item, "call_id", "") or getattr(item, "id", "")
                )
                tool_calls.append({"id": call_id or req_id, "name": name, "input": args})
            elif item_type == "message":
                content = item.get("content") if isinstance(item, dict) else getattr(item, "content", [])
                text = OpenAINativeClient._content_text(content)
                if text:
                    text_blocks.append({"type": "text", "text": text})

        output_text = getattr(response, "output_text", "") or ""
        if output_text and not text_blocks and not tool_calls:
            if selected_tool:
                try:
                    args = json.loads(output_text)
                    tool_calls.append({"id": req_id, "name": selected_tool["name"], "input": args})
                except json.JSONDecodeError:
                    text_blocks.append({"type": "text", "text": output_text})
            else:
                text_blocks.append({"type": "text", "text": output_text})

        status = getattr(response, "status", "")
        return UnifiedResponse(
            text_blocks=text_blocks,
            tool_calls=tool_calls,
            stop_reason="tool_use" if tool_calls else "end_turn",
            usage=OpenAINativeClient._responses_usage(response),
            model=getattr(response, "model", None) or model,
            truncated=status == "incomplete",
        )

    @staticmethod
    def _to_unified_response(
        response: Any,
        model: str,
        req_id: str,
        selected_tool: Optional[Dict[str, Any]],
    ) -> UnifiedResponse:
        choice = response.choices[0]
        message = choice.message
        text_blocks = []
        tool_calls = []

        for call in getattr(message, "tool_calls", None) or []:
            fn = call.function
            try:
                args = json.loads(fn.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            tool_calls.append({"id": getattr(call, "id", req_id), "name": fn.name, "input": args})

        content = getattr(message, "content", None)
        if content:
            if selected_tool and not tool_calls:
                try:
                    args = json.loads(content)
                    tool_calls.append({"id": req_id, "name": selected_tool["name"], "input": args})
                except json.JSONDecodeError:
                    text_blocks.append({"type": "text", "text": content})
            else:
                text_blocks.append({"type": "text", "text": content})

        return UnifiedResponse(
            text_blocks=text_blocks,
            tool_calls=tool_calls,
            stop_reason="tool_use" if tool_calls else "end_turn",
            usage=OpenAINativeClient._usage(response),
            model=model,
            truncated=getattr(choice, "finish_reason", "") == "length",
        )
