"""
啄木鸟 PRD 评审 Agent

用法：
  python run_session.py 搜索优化                    # auto 路由
  python run_session.py 搜索优化 --model opus       # 强制 Opus
  python run_session.py 搜索优化 --workspace /path  # 指定工作目录
  python run_session.py 搜索优化 --parallel         # Phase 2 用并行 Workers
"""

import argparse
import datetime
import io
import json
import os
import re
import subprocess
import sys

# Windows 终端强制 UTF-8 输出（防止 emoji 导致 GBK 编码崩溃）
if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from logger import setup_logging, log_agent_call
setup_logging()

from dotenv import load_dotenv

from agent_config import (
    load_system_prompt, MODEL_TIERS, ROUTER_PROMPT, DEFAULT_WORKSPACE,
    MAX_TOKENS, MAX_TOOL_TURNS, TOOL_LOOP_TIMEOUT,
)
from exceptions import AgentTimeoutError
from tools import TOOL_SCHEMAS, is_concurrency_safe_tool
from security import safe_execute_tool, save_session_turn, resume_session, get_session_path
from context_manager import create_turn_callback, read_scratchpad
from api_adapter import create_client
from easter_eggs import (
    show_startup_art, get_phase_line, get_fortune,
    handle_hidden_command,
)

# --- 配置变量（在 main() 中初始化）---
API_KEY = ""
BASE_URL = "https://api.anthropic.com"


# --- 非交互模式 helper ---
def _is_noninteractive():
    """检测是否处于非交互模式(CI/CD 场景)

    触发条件:
    - 环境变量 PECKER_NONINTERACTIVE=1/true/yes
    - 或 CLI 参数 --non-interactive 被设置(会在 main() 中设置环境变量)
    """
    return os.environ.get("PECKER_NONINTERACTIVE", "").lower() in ("1", "true", "yes")


def _read_input(prompt, fallback=""):
    """非交互模式下直接返回 fallback,不调用 input()

    用法:
        name = _read_input("PRD 名称: ", fallback="unnamed")
    """
    if _is_noninteractive():
        return fallback
    try:
        return input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        return fallback


def validate_config():
    """启动时校验所有必需配置，给人话报错"""
    errors = []
    warnings = []

    use_cc = os.environ.get("USE_CLAUDE_CODE", "").strip().lower() in ("1", "true", "yes", "on")

    if use_cc:
        # 走本地 Claude Code CLI，只要 claude 可用即可，不需要 API key
        import shutil
        if not shutil.which("claude"):
            errors.append("USE_CLAUDE_CODE=1 但本机找不到 claude CLI。请先安装 Claude Code 并执行 `claude login`")
        else:
            print("  [后端] 使用本地 Claude Code CLI（零 API key 模式）")
    else:
        if not API_KEY:
            errors.append("ANTHROPIC_API_KEY 未设置。请在 .env 中配置，或改用 USE_CLAUDE_CODE=1 走本地 CC")
        elif not API_KEY.startswith("sk-"):
            warnings.append(f"ANTHROPIC_API_KEY 格式异常（不以 sk- 开头），可能无法使用: {API_KEY[:10]}...")

        if not BASE_URL:
            warnings.append("ANTHROPIC_BASE_URL 未设置，将使用默认 https://api.anthropic.com")
        elif not BASE_URL.startswith("http"):
            errors.append(f"ANTHROPIC_BASE_URL 格式错误（需以 http 开头）: {BASE_URL}")

    if warnings:
        for w in warnings:
            print(f"  [警告] {w}")

    if errors:
        print("\n配置检查失败：")
        for e in errors:
            print(f"  [错误] {e}")
        print("\n请检查 .env 文件或环境变量。参考 .env.example")
        sys.exit(1)


def _init_config():
    """加载配置，仅在 main() 中调用"""
    global API_KEY, BASE_URL
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    load_dotenv(env_path, override=True)
    os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)
    API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
    BASE_URL = os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com")
    validate_config()


