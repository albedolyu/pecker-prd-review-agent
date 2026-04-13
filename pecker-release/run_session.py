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
import json
import os
import re
import subprocess
import sys
from dotenv import load_dotenv

from agent_config import (
    load_system_prompt, MODEL_TIERS, ROUTER_PROMPT, DEFAULT_WORKSPACE,
    MAX_TOKENS, MAX_TOOL_TURNS,
)
from tools import TOOL_SCHEMAS
from security import safe_execute_tool, save_session_turn, resume_session, get_session_path, notify_feishu
from context_manager import create_turn_callback, read_scratchpad
from api_adapter import create_client
from easter_eggs import (
    show_startup_art, get_phase_line, get_fortune,
    handle_hidden_command, check_achievements, format_achievement_unlock,
    update_forest_in_index,
)

# --- 加载配置 ---
env_path = os.path.join(os.path.dirname(__file__), ".env")
load_dotenv(env_path)

# 清掉 Claude Code 注入的旧 auth token
os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)

API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
BASE_URL = os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com")

if not API_KEY:
    print("ERROR: ANTHROPIC_API_KEY 未设置。请在 .env 中配置。")
    sys.exit(1)


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
            # 执行工具
            tool_outputs = []
            for tc in tool_calls:
                result = safe_execute_tool(tc.name, tc.input, workspace)
                truncated = result[:5000] + ("[...内容截断]" if len(result) > 5000 else "")
                tool_outputs.append(f"[{tc.name}] {truncated}")
                print(f"  [done] {result[:60]}", flush=True)

            messages.append({"role": "assistant", "content": "\n".join(text_parts) or "(执行工具)"})
            messages.append({"role": "user", "content": "工具执行结果：\n\n" + "\n\n---\n\n".join(tool_outputs)})
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
    from parallel_review import parallel_review_sync, verify_evidence, format_peck_score
    from easter_eggs import calculate_peck_score, format_peck_score as format_peck

    # 读取 PRD
    prd_dir = os.path.join(workspace, "prd")
    prd_files = [f for f in os.listdir(prd_dir) if f.endswith(".md")] if os.path.isdir(prd_dir) else []
    if not prd_files:
        print("  [并行评审] prd/ 目录中没有 .md 文件，跳过")
        return None

    prd_path = os.path.join(prd_dir, prd_files[0])
    with open(prd_path, "r", encoding="utf-8") as f:
        prd_content = f.read()

    # 读取 wiki 相关页面
    wiki_pages = {}
    if os.path.isdir(wiki_path):
        for wf in os.listdir(wiki_path):
            if wf.endswith(".md") and wf not in ("index.md", "log.md", "_scratchpad.md"):
                wp = os.path.join(wiki_path, wf)
                with open(wp, "r", encoding="utf-8", errors="replace") as f:
                    wiki_pages[wf.replace(".md", "")] = f.read()

    print(f"\n  [并行评审] PRD: {prd_files[0]} ({len(prd_content)} 字)")
    print(f"  [并行评审] Wiki: {len(wiki_pages)} 页")
    print(f"  [并行评审] 派出: 织布鸟(结构) + 猫头鹰(质量) + 渡鸦(AI Coding) + 鸬鹚(数据)")

    # 用原生 Anthropic client 调 workers
    import anthropic
    raw_client = anthropic.Anthropic(api_key=API_KEY, base_url=BASE_URL)

    result = parallel_review_sync(raw_client, prd_content, wiki_pages, MODEL_TIERS)

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


def wiki_push(wiki_path, prd_name, reviewer):
    """评审结束后推送知识库变更"""
    if not os.path.isdir(os.path.join(wiki_path, ".git")):
        return
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        capture_output=True, text=True, cwd=wiki_path,
    )
    if not status.stdout.strip():
        print("[wiki] 无变更，跳过推送")
        return
    subprocess.run(["git", "add", "."], cwd=wiki_path)
    subprocess.run(
        ["git", "commit", "-m", f"review: {prd_name} by {reviewer}"],
        cwd=wiki_path,
    )
    result = subprocess.run(
        ["git", "push"], capture_output=True, text=True, cwd=wiki_path,
    )
    if result.returncode == 0:
        print(f"[wiki] 知识库已推送到 GitHub")
    else:
        print(f"[wiki] push 失败: {result.stderr.strip()[:80]}")


# ============================================================
# 主流程
# ============================================================

def main():
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
        sys.exit(1)

    # 创建 API 客户端
    client = create_client(api_key=API_KEY, base_url=BASE_URL)

    # 意图路由
    if args.model == "auto":
        model_tier = route_intent(client, prd_name)
        print(f"[router] PRD「{prd_name}」-> {model_tier}")
    else:
        model_tier = args.model

    model = MODEL_TIERS[model_tier]
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

    # 成就检查
    review_items = parallel_result["items"] if parallel_result else None
    new_achievements = check_achievements(wiki_path, review_items=review_items)
    unlock_msg = format_achievement_unlock(new_achievements)
    if unlock_msg:
        print(unlock_msg)

    # 更新知识森林
    update_forest_in_index(wiki_path)

    # 推送 wiki
    wiki_push(wiki_path, prd_name, args.reviewer)

    # 飞书通知
    feishu_webhook = os.environ.get("FEISHU_WEBHOOK", "")
    if feishu_webhook:
        notify_feishu(
            feishu_webhook,
            f"啄木鸟评审完成: {prd_name}",
            f"**PRD**: {prd_name}\n**评审人**: {args.reviewer}\n**模型**: {model_tier}",
        )

    print("\n会话结束。")


if __name__ == "__main__":
    main()