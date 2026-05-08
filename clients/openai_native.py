"""OpenAI API client for GPT-primary team deployments.

This client uses ``OPENAI_API_KEY`` plus optional ``OPENAI_BASE_URL`` so the
team version is not tied to a single local OAuth/OAT session.  The default wire
can be switched with ``OPENAI_WIRE_API=responses|chat_completions``.
"""
from __future__ import annotations

import json
import os
import re
import threading
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
        base_url = base_url or os.environ.get("OPENAI_BASE_URL") or None
        self._base_url = base_url
        self._api_keys = self._load_api_keys(api_key)
        if not self._api_keys:
            raise RuntimeError("OpenAINativeClient: OPENAI_API_KEYS/OPENAI_API_KEY/API_KEY 未配置")
        self._client_lock = threading.Lock()
        self._client_index = -1
        self._clients: Dict[str, Any] = {}
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
        first_label, first_key = self._api_keys[0]
        self.client = self._client_for(first_label, first_key)
        self.tracker = TokenTracker()

    def _build_client(self, api_key: str, base_url: Optional[str]):
        from openai import OpenAI

        kwargs: Dict[str, Any] = {
            "api_key": api_key,
            "timeout": self._env_float("OPENAI_REQUEST_TIMEOUT", 360.0),
            "max_retries": 0,
        }
        if base_url:
            kwargs["base_url"] = base_url
        return OpenAI(**kwargs)

    @classmethod
    def _load_api_keys(cls, explicit_key: Optional[str]) -> List[tuple[str, str]]:
        candidates: List[tuple[str, str]] = []
        if explicit_key:
            candidates.append(("key_1", explicit_key))
        else:
            for name in ("OPENAI_API_KEYS", "PECKER_OPENAI_API_KEYS"):
                candidates.extend(cls._parse_key_entries(os.environ.get(name, "")))
            for prefix in ("OPENAI_API_KEY", "PECKER_OPENAI_API_KEY"):
                for i in range(1, 11):
                    value = os.environ.get(f"{prefix}_{i}", "").strip()
                    if value:
                        candidates.append((f"key_{i}", value))
            if not candidates:
                for name in ("OPENAI_API_KEY", "API_KEY"):
                    value = os.environ.get(name, "").strip()
                    if value:
                        candidates.append(("key_1", value))

        keys: List[tuple[str, str]] = []
        seen: set[str] = set()
        for raw_label, raw_key in candidates:
            key = (raw_key or "").strip()
            if not key or key in seen:
                continue
            label = (raw_label or "").strip() or f"key_{len(keys) + 1}"
            if "sk-" in label.lower():
                label = f"key_{len(keys) + 1}"
            existing_labels = {existing_label for existing_label, _ in keys}
            if label in existing_labels:
                label = f"key_{len(keys) + 1}"
            keys.append((label, key))
            seen.add(key)
        return keys

    @staticmethod
    def _parse_key_entries(raw: str) -> List[tuple[str, str]]:
        entries: List[tuple[str, str]] = []
        for entry in re.split(r"[\n,;]+", raw or ""):
            piece = entry.strip()
            if not piece:
                continue
            label = ""
            key = piece
            if "=" in piece:
                label, key = piece.split("=", 1)
            elif "：" in piece and not piece.lower().startswith("sk-"):
                label, key = piece.split("：", 1)
            elif ":" in piece and not piece.lower().startswith("sk-"):
                label, key = piece.split(":", 1)
            entries.append((label.strip(), key.strip()))
        return entries

    def _client_for(self, label: str, api_key: str):
        with self._client_lock:
            client = self._clients.get(label)
            if client is None:
                client = self._build_client(api_key, self._base_url)
                self._clients[label] = client
            return client

    def _select_client(self):
        with self._client_lock:
            self._client_index = (self._client_index + 1) % len(self._api_keys)
            label, api_key = self._api_keys[self._client_index]
        return self._client_for(label, api_key), label

    def _rotate_client(self, current_label: str):
        if len(self._api_keys) <= 1:
            label, api_key = self._api_keys[0]
            return self._client_for(label, api_key), label
        with self._client_lock:
            current_index = next(
                (i for i, (label, _key) in enumerate(self._api_keys) if label == current_label),
                self._client_index,
            )
            self._client_index = (current_index + 1) % len(self._api_keys)
            label, api_key = self._api_keys[self._client_index]
        return self._client_for(label, api_key), label

    @staticmethod
    def _is_transient_error(exc: Exception) -> bool:
        transient_codes = {408, 409, 425, 429, 500, 502, 503, 504, 520, 522, 524}
        for attr in ("status_code", "status", "code"):
            value = getattr(exc, attr, None)
            try:
                if int(value) in transient_codes:
                    return True
            except (TypeError, ValueError):
                pass
        response = getattr(exc, "response", None)
        value = getattr(response, "status_code", None) if response is not None else None
        try:
            if int(value) in transient_codes:
                return True
        except (TypeError, ValueError):
            pass
        message = str(exc).lower()
        return any(
            marker in message
            for marker in (
                "524",
                "cloudflare",
                "timeout",
                "timed out",
                "rate limit",
                "temporarily unavailable",
                "connection reset",
            )
        )

    @staticmethod
    def _sleep_before_retry(attempt: int) -> None:
        time.sleep(min(8, 2 ** (attempt + 1)))

    @staticmethod
    def _meta_usage_extra(response: UnifiedResponse) -> Dict[str, Any]:
        value = getattr(response, "_pecker_usage_extra", None)
        return dict(value) if isinstance(value, dict) else {}

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

    @staticmethod
    def _env_float(name: str, default: float) -> float:
        try:
            return float(os.environ.get(name, str(default)) or default)
        except ValueError:
            return default

    @staticmethod
    def _env_int(name: str, default: int) -> int:
        try:
            return int(os.environ.get(name, str(default)) or default)
        except ValueError:
            return default

    def _max_retries_for_policy(self, retry_policy: str) -> int:
        policy = RETRY_POLICIES.get(retry_policy, RETRY_POLICIES["foreground"])
        default = int(policy["max_retries"])
        suffix = retry_policy.upper()
        for name in (
            f"OPENAI_{suffix}_MAX_RETRIES",
            f"PECKER_OPENAI_{suffix}_MAX_RETRIES",
            "OPENAI_MAX_RETRIES",
        ):
            if os.environ.get(name, "").strip():
                return max(0, self._env_int(name, default))
        return default

    def _reasoning_effort_for_policy(self, retry_policy: str) -> str:
        suffix = retry_policy.upper()
        for name in (
            f"OPENAI_{suffix}_REASONING_EFFORT",
            f"PECKER_OPENAI_{suffix}_REASONING_EFFORT",
            f"PECKER_{suffix}_REASONING_EFFORT",
        ):
            value = os.environ.get(name, "").strip()
            if value:
                return value
        return self.reasoning_effort

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
        max_retries = self._max_retries_for_policy(retry_policy)
        reasoning_effort = self._reasoning_effort_for_policy(retry_policy)
        selected_tool = self._selected_tool(tools, tool_choice)
        req_id = _gen_req_id()
        last_exc: Optional[Exception] = None
        client, key_label = self._select_client()
        attempts_used = 0

        if self.wire_api == "responses":
            params: Dict[str, Any] = {
                "model": model,
                "input": self._response_input(system, messages),
                "max_output_tokens": max_tokens,
            }
            if self.disable_response_storage:
                params["store"] = False
            if reasoning_effort:
                params["reasoning"] = {"effort": reasoning_effort}
            if temperature is not None and not reasoning_effort:
                params["temperature"] = temperature
            converted_tools = self._response_tools(tools)
            if converted_tools:
                params["tools"] = converted_tools
            converted_choice = self._response_tool_choice(tool_choice, selected_tool)
            if converted_choice:
                params["tool_choice"] = converted_choice

            for attempt in range(max_retries + 1):
                attempts_used = attempt + 1
                try:
                    response = client.responses.create(**params)
                    break
                except Exception as exc:  # noqa: BLE001
                    last_exc = exc
                    if attempt >= max_retries or not self._is_transient_error(exc):
                        raise
                    client, key_label = self._rotate_client(key_label)
                    self._sleep_before_retry(attempt)
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
                attempts_used = attempt + 1
                try:
                    response = client.chat.completions.create(**params)
                    break
                except TypeError:
                    # Some OpenAI-compatible gateways still expect max_tokens.
                    params["max_tokens"] = params.pop("max_completion_tokens")
                    response = client.chat.completions.create(**params)
                    break
                except Exception as exc:  # noqa: BLE001
                    last_exc = exc
                    if attempt >= max_retries or not self._is_transient_error(exc):
                        raise
                    client, key_label = self._rotate_client(key_label)
                    self._sleep_before_retry(attempt)
            else:
                raise last_exc or RuntimeError("OpenAI request failed")

            unified = self._to_unified_response(response, model, req_id, selected_tool)
        usage_extra = {
            "attempts": attempts_used,
            "key_id": key_label,
            "key_pool_size": len(self._api_keys),
            "reasoning_effort": reasoning_effort,
        }
        try:
            setattr(unified, "_pecker_usage_extra", usage_extra)
        except Exception:
            pass
        usage = unified.usage
        usage.update(usage_extra)
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
                "max_retries": max_retries,
                **usage_extra,
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