# ============================================================
# 意图路由
# ============================================================

def route_intent(client, prd_name, user_instruction="PRD 评审"):
    """用 Haiku 做轻量分类，决定用哪个模型"""
    try:
        response = client.create(
            model=MODEL_TIERS["haiku"],
            max_tokens=10,
            system=ROUTER_PROMPT,
            messages=[{
                "role": "user",
                "content": f"PRD 名称：{prd_name}\n用户指令：{user_instruction}",
            }],
        )
        tier = response.content[0].text.strip().lower()
        if tier in MODEL_TIERS:
            return tier
    except Exception:
        pass
    return "sonnet"


# ============================================================
# Tool 执行循环（核心）
# ============================================================

# 只读工具集合(保留常量供旧代码兼容;真源在 tools.py 的 AgentTool.is_concurrency_safe)
# 改动时优先改 tools.py _AGENT_TOOLS 定义,这里由 is_concurrency_safe_tool(name) 查询。
CONCURRENT_SAFE_TOOLS = {"read_file", "search_files", "list_directory"}

# Tool result 落盘阈值（参考 CC toolResultStorage.ts:272-334）
TOOL_RESULT_PERSIST_THRESHOLD = 10000


def _process_tool_result(result, tool_name, workspace):
    """CC 模式：大结果落盘+预览，空结果标记，错误不截断"""
    if not result or not result.strip():
        return f"({tool_name} 执行完成，无输出)"

    if result.startswith("[blocked]") or result.startswith("[error]"):
        return result

    if len(result) <= TOOL_RESULT_PERSIST_THRESHOLD:
        return result

    # 大结果写磁盘，返回 2KB 预览
    import time as _t
    persist_dir = os.path.join(workspace, "output", ".tool_results")
    os.makedirs(persist_dir, exist_ok=True)
    fname = f"{tool_name}_{int(_t.time())}.txt"
    fpath = os.path.join(persist_dir, fname)
    with open(fpath, "w", encoding="utf-8", errors="replace") as f:
        f.write(result)

    # 在换行处截断预览（CC 用 2KB）
    preview = result[:2000]
    last_nl = preview.rfind("\n")
    if last_nl > 500:
        preview = preview[:last_nl]
    return f"{preview}\n...\n[完整结果已保存至 .tool_results/{fname}，共 {len(result)} 字符]"


def tool_loop(client, model, system_blocks, messages, workspace, turn_callback=None, max_turns=MAX_TOOL_TURNS, wall_clock_limit=None):
    """
    Messages API + tool use 循环

    A4: 加 wall-clock 总时长上限(默认 TOOL_LOOP_TIMEOUT 秒),超时抛 AgentTimeoutError。
    max_turns 保护的是"最多几轮工具调用",wall_clock_limit 保护的是"最长跑多少秒"。
    两者是互补的:API 慢响应也会被 wall-clock 拦住。
    """
    import time as _time
    start_time = _time.time()
    limit = wall_clock_limit if wall_clock_limit is not None else TOOL_LOOP_TIMEOUT

    for turn in range(max_turns):
        # A4: 每轮前检查 wall-clock
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
        has_error = any(b.type == "text" and b.text.startswith("[API error]") for b in response.content)
        if has_error:
            for b in response.content:
                if b.type == "text":
                    print(b.text, flush=True)
            break

        # 解析响应
        text_parts = []
        tool_calls = []
        for block in response.content:
            if block.type == "text":
                print(block.text, end="", flush=True)
                text_parts.append(block.text)
            elif block.type == "tool_use":
                print(f"\n  [tool] {block.name}({_brief_input(block.input)})", flush=True)
                tool_calls.append(block)

        if tool_calls:
            # 执行工具，按 Anthropic API 合约构建 tool_result blocks
            assistant_content = []
            for tp in text_parts:
                assistant_content.append({"type": "text", "text": tp})
            for tc in tool_calls:
                assistant_content.append({"type": "tool_use", "id": tc.id, "name": tc.name, "input": tc.input})
            messages.append({"role": "assistant", "content": assistant_content})

            tool_results = []
            # CC 模式:只读工具可并发,写工具串行
            # 真源是 tools.AgentTool.is_concurrency_safe(查询通过 is_concurrency_safe_tool)
            safe_calls = [tc for tc in tool_calls if is_concurrency_safe_tool(tc.name)]
            unsafe_calls = [tc for tc in tool_calls if not is_concurrency_safe_tool(tc.name)]
            executed = {}

            if len(safe_calls) > 1:
                # 多个只读工具并发执行
                import concurrent.futures
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

            for tc in tool_calls:
                result = executed[tc.id]
                processed = _process_tool_result(result, tc.name, workspace)
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


