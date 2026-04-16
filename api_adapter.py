"""
API 适配层 -- Anthropic 原生客户端
"""

import os
import random
import json
import threading

# 重试策略（参考 Claude Code withRetry.ts:57-89 的 query source 分级）
RETRY_POLICIES = {
    "foreground": {"max_retries": 5, "retry_overload": True},   # Phase 1/3 交互，用户在等
    "worker":     {"max_retries": 2, "retry_overload": False},  # Phase 2 worker，失败走容错
    "advisor":    {"max_retries": 3, "retry_overload": True},   # 苍鹰，重要但可延迟
    "router":     {"max_retries": 1, "retry_overload": False},  # 意图路由，快速失败
}

# 模型降级链（参考 CC withRetry.ts:326-350 的 FallbackTriggeredError）
FALLBACK_MODELS = {
    "claude-opus-4-6": "claude-sonnet-4-6",
    "claude-sonnet-4-6": "claude-haiku-4-5-20251001",
}
MAX_CONSECUTIVE_OVERLOADS = 3  # 连续 N 次 529 后自动降级

# 成本定价（USD per million tokens）
MODEL_PRICING = {
    "claude-opus-4-6":            {"input": 15.0, "output": 75.0, "cache_read": 1.5, "cache_write": 18.75},
    "claude-sonnet-4-6":          {"input": 3.0,  "output": 15.0, "cache_read": 0.3, "cache_write": 3.75},
    "claude-haiku-4-5-20251001":  {"input": 0.8,  "output": 4.0,  "cache_read": 0.08, "cache_write": 1.0},
}
FLOOR_MAX_TOKENS = 3000  # 动态调整 max_tokens 的下限


# ============================================================
# Token 用量追踪
# ============================================================

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
# 统一响应对象
# ============================================================

class UnifiedResponse:
    """统一的 API 响应"""
    def __init__(self, text_blocks, tool_calls, stop_reason, usage, model, degraded=False):
        self.text_blocks = text_blocks
        self.tool_calls = tool_calls
        self.stop_reason = stop_reason
        self.usage = usage
        self.model = model
        # Phase G #1: 标记本次结构化输出是否被降级(JSON 解析失败 + 重试无效)
        # 上游可据此发出 worker_degraded 事件,前端能看到"这位编辑这次状态不好"
        self.degraded = degraded

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

    def create(self, model, max_tokens, system, messages, tools=None, tool_choice=None, temperature=0.2, retry_policy="foreground"):
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
        policy = RETRY_POLICIES.get(retry_policy, RETRY_POLICIES["foreground"])
        max_retries = policy["max_retries"]
        consecutive_overloads = 0
        current_model = kwargs["model"]
        response = None

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
                        continue  # 用新模型立即重试
                if attempt == max_retries:
                    from exceptions import APIError
                    raise APIError(f"API 限流 {max_retries + 1} 次均失败: {e}")
                delay = 2 ** (attempt + 1) + random.uniform(0, 1)
                log.warning(f"API 限流 (第{attempt + 1}次)，{delay:.1f}s 后重试: {str(e)[:80]}")
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
                    log.error(f"API {max_retries + 1} 次调用均失败: {e}")
                    raise APIError(f"API 调用 {max_retries + 1} 次均失败: {e}")
                delay = 2 ** (attempt + 1) + random.uniform(0, 1)
                log.warning(f"API 调用失败 (第{attempt + 1}次)，{delay:.1f}s 后重试: {str(e)[:80]}")
                time.sleep(delay)

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
        )
        cache_creation = getattr(response.usage, 'cache_creation_input_tokens', 0) or 0
        cache_read = getattr(response.usage, 'cache_read_input_tokens', 0) or 0
        self.tracker.record(response.model, response.usage.input_tokens, response.usage.output_tokens, cache_creation, cache_read)
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


# ============================================================
# Token 预估（参考 CC tokenEstimation.ts:203-224）
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


# ============================================================
# Claude Code CLI 后端（零 API key，复用本地 CC 登录态）
# ============================================================

