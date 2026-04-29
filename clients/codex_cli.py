"""Codex CLI 客户端 (subprocess 调 `codex exec`, 复用本地 ChatGPT OAuth 登录态).

设计目标:
- 与 ClaudeCodeCLIClient.create() 签名 + UnifiedResponse 输出 1:1 兼容
- tools + tool_choice 强制结构化输出 → 转译为 codex --output-schema (JSON Schema 严格模式)
- 单调用流: prompt 走 argv, 输出走 -o file, usage 从 stdout JSONL 解析

注意:
- Codex CLI 系统 prompt 自带 ~30K token, 单调用 input cost 偏重 (vs DeepSeek 直连 ~5K)
- ChatGPT Pro OAuth 单 OAT, 多 codex 子进程并发可能撞 OAuth race (与 claude CLI 同病同治)
"""

import json
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path

from clients.shared import RETRY_POLICIES, UnifiedResponse, _gen_req_id
from clients.token_tracker import TokenTracker

# Metrics 埋点 — 失败 silent skip, 不阻 LLM 调用主流程
try:
    from review.metrics_store import record_event as _record_event
except Exception:
    def _record_event(*args, **kwargs):  # noqa: ARG001
        return False


def _find_codex_entry():
    """找 codex.js 入口 + node bin, 绕过 Windows .cmd 包装."""
    candidates_js = [
        os.path.expandvars(r"%APPDATA%\npm\node_modules\@openai\codex\bin\codex.js"),
        "/usr/local/lib/node_modules/@openai/codex/bin/codex.js",
        "/usr/lib/node_modules/@openai/codex/bin/codex.js",
    ]
    for c in candidates_js:
        if c and os.path.isfile(c):
            return "node", c
    return None, None