def _brief_input(inputs):
    """工具输入的简短展示"""
    if "path" in inputs:
        return inputs["path"]
    if "command" in inputs:
        cmd = inputs["command"]
        return cmd[:60] + "..." if len(cmd) > 60 else cmd
    if "pattern" in inputs:
        return inputs["pattern"]
    return ""


# ============================================================
# PRD / Wiki 共享读取
# ============================================================

def load_prd_content(workspace):
    """读取 workspace/prd/ 下所有 .md 文件，返回 (prd_content, prd_files) 或 (None, [])"""
    prd_dir = os.path.join(workspace, "prd")
    prd_files = [f for f in os.listdir(prd_dir) if f.endswith(".md")] if os.path.isdir(prd_dir) else []
    if not prd_files:
        return None, []
    prd_parts = []
    for pf in sorted(prd_files):
        with open(os.path.join(prd_dir, pf), "r", encoding="utf-8") as f:
            prd_parts.append(f"## {pf}\n\n{f.read()}")
    return "\n\n---\n\n".join(prd_parts), prd_files


def load_wiki_pages(wiki_path):
    """读取 wiki 目录下所有 .md 页面（排除 index/log/scratchpad），返回 dict"""
    wiki_pages = {}
    if os.path.isdir(wiki_path):
        for wf in os.listdir(wiki_path):
            if wf.endswith(".md") and wf not in ("index.md", "log.md", "_scratchpad.md"):
                wp = os.path.join(wiki_path, wf)
                with open(wp, "r", encoding="utf-8", errors="replace") as f:
                    wiki_pages[wf.replace(".md", "")] = f.read()
    return wiki_pages


# ============================================================
# 并行评审（Phase 2）
# ============================================================