class ClaudeCodeCLIClient:
    """通过 subprocess 调用本地 claude -p，不走 Anthropic API / 中转站。

    约束：
    - 需要本机安装 Claude Code CLI 且已登录（claude login）
    - 不支持真正的多轮 tool use；自定义 tool schema 会映射到 CC 内建 Read/Write/Grep/Glob/Bash
    - tool_choice={"type":"any"} 模式走「prompt 注入 schema + 解析 JSON」路径
    - 无 temperature / max_tokens 精细控制（CC 内部管）
    - 无原生 prompt cache 外显，但 CC 侧会自动缓存
    """

    # 自定义 tool → CC 内建 tool 映射（与 tools.py 保持同步）
    _CUSTOM_TO_BUILTIN = {
        "read_file": "Read",
        "write_file": "Write",
        "list_directory": "Glob",
        "search_files": "Grep",
        "run_bash": "Bash",
    }

    # 用于「禁用所有 tool」场景（Windows subprocess 上传 "" 会丢失参数，
    # 改用 --disallowed-tools 列举 CC 全部内建工具）
    _ALL_BUILTIN_TOOLS = (
        "Bash,Edit,Glob,Grep,Read,Write,WebFetch,WebSearch,"
        "Task,TodoWrite,BashOutput,KillShell,NotebookEdit,SlashCommand,SkillCommand"
    )

    def __init__(self):
        import shutil
        self.claude_bin = shutil.which("claude") or "claude"
        self.tracker = TokenTracker()
        # 子进程工作目录（supports workspace 沙箱语义）
        self._workspace = os.environ.get("WORKSPACE", "").strip() or None
        # Windows .CMD 包装在多行 / 超长 argv 下会丢参数，尝试定位 node+cli.js 直连
        self._node_bin, self._cli_js = self._locate_node_cli()

    def _locate_node_cli(self):
        """定位 node 和 claude-code cli.js，绕过 Windows .CMD 包装的 argv 限制。"""
        import shutil
        node_bin = shutil.which("node")
        if not node_bin:
            return None, None
        candidates = [
            os.path.join(os.path.dirname(self.claude_bin),
                         "node_modules", "@anthropic-ai", "claude-code", "cli.js"),
            os.path.expanduser("~/.npm-global/lib/node_modules/@anthropic-ai/claude-code/cli.js"),
            "/usr/local/lib/node_modules/@anthropic-ai/claude-code/cli.js",
            "/usr/lib/node_modules/@anthropic-ai/claude-code/cli.js",
        ]
        for c in candidates:
            if os.path.isfile(c):
                return node_bin, c
        return None, None

    # ---------- 对外接口（与 AnthropicNativeClient 签名一致）----------

    def create(self, model, max_tokens, system, messages, tools=None, tool_choice=None,
               temperature=0.2, retry_policy="foreground"):
        from logger import get_logger
        log = get_logger("api")

        system_text = self._flatten_system(system)
        prompt_text = self._flatten_messages(messages)

        # 决定输出模式
        structured_tool = self._pick_structured_tool(tools, tool_choice)

        if structured_tool is not None:
            # 结构化输出：禁用所有工具，prompt 末尾追加 schema，响应解析为 tool_use
            prompt_text = self._append_schema_instruction(prompt_text, structured_tool)
            tools_flag = None  # 用 disallowed-tools 屏蔽全部
        elif tools:
            # 自定义 tool loop：映射到 CC 内建 tool，由 CC 内部迭代
            tools_flag = self._map_tools_to_builtin(tools)
        else:
            # 纯文本：禁用所有工具
            tools_flag = None

        cc_model = self._map_model(model)

        # 优先 node + cli.js 直连（绕过 Windows .CMD 包装的 argv 限制和编码问题）
        if self._node_bin and self._cli_js:
            cmd = [self._node_bin, self._cli_js]
        else:
            cmd = [self.claude_bin]

        cmd += [
            "-p",
            "--no-session-persistence",
            "--model", cc_model,
            "--output-format", "json",
            "--permission-mode", "bypassPermissions",
        ]
        if tools_flag:
            cmd += ["--tools", tools_flag]
        else:
            # 无自定义工具：显式列出 CC 内建工具全部 disallow，确保模型只输出文本
            cmd += ["--disallowed-tools", self._ALL_BUILTIN_TOOLS]
        if system_text:
            cmd += ["--system-prompt", system_text]
        # prompt 走 stdin（不作为 argv positional），规避 Windows argv 长度与换行问题

        # 环境：清掉 Anthropic API 变量，强制走 CC OAuth 登录态
        env = os.environ.copy()
        for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN"):
            env.pop(k, None)

        cwd = self._workspace if self._workspace and os.path.isdir(self._workspace) else None

        # 预算检查（与 Anthropic 客户端保持一致）
        max_budget = float(os.environ.get("MAX_BUDGET_USD", "0"))
        if max_budget > 0 and self.tracker.total_cost_usd() >= max_budget:
            from exceptions import APIError
            raise APIError(f"预算已耗尽: ${self.tracker.total_cost_usd():.2f} >= ${max_budget:.2f}")

        import subprocess

        def _invoke_subprocess(invoke_prompt: str):
            """跑一次 claude -p 子进程,返回 (text_result, usage_dict, used_model_name)。
            失败抛 APIError(向上传递)。Phase G #1 把 subprocess 抽成 helper,以便
            JSON 解析失败时能换 prompt 重试。"""
            try:
                p = subprocess.run(
                    cmd,
                    input=invoke_prompt,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    env=env,
                    cwd=cwd,
                    timeout=600,
                )
            except subprocess.TimeoutExpired:
                from exceptions import APIError
                raise APIError("claude -p 子进程 600s 超时")
            except FileNotFoundError:
                from exceptions import APIError
                raise APIError(f"找不到 claude CLI: {self.claude_bin}。请先安装 Claude Code 并登录")

            if p.returncode != 0:
                from exceptions import APIError
                raise APIError(f"claude -p 退出码 {p.returncode}: {(p.stderr or p.stdout)[:300]}")

            stdout_local = (p.stdout or "").strip()
            if not stdout_local:
                from exceptions import APIError
                raise APIError(f"claude -p 无输出 (stderr: {p.stderr[:200]})")

            try:
                data_local = json.loads(stdout_local)
            except json.JSONDecodeError as e:
                from exceptions import APIError
                raise APIError(f"claude -p 输出非 JSON: {e}\n前 200 字: {stdout_local[:200]}")

            if data_local.get("is_error"):
                from exceptions import APIError
                raise APIError(f"claude -p 返回错误: {str(data_local.get('result', ''))[:300]}")

            return (
                data_local.get("result", "") or "",
                data_local.get("usage") or {},
                next(iter(data_local.get("modelUsage", {}).keys()), cc_model),
            )

        # ============ 第一次调用 ============
        text_result, usage, used_model = _invoke_subprocess(prompt_text)

        text_blocks = []
        tool_calls = []
        degraded_flag = False

        if structured_tool is not None:
            parsed = self._parse_json_from_text(text_result, structured_tool["name"])

            # ============ Phase G #1: 重试一次 ============
            if parsed is None:
                log.warning(
                    f"[cc_client] tool={structured_tool['name']} JSON 解析失败,重试一次"
                )
                retry_prompt = (
                    prompt_text
                    + "\n\n[系统重试提示]\n你上一次的输出不是合法的 JSON,无法被解析。"
                    + f"请严格按 {structured_tool['name']} 工具的 schema 格式重新输出,"
                    + "**只输出一个 JSON 对象**(不要 markdown code fence,不要解释文字),"
                    + "确保所有 string 字段被双引号包围,所有数组用 [],所有对象用 {}。"
                )
                try:
                    text_result_retry, usage_retry, used_model_retry = _invoke_subprocess(
                        retry_prompt
                    )
                    parsed_retry = self._parse_json_from_text(
                        text_result_retry, structured_tool["name"]
                    )
                    if parsed_retry is not None:
                        log.info(
                            f"[cc_client] tool={structured_tool['name']} 重试成功"
                        )
                        # 累加两次 usage(第一次 + 重试)
                        usage = {
                            k: int(usage.get(k, 0) or 0) + int(usage_retry.get(k, 0) or 0)
                            for k in set(usage.keys()) | set(usage_retry.keys())
                        }
                        text_result = text_result_retry
                        used_model = used_model_retry
                        parsed = parsed_retry
                except Exception as retry_err:
                    log.warning(
                        f"[cc_client] tool={structured_tool['name']} 重试本身抛错: {retry_err}"
                    )

            # ============ 重试仍失败:走 fallback 空壳 + 标记 degraded ============
            if parsed is None:
                log.warning(
                    f"[cc_client] tool={structured_tool['name']} 重试仍失败,返回空壳并标记 degraded"
                )
                parsed = self._empty_tool_fallback(structured_tool)
                degraded_flag = True

            import uuid as _uuid
            tool_calls.append({
                "id": f"toolu_{_uuid.uuid4().hex[:16]}",
                "name": structured_tool["name"],
                "input": parsed,
            })
            stop_reason = "tool_use"
        else:
            text_blocks.append({"type": "text", "text": text_result})
            stop_reason = "end_turn"

        unified_usage = {
            "input_tokens": int(usage.get("input_tokens") or 0),
            "output_tokens": int(usage.get("output_tokens") or 0),
            "cache_creation_input_tokens": int(usage.get("cache_creation_input_tokens") or 0),
            "cache_read_input_tokens": int(usage.get("cache_read_input_tokens") or 0),
        }

        self.tracker.record(
            used_model,
            unified_usage["input_tokens"],
            unified_usage["output_tokens"],
            unified_usage["cache_creation_input_tokens"],
            unified_usage["cache_read_input_tokens"],
        )

        return UnifiedResponse(
            text_blocks=text_blocks,
            tool_calls=tool_calls,
            stop_reason=stop_reason,
            usage=unified_usage,
            model=used_model,
            degraded=degraded_flag,
        )

    def create_stream(self, *args, **kwargs):
        """流式调用在 CC 后端下退化为同步 create()"""
        kwargs.pop("idle_timeout", None)
        return self.create(*args, **kwargs)

    # ---------- 内部辅助 ----------

    def _map_model(self, model):
        """支持 claude-opus-4-6 / claude-sonnet-4-6 / claude-haiku-* → CC 短别名"""
        m = (model or "").lower()
        if "opus" in m:
            return "opus"
        if "sonnet" in m:
            return "sonnet"
        if "haiku" in m:
            return "haiku"
        return model

    def _flatten_system(self, system):
        """system 支持 str 或 block list（cache_control 被忽略）"""
        if not system:
            return ""
        if isinstance(system, str):
            return system
        if isinstance(system, list):
            parts = []
            for block in system:
                if isinstance(block, dict):
                    parts.append(block.get("text", ""))
                elif isinstance(block, str):
                    parts.append(block)
            return "\n\n".join(p for p in parts if p)
        return str(system)

    def _flatten_messages(self, messages):
        """把 Anthropic messages 序列化成单一 prompt 字符串。

        历史 user/assistant 用 markdown 段落拼接；末尾用户消息作为当前 query 呈现。
        tool_use/tool_result block 被展平为文本摘要。
        """
        if not messages:
            return ""

        parts = []
        for msg in messages:
            role = msg.get("role", "user").upper()
            content = msg.get("content", "")
            rendered = self._render_content(content)
            if rendered:
                parts.append(f"## {role}\n{rendered}")

        return "\n\n".join(parts)

    def _render_content(self, content):
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            lines = []
            for block in content:
                if not isinstance(block, dict):
                    lines.append(str(block))
                    continue
                btype = block.get("type")
                if btype == "text":
                    lines.append(block.get("text", ""))
                elif btype == "tool_use":
                    name = block.get("name", "?")
                    inp = json.dumps(block.get("input", {}), ensure_ascii=False)
                    if len(inp) > 800:
                        inp = inp[:800] + "..."
                    lines.append(f"[调用工具 {name}]\n输入: {inp}")
                elif btype == "tool_result":
                    body = block.get("content", "")
                    if isinstance(body, list):
                        body = " ".join(
                            b.get("text", "") for b in body if isinstance(b, dict)
                        )
                    body = str(body)
                    if len(body) > 2000:
                        body = body[:2000] + "...(截断)"
                    lines.append(f"[工具返回]\n{body}")
            return "\n".join(l for l in lines if l)
        return str(content)

    def _pick_structured_tool(self, tools, tool_choice):
        """判断是否是结构化输出模式（tool_choice=any/tool），返回目标 tool schema"""
        if not tools or not tool_choice:
            return None
        choice_type = tool_choice.get("type") if isinstance(tool_choice, dict) else None
        if choice_type not in ("any", "tool"):
            return None
        if choice_type == "tool":
            name = tool_choice.get("name")
            for t in tools:
                if t.get("name") == name:
                    return t
            return None
        # type=any：取第一个
        return tools[0] if tools else None

    def _map_tools_to_builtin(self, tools):
        """自定义 tool → CC 内建 tool name 逗号分隔字符串"""
        mapped = set()
        for t in tools:
            name = t.get("name") if isinstance(t, dict) else None
            if name in self._CUSTOM_TO_BUILTIN:
                mapped.add(self._CUSTOM_TO_BUILTIN[name])
        if not mapped:
            return "default"
        return ",".join(sorted(mapped))

    def _append_schema_instruction(self, prompt_text, tool_schema):
        """在 prompt 末尾追加「只输出 JSON」的硬约束"""
        schema_json = json.dumps(tool_schema.get("input_schema", {}), ensure_ascii=False, indent=2)
        tool_name = tool_schema.get("name", "?")
        tool_desc = tool_schema.get("description", "")
        instr = (
            f"\n\n---\n"
            f"## 输出格式要求（MUST）\n"
            f"本环境不支持原生 tool use。你必须输出一段能作为工具 `{tool_name}` 输入的 JSON 对象。\n"
            f"工具说明：{tool_desc}\n\n"
            f"### Input Schema\n```json\n{schema_json}\n```\n\n"
            f"### 规则\n"
            f"- 直接输出 JSON 对象本身，不要任何前言、解释、总结\n"
            f"- 不要用 markdown 代码围栏包裹\n"
            f"- 字段必须严格符合 schema\n"
            f"- 如果没有发现问题，提交空的 items 数组（仍然是合法 JSON 对象）\n"
        )
        return prompt_text + instr

    def _parse_json_from_text(self, text, tool_name):
        """从返回文本中鲁棒解析 JSON 对象"""
        if not text:
            return None
        text = text.strip()

        # 去 markdown code fence
        if text.startswith("```"):
            lines = text.split("\n")
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines).strip()

        # 直接解析
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # 找第一个完整 {...}
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                pass

        return None

    def _empty_tool_fallback(self, tool_schema):
        """JSON 解析失败时的兜底结构（让上游能继续而不崩）"""
        name = tool_schema.get("name", "")
        if name == "submit_review_items":
            return {"dimension": "unknown", "items": []}
        if name == "submit_advisor_review":
            return {
                "flagged_as_false_positive": [],
                "additional_findings": [],
                "conflict_resolutions": [],
                "confidence": 0.0,
            }
        return {}


# ============================================================
# 工厂函数
# ============================================================

def create_client(api_key=None, base_url=None, **kwargs):
    """创建 API 客户端。

    只走本地 Claude Code CLI（零 API key，复用当前 CC 登录态）。
    api_key / base_url 参数保留仅为兼容旧调用签名，实际被忽略。
    """
    return ClaudeCodeCLIClient()
