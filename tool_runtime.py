"""
Tool use 主循环 — 从 run_session.py 抽出

核心: tool_loop(...) 跑 Anthropic Messages API + tool use 迭代。
副产: _process_tool_result (大结果落盘) / _brief_input (工具入参简报)。

A4 保护: 每轮前检查 wall-clock 上限,防止 API 慢响应或死循环把 session 跑飞。
并发策略: 只读工具 (is_concurrency_safe_tool) 用 ThreadPoolExecutor 并发,
          写工具串行,两者之后统一打包成 tool_result blocks 回传。
"""

import concurrent.futures
import os
import time as _time
from typing import Any, Callable, Dict, List, Optional

from agent_config import MAX_TOKENS, MAX_TOOL_TURNS, TOOL_LOOP_TIMEOUT
from exceptions import AgentTimeoutError
from security import safe_execute_tool
from tools import TOOL_SCHEMAS, is_concurrency_safe_tool


# 只读工具集合(保留常量供旧代码兼容;真源在 tools.py 的 AgentTool.is_concurrency_safe)
CONCURRENT_SAFE_TOOLS = {"read_file", "search_files", "list_directory"}

# Tool result 落盘阈值 (参考 CC toolResultStorage.ts:272-334)
TOOL_RESULT_PERSIST_THRESHOLD = 10000


def process_tool_result(result: str, tool_name: str, workspace: str) -> str:
    """CC 模式: 大结果落盘+预览,空结果标记,错误不截断。

    - 空结果 → 标记字符串
    - [blocked]/[error] 前缀 → 原样透传
    - 超过 TOOL_RESULT_PERSIST_THRESHOLD → 落盘 + 返回 2KB 预览
    """
    if not result or not result.strip():
        return f"({tool_name} 执行完成，无输出)"

    if result.startswith("[blocked]") or result.startswith("[error]"):
        return result

    if len(result) <= TOOL_RESULT_PERSIST_THRESHOLD:
        return result

    persist_dir = os.path.join(workspace, "output", ".tool_results")
    os.makedirs(persist_dir, exist_ok=True)
    fname = f"{tool_name}_{int(_time.time())}.txt"
    fpath = os.path.join(persist_dir, fname)
    with open(fpath, "w", encoding="utf-8", errors="replace") as f:
        f.write(result)

    # 在换行处截断预览 (CC 用 2KB)
    preview = result[:2000]
    last_nl = preview.rfind("\n")
    if last_nl > 500:
        preview = preview[:last_nl]
    return f"{preview}\n...\n[完整结果已保存至 .tool_results/{fname}，共 {len(result)} 字符]"


def brief_input(inputs: Dict[str, Any]) -> str:
    """工具输入的简短展示 (只抓 path/command/pattern,限长 60)。"""
    if "path" in inputs:
        return inputs["path"]
    if "command" in inputs:
        cmd = inputs["command"]
        return cmd[:60] + "..." if len(cmd) > 60 else cmd
    if "pattern" in inputs:
        return inputs["pattern"]
    return ""


def _execute_tool_calls(tool_calls, workspace: str) -> Dict[str, str]:
    """按只读/写分流执行,只读工具多于 1 个时并发。

    抽出为子函数让 tool_loop 主体更清晰,也方便单独测并发分支。
    """
    safe_calls = [tc for tc in tool_calls if is_concurrency_safe_tool(tc.name)]
    unsafe_calls = [tc for tc in tool_calls if not is_concurrency_safe_tool(tc.name)]
    executed: Dict[str, str] = {}

    if len(safe_calls) > 1:
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            futures = {
                pool.submit(safe_execute_tool, tc.name, tc.input, workspace): tc
                for tc in safe_calls
            }
            for future in concurrent.futures.as_completed(futures):
                tc = futures[future]
                try:
                    executed[tc.id] = future.result()
                except Exception as e:
                    executed[tc.id] = f"[error] {e}"
    else:
        for tc in safe_calls:
            executed[tc.id] = safe_execute_tool(tc.name, tc.input, workspace)

    for tc in unsafe_calls:
        executed[tc.id] = safe_execute_tool(tc.name, tc.input, workspace)

    return executed


def tool_loop(
    client: Any,
    model: str,
    system_blocks: List[Dict[str, Any]],
    messages: List[Dict[str, Any]],
    workspace: str,
    turn_callback: Optional[Callable] = None,
    max_turns: int = MAX_TOOL_TURNS,
    wall_clock_limit: Optional[float] = None,
) -> List[Dict[str, Any]]:
    """Messages API + tool use 循环。

    A4: 加 wall-clock 总时长上限 (默认 TOOL_LOOP_TIMEOUT 秒),超时抛 AgentTimeoutError。
    max_turns 保护的是"最多几轮工具调用",wall_clock_limit 保护的是"最长跑多少秒"。
    两者是互补的: API 慢响应也会被 wall-clock 拦住。
    """
    start_time = _time.time()
    limit = wall_clock_limit if wall_clock_limit is not None else TOOL_LOOP_TIMEOUT

    for turn in range(max_turns):
        elapsed = _time.time() - start_time
        if elapsed > limit:
            raise AgentTimeoutError(
                f"tool_loop 超时:已运行 {elapsed:.0f}s,上限 {limit}s(轮次 {turn}/{max_turns})",
                elapsed=elapsed,
                limit=limit,
            )

        response = client.create(
            model=model,
            max_tokens=MAX_TOKENS,
            system=system_blocks,
            messages=messages,
            tools=TOOL_SCHEMAS,
        )

        # API 错误检查
        has_error = any(
            b.type == "text" and b.text.startswith("[API error]") for b in response.content
        )
        if has_error:
            for b in response.content:
                if b.type == "text":
                    print(b.text, flush=True)
            break

        # 解析响应
        text_parts: List[str] = []
        tool_calls: List[Any] = []
        for block in response.content:
            if block.type == "text":
                print(block.text, end="", flush=True)
                text_parts.append(block.text)
            elif block.type == "tool_use":
                print(f"\n  [tool] {block.name}({brief_input(block.input)})", flush=True)
                tool_calls.append(block)

        if tool_calls:
            # 按 Anthropic API 合约构建 assistant 消息
            assistant_content: List[Dict[str, Any]] = []
            for tp in text_parts:
                assistant_content.append({"type": "text", "text": tp})
            for tc in tool_calls:
                assistant_content.append({
                    "type": "tool_use", "id": tc.id, "name": tc.name, "input": tc.input,
                })
            messages.append({"role": "assistant", "content": assistant_content})

            executed = _execute_tool_calls(tool_calls, workspace)

            tool_results: List[Dict[str, Any]] = []
            for tc in tool_calls:
                result = executed[tc.id]
                processed = process_tool_result(result, tc.name, workspace)
                print(f"  [done] {result[:60]}", flush=True)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tc.id,
                    "content": processed,
                })
            messages.append({"role": "user", "content": tool_results})
        else:
            messages.append({"role": "assistant", "content": "\n".join(text_parts)})
            if response.stop_reason == "end_turn":
                print()
                break
            messages.append({"role": "user", "content": "请继续。"})

        if turn_callback:
            turn_callback(messages, response)

    return messages