@log_agent_call("啄木鸟并行评审")
def run_parallel_review(client, workspace, wiki_path, prd_content, prd_files, wiki_pages, diff_context=None):
    """
    调用并行 Workers 评审 PRD，返回结构化改进项列表
    prd_content / prd_files / wiki_pages 由 main() 预读传入
    """
    from parallel_review import parallel_review, parallel_review_sync, verify_evidence
    from easter_eggs import calculate_peck_score, format_peck_score as format_peck

    if not prd_content:
        print("  [并行评审] prd/ 目录中没有 .md 文件，跳过")
        return None

    print(f"\n  [并行评审] PRD: {', '.join(sorted(prd_files))} ({len(prd_content)} 字)")
    print(f"  [并行评审] Wiki: {len(wiki_pages)} 页")
    print(f"  [并行评审] 派出: 织布鸟(结构) + 猫头鹰(质量) + 渡鸦(AI Coding) + 鸬鹚(数据)")

    # 用 adapter client 调 workers（并行 async）
    import asyncio
    # Windows 兼容：避免 asyncio 在 Windows 上的 ProactorEventLoop 问题
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    import time as _time
    t_start = _time.time()
    result = asyncio.run(parallel_review(client, prd_content, wiki_pages, MODEL_TIERS, wiki_path=wiki_path, diff_context=diff_context))
    elapsed = _time.time() - t_start
    print(f"  [并行评审] 4 个 worker 并行完成，耗时 {elapsed:.1f}s")

    # 打印 worker 结果
    for w in result["workers"]:
        if "error" in w and w["error"]:
            print(f"  [{w['dimension_name']}] 失败: {w['error'][:60]}")
        else:
            print(f"  [{w['dimension_name']}] 发现 {len(w['items'])} 条改进项")

    # 依据验证
    from parallel_review import summarize_verification
    verified = verify_evidence(result["merged_items"], workspace)
    retracted = [i for i in verified if i.get("status") == "RETRACTED"]
    verification_summary = summarize_verification(verified)
    if retracted:
        print(f"  [依据验证] {len(retracted)} 条因依据不足被撤回")
    if verification_summary["caveat"] > 0:
        print(f"  [依据验证] {verification_summary['caveat']} 条 C 类依据需人工确认")
    print(f"  [依据验证] 可靠率 {verification_summary['reliability']:.0%} "
          f"({verification_summary['verified']}/{verification_summary['total']})")

    valid_items = [i for i in verified if i.get("status") != "RETRACTED"]

    # 啄伤度
    peck = calculate_peck_score(valid_items)
    print(format_peck(peck))

    print(f"\n  [并行评审] 合并后 {len(valid_items)} 条有效改进项")
    print(f"  [token] input={result['total_usage']['input_tokens']}, output={result['total_usage']['output_tokens']}")

    return {
        "items": valid_items,
        "retracted": retracted,
        "verification_summary": verification_summary,
        "peck_score": peck,
        "usage": result["total_usage"],
    }


# ============================================================
# Phase 2.5: 苍鹰交叉校验
# ============================================================

@log_agent_call("苍鹰 meta 评审")
def run_goshawk_review(client, workspace, wiki_path, parallel_result, model, system_blocks, messages, session_file, turn_cb, prd_content, wiki_pages):
    """Phase 2.5: 苍鹰交叉校验。prd_content / wiki_pages 由 main() 预读传入。"""
    from goshawk_advisor import advisor_review, apply_advisor_result, format_advisor_report
    from easter_eggs import get_phase_line

    phase_line = get_phase_line("phase2.5")
    if phase_line:
        print(f"\n  {phase_line}")

    print("\n" + "=" * 60)
    print("Phase 2.5: 苍鹰交叉校验")
    print("=" * 60)

    if not prd_content:
        print("  苍鹰：找不到 PRD 文件，跳过交叉校验")
        return messages

    import time as _time
    t_start = _time.time()

    try:
        goshawk_result = advisor_review(
            client, prd_content, parallel_result["items"], wiki_pages,
        )
        elapsed = _time.time() - t_start

        updated_items = apply_advisor_result(parallel_result["items"], goshawk_result)
        parallel_result["items"] = updated_items
        parallel_result["goshawk"] = goshawk_result

        fp_count = len(goshawk_result.get("flagged_as_false_positive", []))
        add_count = len(goshawk_result.get("additional_findings", []))
        conf_count = len(goshawk_result.get("conflict_resolutions", []))
        print(f"\n  苍鹰审核完毕 ({elapsed:.1f}s)：误报 {fp_count}，补充 {add_count}，调解 {conf_count}，"
              f"信心度 {goshawk_result.get('confidence', 0):.0%}")

        goshawk_report = format_advisor_report(goshawk_result)
        messages.append({"role": "user", "content": f"苍鹰交叉校验已完成：\n{goshawk_report}\n\n请结合苍鹰的审核意见，进入 Phase 3 交互确认。"})
        from security import save_session_turn
        messages = tool_loop(client, model, system_blocks, messages, workspace, turn_callback=turn_cb)
        save_session_turn(session_file, messages, {"model": model, "turn": "goshawk"})
    except Exception as e:
        print(f"  苍鹰交叉校验失败（继续评审）: {str(e)[:80]}")

    return messages


# ============================================================
# System Prompt 构建
# ============================================================

