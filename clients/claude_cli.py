"""Claude Code CLI 后端 (subprocess 调 `claude -p`,复用本地 OAuth 登录态).

从 api_adapter.py 拆出 (2026-04-16):
- _ensure_git_bash_in_path: Windows 多进程并发 PATH 兜底
- ClaudeCodeCLIClient: CLI 版本 client (与 AnthropicNativeClient 签名兼容)

关键约束:
- 需要本机 Claude Code CLI 已登录
- 无原生 tool use 支持, tool_choice={"type":"any"} 走 "prompt 注入 schema + 解析 JSON"
- prompt 走 stdin 规避 Windows argv 限制
- 优先 node + cli.js 直连,绕过 .CMD 包装的 argv 问题
- JSON 解析 3 层 fallback (json.loads → 切 {} → json-repair)

当前生产主路径走这个 client (零 API key 成本)。
"""

import json
import os


def _ensure_git_bash_in_path(env: dict) -> dict:
    """Windows 兜底: Claude CLI 要求 git-bash,多进程并发时 PATH 继承偶发丢失。

    已知故障: data_quality worker 偶发 "Claude Code on Windows requires git-bash"。
    根因: Python 多进程 os.environ 快照竞争,某些子进程 PATH 里没有 Git\\bin。
    修法: 检测 env["PATH"] 里有没有 bash.exe,没有就把常见 Git 安装路径拼到前面。
    其他平台无影响。
    """
    if os.name != "nt":
        return env
    path = env.get("PATH", "") or ""
    sep = os.pathsep
    candidates = [
        r"C:\Program Files\Git\bin",
        r"C:\Program Files\Git\usr\bin",
        r"C:\Program Files (x86)\Git\bin",
    ]
    # 已经有 bash.exe 就不动
    for p in path.split(sep):
        if p and os.path.isfile(os.path.join(p, "bash.exe")):
            return env
    # 把第一个存在的 Git 目录拼到 PATH 最前
    for c in candidates:
        if os.path.isdir(c):
            env["PATH"] = c + sep + path
            break
    return env


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
        # 延迟 import 避免循环
        from clients.token_tracker import TokenTracker

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

    # 触发 subprocess 级 retry 的错误片段 (见 _create_once)
    _PARSE_RETRY_HINTS = (
        "CLI JSON parse failed",
        "输出非 JSON",
    )

    def create(self, model, max_tokens, system, messages, tools=None, tool_choice=None,
               temperature=0.2, retry_policy="foreground"):
        """对 _create_once 加 subprocess 级 retry (parse 失败重试 1 次).

        Shadow run (N=80) 见过 2.5% "CLI JSON parse failed" — 根因是 streaming
        stdout 偶发截断或 model 输出被外部打断,不是系统性 prompt 问题,retry 一次
        通常就好。多于 1 次 retry 就说明是真的 LLM 输出问题,不再浪费配额。
        """
        from exceptions import APIError
        from logger import get_logger
        log = get_logger("api")

        last_err = None
        for attempt in range(2):
            try:
                return self._create_once(
                    model, max_tokens, system, messages,
                    tools=tools, tool_choice=tool_choice,
                    temperature=temperature, retry_policy=retry_policy,
                )
            except APIError as e:
                last_err = e
                msg = str(e)
                is_parse_err = any(h in msg for h in self._PARSE_RETRY_HINTS)
                if attempt == 0 and is_parse_err:
                    log.warning(f"[cc_client] parse 失败 retry 一次: {msg[:120]}")
                    continue
                raise
        # 理论不可达: attempt=1 的分支必然 raise
        raise last_err if last_err else APIError("CLI retry 链异常")

    def _create_once(self, model, max_tokens, system, messages, tools=None, tool_choice=None,
                     temperature=0.2, retry_policy="foreground"):
        from logger import get_logger
        from clients.shared import UnifiedResponse, _gen_req_id

        log = get_logger("api")

        # retry chain ID (CC requestLogId 模式)
        req_id = _gen_req_id()
        tool_hint = (tools[0]["name"] if tools and isinstance(tools[0], dict) else "none")
        log.info(f"[cc_client] req={req_id} tool={tool_hint} model={model} backend=cli")

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
        # Windows 多进程 PATH 偶发丢失 git-bash,显式兜底 (见 _ensure_git_bash_in_path doc)
        env = _ensure_git_bash_in_path(env)

        cwd = self._workspace if self._workspace and os.path.isdir(self._workspace) else None

        # 预算检查（与 Anthropic 客户端保持一致）
        max_budget = float(os.environ.get("MAX_BUDGET_USD", "0"))
        if max_budget > 0 and self.tracker.total_cost_usd() >= max_budget:
            from exceptions import APIError
            raise APIError(f"预算已耗尽: ${self.tracker.total_cost_usd():.2f} >= ${max_budget:.2f}")

        import subprocess
        try:
            proc = subprocess.run(
                cmd,
                input=prompt_text,
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

        if proc.returncode != 0:
            from exceptions import APIError, QuotaExhaustedError
            err_text = (proc.stderr or proc.stdout)[:500]
            # P0-3: 配额耗尽专用异常类型,让 UI 能给出"配额重置时间"友好提示
            if "hit your limit" in err_text or "usage limit" in err_text.lower():
                import re
                m = re.search(r"resets\s+([^\"\\]+?)(?:\"|$|\\)", err_text)
                reset_hint = m.group(1).strip() if m else None
                raise QuotaExhaustedError(
                    f"Claude CLI 配额已用完{(', ' + reset_hint + ' 重置') if reset_hint else ''}",
                    reset_hint=reset_hint,
                )
            raise APIError(f"claude -p 退出码 {proc.returncode}: {err_text[:300]}")

        stdout = (proc.stdout or "").strip()
        if not stdout:
            from exceptions import APIError
            raise APIError(f"claude -p 无输出 (stderr: {proc.stderr[:200]})")

        try:
            data = json.loads(stdout)
        except json.JSONDecodeError as e:
            from exceptions import APIError
            raise APIError(f"claude -p 输出非 JSON: {e}\n前 200 字: {stdout[:200]}")

        if data.get("is_error"):
            from exceptions import APIError
            raise APIError(f"claude -p 返回错误: {str(data.get('result', ''))[:300]}")

        text_result = data.get("result", "") or ""
        usage = data.get("usage") or {}
        # 从 modelUsage 取真实 model 名,回退到传入的 model
        used_model = next(iter(data.get("modelUsage", {}).keys()), cc_model)

        # 1c: max_output_recovery — 检测 CLI 返回的 stop_reason
        cli_stop_reason = data.get("stop_reason", "")
        is_truncated = (cli_stop_reason == "max_tokens")
        if is_truncated:
            log.warning(f"[cc_client] req={req_id} CLI stop_reason=max_tokens, 输出被截断")

        text_blocks = []
        tool_calls = []

        if structured_tool is not None:
            parsed = self._parse_json_from_text(text_result, structured_tool["name"])
            if parsed is None:
                # P0-2: JSON 解析失败不能静默返回空壳(会被上游当成"评审无问题")
                # 改为抛 APIError,让 worker error 上报链路接管
                from exceptions import APIError
                log.error(
                    f"[cc_client] tool={structured_tool['name']} JSON 解析失败, "
                    f"text_result 前 200 字: {text_result[:200]}"
                )
                raise APIError(
                    f"CLI JSON parse failed for tool {structured_tool['name']} "
                    f"(text_result {len(text_result)} chars)"
                )
            import uuid as _uuid
            tool_calls.append({
                "id": f"toolu_{_uuid.uuid4().hex[:16]}",
                "name": structured_tool["name"],
                "input": parsed,
            })
            stop_reason = "tool_use"
        else:
            text_blocks.append({"type": "text", "text": text_result})
            stop_reason = data.get("stop_reason") or "end_turn"

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
            truncated=is_truncated,
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
        """从返回文本中鲁棒解析 JSON 对象。

        3 层 fallback:
          L1: 直接 json.loads (标准 JSON)
          L2: 切首尾 {} 后 json.loads (带前后文本污染)
          L3: json-repair 修复 (处理单引号/尾逗号/Python True/None 等 LLM 常见偏离)

        真实 shadow run 出现过 2 条 CLI JSON parse failed,本函数新加 L3 专治。
        """
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

        # L1: 直接解析
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # L2: 找第一个完整 {...}
        candidate = None
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            candidate = text[start:end + 1]
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                pass

        # L3: json-repair 修复 LLM 常见偏离 (单引号 / 尾逗号 / Python 常量 / 未闭合等)
        try:
            from json_repair import loads as _repair_loads
        except ImportError:
            return None

        for raw in (candidate, text):
            if not raw:
                continue
            try:
                repaired = _repair_loads(raw)
                # json-repair 失败时返回 "" (字符串),不是合法 dict/list,要过滤
                if isinstance(repaired, (dict, list)):
                    return repaired
            except Exception:
                continue
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