class CodexCLIClient:
    """通过 subprocess 调 codex exec, 复用 ChatGPT OAuth, 零 API key."""

    # 继承 worker 拒答出口的 null_finding_reason 风险: codex 严格 schema 不允许少字段
    _SCHEMA_REQUIRED_TIMEOUT_S = 600

    def __init__(self, api_key=None, base_url=None):
        # api_key/base_url 仅为兼容签名, codex CLI 不读
        self.node_bin, self.codex_js = _find_codex_entry()
        if not self.codex_js:
            raise RuntimeError(
                "CodexCLIClient: 找不到 codex.js. 请先 `npm i -g @openai/codex` 并 `codex login`"
            )
        self.tracker = TokenTracker()

    # ---------- prompt 构造 ----------

    @staticmethod
    def _flatten_system(system):
        if not system:
            return ""
        if isinstance(system, list):
            return "\n\n".join(
                s.get("text", "") if isinstance(s, dict) else str(s) for s in system
            )
        return str(system)

    @staticmethod
    def _flatten_messages(messages):
        out = []
        for m in messages:
            role = m.get("role", "user").upper()
            content = m.get("content", "")
            if isinstance(content, list):
                parts = []
                for blk in content:
                    if isinstance(blk, dict):
                        if blk.get("type") == "text":
                            parts.append(blk.get("text", ""))
                        elif blk.get("type") == "tool_result":
                            tr = blk.get("content", "")
                            if isinstance(tr, list):
                                tr = "\n".join(b.get("text", "") for b in tr if isinstance(b, dict))
                            parts.append(f"[tool_result] {tr}")
                content = "\n".join(parts)
            out.append(f"[{role}]\n{content}")
        return "\n\n".join(out)

    @staticmethod
    def _normalize_schema(schema):
        """OpenAI strict mode: 每层 object 必须 additionalProperties: false + 全 properties 在 required."""
        if not isinstance(schema, dict):
            return schema
        out = json.loads(json.dumps(schema))  # 深拷贝避免改原 tool

        def fix(node):
            if not isinstance(node, dict):
                return
            if node.get("type") == "object":
                node["additionalProperties"] = False
                # 确保 required 包含所有 properties (OpenAI strict 要求)
                props = node.get("properties", {})
                node["required"] = list(props.keys())
                for v in props.values():
                    fix(v)
            elif node.get("type") == "array":
                fix(node.get("items"))
            # anyOf / oneOf / allOf 也递归
            for k in ("anyOf", "oneOf", "allOf"):
                if k in node and isinstance(node[k], list):
                    for sub in node[k]:
                        fix(sub)

        fix(out)
        return out

    @staticmethod
    def _pick_structured_tool(tools, tool_choice):
        """tools + tool_choice 决定走结构化输出. 返回选中的 tool dict 或 None."""
        if not tools:
            return None
        if not tool_choice:
            return None
        if isinstance(tool_choice, str):
            if tool_choice in ("required", "any"):
                return tools[0] if isinstance(tools[0], dict) else None
            return None
        ttype = tool_choice.get("type")
        if ttype in ("any", "required"):
            return tools[0]
        if ttype == "tool":
            name = tool_choice.get("name")
            for t in tools:
                if t.get("name") == name:
                    return t
        return None

    # ---------- 主入口 ----------

    def create(self, model, max_tokens, system, messages, tools=None, tool_choice=None,
               temperature=0.2, retry_policy="foreground"):
        """Metrics 包装 _create_inner: 在失败时记 llm.api_call status=failure."""
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
                        "vendor": "codex_cli",
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

        req_id = _gen_req_id()
        tool_hint = (tools[0]["name"] if tools and isinstance(tools[0], dict) else "none")
        log.info(f"[codex_cli] req={req_id} tool={tool_hint} model={model} backend=codex")

        # 预算检查 (与其它 client 一致)
        max_budget = float(os.environ.get("MAX_BUDGET_USD", "0"))
        if max_budget > 0 and self.tracker.total_cost_usd() >= max_budget:
            from exceptions import APIError
            raise APIError(f"预算已耗尽: ${self.tracker.total_cost_usd():.2f} >= ${max_budget:.2f}")

        # prompt 拼接
        system_text = self._flatten_system(system)
        user_text = self._flatten_messages(messages)
        prompt_text = f"[SYSTEM]\n{system_text}\n\n{user_text}" if system_text else user_text

        # 结构化输出 schema
        structured_tool = self._pick_structured_tool(tools, tool_choice)
        schema_path = None
        last_path = None
        try:
            if structured_tool:
                schema = self._normalize_schema(structured_tool.get("input_schema", {}))
                # 顶层包一层 root 让 codex 知道 root 类型
                fd, schema_path = tempfile.mkstemp(suffix=".json", prefix="codex_schema_")
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(schema, f, ensure_ascii=False)

            fd2, last_path = tempfile.mkstemp(suffix=".txt", prefix="codex_last_")
            os.close(fd2)

            cmd = [
                self.node_bin, self.codex_js, "exec",
                "--json",
                "--ephemeral",
                "--skip-git-repo-check",
                "--ignore-rules",
                "-s", "read-only",
                "-o", last_path,
            ]
            if schema_path:
                cmd += ["--output-schema", schema_path]
            if model:
                cmd += ["-m", model]
            # 2026-04-28: prompt 走 stdin (用 "-" 占位), 不放 argv. Windows argv 32K 限制
            # 在苍鹰这种长 prompt 场景会触发 [WinError 206]. 与 claude_cli.py 同款规避.
            cmd += ["-"]

            # 重试 loop (subprocess 级)
            last_err = None
            stdout = ""
            stderr = ""
            for attempt in range(max_retries + 1):
                try:
                    proc = subprocess.run(
                        cmd,
                        input=prompt_text,
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        timeout=self._SCHEMA_REQUIRED_TIMEOUT_S,
                    )
                    stdout, stderr = proc.stdout or "", proc.stderr or ""
                    if proc.returncode == 0:
                        break
                    # 失败: 尝试解析 stdout JSONL 找具体 error
                    err_msg = self._extract_error_from_jsonl(stdout) or (stderr or stdout)[:300]
                    last_err = f"codex exec 退出码 {proc.returncode}: {err_msg}"
                    if attempt == max_retries:
                        from exceptions import APIError
                        raise APIError(last_err)
                    delay = 2 ** (attempt + 1)
                    log.warning(f"[codex_cli] req={req_id} 异常重试 {delay}s: {err_msg[:120]}")
                    time.sleep(delay)
                except subprocess.TimeoutExpired:
                    from exceptions import APIError
                    raise APIError(f"codex exec 超时 {self._SCHEMA_REQUIRED_TIMEOUT_S}s")

            # 解析 last_path 里的最终 message
            last_text = ""
            if os.path.isfile(last_path):
                with open(last_path, encoding="utf-8") as f:
                    last_text = f.read().strip()

            text_blocks = []
            tool_calls = []
            if structured_tool and last_text:
                try:
                    parsed = json.loads(last_text)
                    tool_calls.append({
                        "id": req_id,
                        "name": structured_tool["name"],
                        "input": parsed,
                    })
                except json.JSONDecodeError as e:
                    log.warning(f"[codex_cli] req={req_id} JSON parse 失败, 当 text 兜底: {e}")
                    text_blocks.append({"type": "text", "text": last_text})
            elif last_text:
                text_blocks.append({"type": "text", "text": last_text})

            # usage 从 stdout JSONL 的 turn.completed 提取
            usage = self._parse_usage_from_jsonl(stdout)

            stop_reason = "tool_use" if tool_calls else "end_turn"
            unified = UnifiedResponse(
                text_blocks=text_blocks,
                tool_calls=tool_calls,
                stop_reason=stop_reason,
                usage=usage,
                model=model or "gpt-5-codex",
                truncated=False,
            )
            self.tracker.record(
                model or "gpt-5-codex",
                usage["input_tokens"], usage["output_tokens"],
                usage.get("cache_creation_input_tokens", 0),
                usage.get("cache_read_input_tokens", 0),
            )

            # Metrics 埋点: llm.api_call (codex_cli success)
            try:
                _record_event(
                    "llm.api_call",
                    workspace=os.environ.get("WORKSPACE"),
                    duration_ms=int((time.time() - _metric_start) * 1000) if _metric_start else 0,
                    model=model or "gpt-5-codex",
                    status="success",
                    details={
                        "vendor": "codex_cli",
                        "tokens_in": usage["input_tokens"],
                        "tokens_out": usage["output_tokens"],
                        "cache_read": usage.get("cache_read_input_tokens", 0),
                        "retry_policy": retry_policy,
                    },
                )
            except Exception:
                pass

            return unified

        finally:
            for p in (schema_path, last_path):
                if p:
                    try:
                        os.unlink(p)
                    except OSError:
                        pass

    @staticmethod
    def _parse_usage_from_jsonl(stdout):
        """从 stdout JSONL events 找 turn.completed.usage."""
        usage = {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
        }
        if not stdout:
            return usage
        for line in stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                evt = json.loads(line)
            except json.JSONDecodeError:
                continue
            if evt.get("type") == "turn.completed":
                u = evt.get("usage", {})
                usage["input_tokens"] = u.get("input_tokens", 0)
                usage["output_tokens"] = u.get("output_tokens", 0)
                usage["cache_read_input_tokens"] = u.get("cached_input_tokens", 0)
                # reasoning_output_tokens 算进 output 方便统一统计
                usage["output_tokens"] += u.get("reasoning_output_tokens", 0)
                break
        return usage

    @staticmethod
    def _extract_error_from_jsonl(stdout):
        """从 stdout JSONL 找 error event 的 message."""
        if not stdout:
            return None
        for line in stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                evt = json.loads(line)
            except json.JSONDecodeError:
                continue
            if evt.get("type") in ("error", "turn.failed"):
                msg = evt.get("message") or evt.get("error", {}).get("message")
                if msg:
                    return str(msg)[:500]
        return None