def build_system_blocks(system_prompt, prd_content=None, workspace=None):
    """构建 system prompt blocks，支持 prompt caching"""
    blocks = [
        {
            "type": "text",
            "text": system_prompt,
            "cache_control": {"type": "ephemeral"},
        }
    ]

    if prd_content:
        blocks.append({
            "type": "text",
            "text": f"## 当前待评审 PRD 内容\n\n{prd_content}",
            "cache_control": {"type": "ephemeral"},
        })

    if workspace:
        scratchpad = read_scratchpad(workspace)
        if scratchpad:
            blocks.append({
                "type": "text",
                "text": f"## 当前评审状态\n\n{scratchpad}",
            })

    return blocks


# ============================================================
# Wiki 同步
# ============================================================

def sanitize_branch_name(name):
    """将中文/特殊字符转为 git 安全的分支名"""
    name = re.sub(r"[^\w\u4e00-\u9fff-]", "-", name)
    name = re.sub(r"-+", "-", name).strip("-")
    return name or "unnamed"


def wiki_pull(wiki_path):
    """评审开始前拉取最新知识库"""
    if not os.path.isdir(os.path.join(wiki_path, ".git")):
        return
    result = subprocess.run(
        ["git", "pull", "--rebase", "--autostash"],
        capture_output=True, text=True, cwd=wiki_path,
    )
    if result.returncode == 0:
        print(f"[wiki] 已同步最新知识库")
    else:
        print(f"[wiki] pull 失败（继续评审）: {result.stderr.strip()[:80]}")



# ============================================================
# 主流程
# ============================================================

