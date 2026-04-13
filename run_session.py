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

from logger import setup_logging
setup_logging()

from dotenv import load_dotenv

from agent_config import (
    load_system_prompt, MODEL_TIERS, ROUTER_PROMPT, DEFAULT_WORKSPACE,
    MAX_TOKENS, MAX_TOOL_TURNS,
)
from tools import TOOL_SCHEMAS
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


def validate_config():
    """启动时校验所有必需配置，给人话报错"""
    errors = []
    warnings = []

    if not API_KEY:
        errors.append("ANTHROPIC_API_KEY 未设置。请在 .env 中配置 Claude API Key")
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

def tool_loop(client, model, system_blocks, messages, workspace, turn_callback=None, max_turns=MAX_TOOL_TURNS):
    """
    Messages API + tool use 循环
    """
    for turn in range(max_turns):
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
            for tc in tool_calls:
                result = safe_execute_tool(tc.name, tc.input, workspace)
                truncated = result[:5000] + ("[...内容截断]" if len(result) > 5000 else "")
                print(f"  [done] {result[:60]}", flush=True)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tc.id,
                    "content": truncated,
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
# 并行评审（Phase 2）
# ============================================================

def run_parallel_review(client, workspace, wiki_path):
    """
    调用并行 Workers 评审 PRD，返回结构化改进项列表
    读取 prd/ 下的文件和 wiki/ 中的相关页面
    """
    from parallel_review import parallel_review, parallel_review_sync, verify_evidence, format_peck_score
    from easter_eggs import calculate_peck_score, format_peck_score as format_peck

    # 读取 PRD
    prd_dir = os.path.join(workspace, "prd")
    prd_files = [f for f in os.listdir(prd_dir) if f.endswith(".md")] if os.path.isdir(prd_dir) else []
    if not prd_files:
        print("  [并行评审] prd/ 目录中没有 .md 文件，跳过")
        return None

    # 读取 prd/ 中所有 .md 文件
    prd_parts = []
    for pf in sorted(prd_files):
        with open(os.path.join(prd_dir, pf), "r", encoding="utf-8") as f:
            prd_parts.append(f"## {pf}\n\n{f.read()}")
    prd_content = "\n\n---\n\n".join(prd_parts)

    # 读取 wiki 相关页面
    wiki_pages = {}
    if os.path.isdir(wiki_path):
        for wf in os.listdir(wiki_path):
            if wf.endswith(".md") and wf not in ("index.md", "log.md", "_scratchpad.md"):
                wp = os.path.join(wiki_path, wf)
                with open(wp, "r", encoding="utf-8", errors="replace") as f:
                    wiki_pages[wf.replace(".md", "")] = f.read()

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
    result = asyncio.run(parallel_review(client, prd_content, wiki_pages, MODEL_TIERS))
    elapsed = _time.time() - t_start
    print(f"  [并行评审] 4 个 worker 并行完成，耗时 {elapsed:.1f}s")

    # 打印 worker 结果
    for w in result["workers"]:
        if "error" in w and w["error"]:
            print(f"  [{w['dimension_name']}] 失败: {w['error'][:60]}")
        else:
            print(f"  [{w['dimension_name']}] 发现 {len(w['items'])} 条改进项")

    # 依据验证
    verified = verify_evidence(result["merged_items"], workspace)
    retracted = [i for i in verified if i.get("status") == "RETRACTED"]
    if retracted:
        print(f"  [依据验证] {len(retracted)} 条因依据不足被撤回")

    valid_items = [i for i in verified if i.get("status") != "RETRACTED"]

    # 啄伤度
    peck = calculate_peck_score(valid_items)
    print(format_peck(peck))

    print(f"\n  [并行评审] 合并后 {len(valid_items)} 条有效改进项")
    print(f"  [token] input={result['total_usage']['input_tokens']}, output={result['total_usage']['output_tokens']}")

    return {
        "items": valid_items,
        "retracted": retracted,
        "peck_score": peck,
        "usage": result["total_usage"],
    }


# ============================================================
# Phase 2.5: 苍鹰交叉校验
# ============================================================

def run_goshawk_review(client, workspace, wiki_path, parallel_result, model, system_blocks, messages, session_file, turn_cb):
    """Phase 2.5: 苍鹰交叉校验"""
    from goshawk_advisor import advisor_review, apply_advisor_result, format_advisor_report
    from easter_eggs import get_phase_line

    phase_line = get_phase_line("phase2.5")
    if phase_line:
        print(f"\n  {phase_line}")

    print("\n" + "=" * 60)
    print("Phase 2.5: 苍鹰交叉校验")
    print("=" * 60)

    # 读取 PRD
    prd_dir = os.path.join(workspace, "prd")
    prd_files = [f for f in os.listdir(prd_dir) if f.endswith(".md")] if os.path.isdir(prd_dir) else []
    if not prd_files:
        print("  苍鹰：找不到 PRD 文件，跳过交叉校验")
        return messages

    # 读取 prd/ 中所有 .md 文件
    prd_parts = []
    for pf in sorted(prd_files):
        with open(os.path.join(prd_dir, pf), "r", encoding="utf-8") as f:
            prd_parts.append(f"## {pf}\n\n{f.read()}")
    prd_content = "\n\n---\n\n".join(prd_parts)

    # 读取 wiki
    goshawk_wiki = {}
    if os.path.isdir(wiki_path):
        for wf in os.listdir(wiki_path):
            if wf.endswith(".md") and wf not in ("index.md", "log.md", "_scratchpad.md"):
                with open(os.path.join(wiki_path, wf), "r", encoding="utf-8", errors="replace") as f:
                    goshawk_wiki[wf.replace(".md", "")] = f.read()

    import time as _time
    t_start = _time.time()

    try:
        goshawk_result = advisor_review(
            client, prd_content, parallel_result["items"], goshawk_wiki,
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
    args = parser.parse_args()

    prd_name = args.prd_name or input("PRD 名称: ").strip() or "unnamed"
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
    system_blocks = build_system_blocks(system_prompt, workspace=workspace)

    # Turn 回调
    turn_cb = create_turn_callback(workspace)

    # Session
    session_file = get_session_path(os.path.join(workspace, "output"), prd_name, args.reviewer)

    # 尝试恢复
    resumed = resume_session(os.path.join(workspace, "output"), prd_name)
    if resumed:
        prev_messages, prev_meta = resumed
        if prev_messages:
            answer = input(f"发现未完成的评审 session，是否恢复？(y/n): ").strip().lower()
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

    # 并行评审（默认开启）
    parallel_result = None
    if not args.no_parallel:
        print("\n" + "=" * 60)
        print("Phase 2: 并行评审（织布鸟 + 猫头鹰 + 渡鸦 + 鸬鹚）")
        print("=" * 60)
        parallel_result = run_parallel_review(client, workspace, wiki_path)

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
        messages = run_goshawk_review(client, workspace, wiki_path, parallel_result, model, system_blocks, messages, session_file, turn_cb)

    # 多轮交互
    while True:
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