def main():
    _init_config()

    parser = argparse.ArgumentParser(
        description="啄木鸟 PRD Review Agent",
        epilog="示例:\n"
               "  python run_session.py 搜索优化\n"
               "  python run_session.py 搜索优化 --model opus\n"
               "  python run_session.py 搜索优化 --no-parallel\n"
               "  python run_session.py 搜索优化 --workspace ./my-project\n",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("prd_name", nargs="?", help="PRD 名称")
    parser.add_argument("--model", choices=["auto", "opus", "sonnet", "haiku"], default="auto")
    parser.add_argument("--reviewer", default=os.environ.get("REVIEWER", "default"))
    parser.add_argument("--workspace", default=DEFAULT_WORKSPACE, help="工作目录路径")
    parser.add_argument("--no-parallel", action="store_true", help="关闭并行 Workers，用单 agent 评审")
    parser.add_argument("--merge", nargs=2, metavar="REVIEWER", help="合并两个 reviewer 的评审结果")
    parser.add_argument("--non-interactive", action="store_true",
                        help="非交互模式(CI/CD),禁止 input() 阻塞,缺省值走 fallback")
    parser.add_argument("--resume", choices=["prompt", "auto", "skip"], default="prompt",
                        help="session 恢复策略: prompt=询问(默认), auto=自动恢复, skip=忽略旧 session")
    parser.add_argument("--auto-decide", choices=["off", "by-confidence", "accept-all", "reject-all"],
                        default="off",
                        help=("缺失 ⑥ Phase 3 批量决策: by-confidence 按 confidence 自动 Y/N "
                              "(>=0.8 接受, <0.5 驳回, 中间挂起);accept-all 全 Y;reject-all 全 N"))
    args = parser.parse_args()

    # 缺失 ⑥ 自动检测 nohup/CI 等无 stdin 场景,自动启用非交互
    # (避免用户忘记加 --non-interactive 导致进程卡死)
    if not sys.stdin.isatty() and not args.non_interactive:
        print("[auto] 检测到 stdin 非 tty (nohup/CI/管道),自动启用 --non-interactive")
        args.non_interactive = True

    # 非交互模式:设置环境变量,让 _read_input() 和下游模块(post_review 等)都生效
    if args.non_interactive:
        os.environ["PECKER_NONINTERACTIVE"] = "1"
    # 非交互模式下 --resume 默认改为 skip(避免潜在 prompt)
    if _is_noninteractive() and args.resume == "prompt":
        args.resume = "skip"
    # 缺失 ⑥ 非交互模式下 --auto-decide 默认 by-confidence
    if _is_noninteractive() and args.auto_decide == "off":
        args.auto_decide = "by-confidence"
        print(f"[auto] 非交互模式自动启用 --auto-decide=by-confidence")
    # 设到环境让 post_review 链消费
    os.environ["PECKER_AUTO_DECIDE"] = args.auto_decide

    # 合并模式（--merge）
    if args.merge:
        from merge_reviews import load_reviewer_items, merge_reviews, format_merged_report
        prd_name = args.prd_name or _read_input("PRD 名称: ", fallback="unnamed") or "unnamed"
        workspace = os.path.abspath(args.workspace)
        reviewer_a, reviewer_b = args.merge
        items_a = load_reviewer_items(workspace, prd_name, reviewer_a)
        items_b = load_reviewer_items(workspace, prd_name, reviewer_b)
        print(f"[合并] {reviewer_a}: {len(items_a)} 条, {reviewer_b}: {len(items_b)} 条")
        result = merge_reviews(items_a, items_b, reviewer_a, reviewer_b)
        report = format_merged_report(result)
        output_path = os.path.join(workspace, "output", f"PRD_合并报告_{datetime.date.today().strftime('%Y%m%d')}.md")
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"[合并] 共识 {result['agreement']['agreed']} 条，合并后 {result['agreement']['total']} 条")
        print(f"[合并] 报告: {output_path}")
        return

    prd_name = args.prd_name or _read_input("PRD 名称: ", fallback="") or "unnamed"
    if _is_noninteractive() and not args.prd_name:
        print("[warn] 非交互模式未指定 PRD 名称,使用默认值 'unnamed'")
    workspace = os.path.abspath(args.workspace)

    if not os.path.isdir(workspace):
        print(f"ERROR: 工作目录不存在: {workspace}")
        print(f"  请创建目录并按以下结构组织：")
        print(f"  {workspace}/")
        print(f"  ├── prd/       ← 放入待评审的 PRD (.md 文件)")
        print(f"  ├── raw/       ← 原始业务资料（可选）")
        print(f"  ├── wiki/      ← 知识库（自动创建）")
        print(f"  └── output/    ← 评审产出（自动创建）")
        sys.exit(1)

    # 检查 prd/ 子目录
    prd_dir = os.path.join(workspace, "prd")
    if not os.path.isdir(prd_dir) or not any(f.endswith(".md") for f in os.listdir(prd_dir)):
        print(f"WARNING: {prd_dir} 中没有 .md 文件，评审可能无法正常进行")

    # 导出 WORKSPACE 给下游（CC 模式下 ClaudeCodeCLIClient 会用它当 subprocess cwd）
    os.environ["WORKSPACE"] = workspace

    # 创建 API 客户端
    client = create_client(api_key=API_KEY, base_url=BASE_URL)

    # 意图路由
    if args.model == "auto":
        model_tier = route_intent(client, prd_name)
        print(f"[router] PRD「{prd_name}」-> {model_tier}")
    else:
        model_tier = args.model

    model = MODEL_TIERS[model_tier]
    print(f"Pecker:    v1.0.0")
    print(f"Model:     {model}")
    print(f"Workspace: {workspace}")
    print(f"Reviewer:  {args.reviewer}")
    print(f"Parallel:  {'OFF' if args.no_parallel else 'ON'}\n")

    # 启动画面
    show_startup_art(model_tier)

    # Wiki 路径
    wiki_path = os.environ.get("WIKI_PATH", "").strip()
    wiki_path = os.path.abspath(wiki_path) if wiki_path and os.path.isdir(wiki_path) else os.path.join(workspace, "wiki")
    print(f"Wiki:      {wiki_path}")

    # 同步知识库
    wiki_pull(wiki_path)

    # 系统提示词
    system_prompt = load_system_prompt()
    system_prompt = system_prompt.replace("{{folder_path}}", workspace)
    system_prompt = system_prompt.replace("{{wiki_path}}", wiki_path)

    # 注入评审记忆(含 reviewer 偏好,CC memdir 模式,失败不阻断启动)
    # P0: 合并 reviewer_memory 到 review_memory,不再单独调 inject_reviewer_context
    # P1: 优先读 wiki/ 里的记忆页,降级读老 JSON(向后兼容)
    try:
        from review_memory import load_memories_for_context
        mem_context = load_memories_for_context(workspace, reviewer=args.reviewer, wiki_path=wiki_path)
        if mem_context:
            system_prompt += "\n\n" + mem_context + "\n"
    except Exception as e:
        print(f"  [警告] 加载评审记忆失败（继续启动）: {str(e)[:60]}")

    system_blocks = build_system_blocks(system_prompt, workspace=workspace)

    # Turn 回调
    turn_cb = create_turn_callback(workspace)

    # Session
    session_file = get_session_path(os.path.join(workspace, "output"), prd_name, args.reviewer)

    # 尝试恢复 —— 根据 --resume 策略决定
    resumed = resume_session(os.path.join(workspace, "output"), prd_name)
    if resumed:
        prev_messages, prev_meta = resumed
        if prev_messages:
            if args.resume == "auto":
                messages = prev_messages
                print(f"[resume=auto] 自动恢复 {len(messages)} 条消息的会话。\n")
            elif args.resume == "skip":
                print(f"[resume=skip] 忽略已有 session,开始新评审。")
                messages = None
            else:  # prompt
                answer = _read_input(
                    f"发现未完成的评审 session,是否恢复？(y/n): ",
                    fallback="n",
                ).lower()
                if answer == "y":
                    messages = prev_messages
                    print(f"已恢复 {len(messages)} 条消息的会话。\n")
                else:
                    messages = None
        else:
            messages = None
    else:
        messages = None

    # 首轮消息
    date_str = datetime.date.today().strftime("%Y-%m-%d")
    safe_reviewer = sanitize_branch_name(args.reviewer)
    safe_prd = sanitize_branch_name(prd_name)
    branch_name = f"review/{safe_reviewer}/{safe_prd}/{date_str}"

    if messages is None:
        init_message = (
            f"今天是 {date_str}。\n"
            f"评审人：{args.reviewer}\n"
            f"PRD 名称：{prd_name}\n"
            f"工作目录：{workspace}\n"
            f"Git 分支：{branch_name}\n\n"
            f"请执行 Phase 0 初始化，检查工作目录结构，然后执行 Phase 0.5 知识库预检。"
        )
        messages = [{"role": "user", "content": init_message}]

    # 首轮
    print("=" * 60)
    print("啄木鸟 PRD 评审")
    print("=" * 60)
    messages = tool_loop(client, model, system_blocks, messages, workspace, turn_callback=turn_cb)
    save_session_turn(session_file, messages, {"model": model, "turn": "init"})

    # 预读 PRD 和 Wiki（一次读取，Phase 2 / 2.5 共用）
    prd_content, prd_files = load_prd_content(workspace)
    wiki_pages = load_wiki_pages(wiki_path)

    # PRD 迭代 Diff 检测（发现上次评审时注入 diff 上下文）
    diff_context = None
    try:
        from prd_diff import detect_previous_review, compute_section_diff, load_previous_decisions, classify_previous_items, build_diff_context
        prev = detect_previous_review(workspace, prd_name)
        if prev and prd_content:
            with open(prev["snapshot_path"], "r", encoding="utf-8", errors="replace") as f:
                old_prd = f.read()
            diffs = compute_section_diff(old_prd, prd_content)
            modified_count = sum(1 for d in diffs if d["status"] in ("modified", "added"))
            if modified_count > 0:
                prev_items = load_previous_decisions(prev["report_path"])
                classified = classify_previous_items(prev_items, diffs)
                diff_context = build_diff_context(diffs, classified)
                print(f"  [迭代] 检测到上次评审 ({prev['date']})，{modified_count} 节有变更，{len(prev_items)} 条历史 item")
            else:
                print(f"  [迭代] PRD 与上次评审 ({prev['date']}) 无实质变更")
    except Exception as e:
        print(f"  [迭代] Diff 检测失败（继续正常评审）: {str(e)[:60]}")

    # 并行评审（默认开启）
    parallel_result = None
    if not args.no_parallel:
        print("\n" + "=" * 60)
        print("Phase 2: 并行评审（织布鸟 + 猫头鹰 + 渡鸦 + 鸬鹚）")
        print("=" * 60)
        parallel_result = run_parallel_review(client, workspace, wiki_path, prd_content, prd_files, wiki_pages, diff_context)

        if parallel_result and parallel_result["items"]:
            # 把并行评审结果注入对话，让啄木鸟整合
            items_summary = []
            for item in parallel_result["items"]:
                items_summary.append(
                    f"- {item.get('id', '?')} | {item.get('location', '?')} | "
                    f"{item.get('issue', '?')} | {item.get('severity', '?')} | "
                    f"[{item.get('dimension', '?')}]"
                )
            inject_msg = (
                f"并行评审团（织布鸟/猫头鹰/渡鸦/鸬鹚）已完成 Phase 2 评审，发现 {len(parallel_result['items'])} 条改进项：\n\n"
                + "\n".join(items_summary)
                + "\n\n请整合以上结果，进入 Phase 3 交互确认环节。"
            )
            messages.append({"role": "user", "content": inject_msg})
            messages = tool_loop(client, model, system_blocks, messages, workspace, turn_callback=turn_cb)
            save_session_turn(session_file, messages, {"model": model, "turn": "parallel_review"})

    # Phase 2.5: 苍鹰交叉校验
    if parallel_result and parallel_result["items"]:
        messages = run_goshawk_review(client, workspace, wiki_path, parallel_result, model, system_blocks, messages, session_file, turn_cb, prd_content, wiki_pages)

    # 多轮交互 —— 非交互模式下跳过,直接进入后处理
    if _is_noninteractive():
        print("\n[non-interactive] 跳过多轮对话环节,直接进入后处理链。")
    while not _is_noninteractive():
        try:
            user_input = input("\n你: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n退出会话。")
            break

        if not user_input:
            continue
        if user_input.lower() in ("exit", "quit", "q"):
            break

        # 隐藏命令
        handled, output = handle_hidden_command(user_input, wiki_path)
        if handled:
            print(output)
            continue

        if user_input.lower() == "/submit":
            user_input = (
                f"请执行以下操作：\n"
                f"1. git add wiki/ output/\n"
                f"2. git commit -m 'review: {prd_name} by {args.reviewer}'\n"
                f"3. git push origin {branch_name}\n"
                f"4. 告诉我 push 结果"
            )

        messages.append({"role": "user", "content": user_input})
        messages = tool_loop(client, model, system_blocks, messages, workspace, turn_callback=turn_cb)
        save_session_turn(session_file, messages, {"model": model, "turn": "interact"})

    # 后处理链
    from post_review import run_post_review
    run_post_review(
        workspace=workspace,
        wiki_path=wiki_path,
        prd_name=prd_name,
        reviewer=args.reviewer,
        model_tier=model_tier,
        parallel_result=parallel_result,
        feishu_webhook=os.environ.get("FEISHU_WEBHOOK", ""),
    )

    # Token 用量统计
    if hasattr(client, 'tracker'):
        print("\n" + "=" * 60)
        print("Token 用量统计")
        print("=" * 60)
        print(client.tracker.summary())

    print("\n会话结束。")


if __name__ == "__main__":
    main()