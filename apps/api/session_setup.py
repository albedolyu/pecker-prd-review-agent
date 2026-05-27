"""
main() 编排辅助 — 从 run_session.py 抽出

纯函数 / 单一职责小工具:
- build_parser(): argparse 定义
- apply_noninteractive_defaults(args): stdin/CI 场景下自动调整 args 和环境
- run_merge_mode(args): --merge 分支的完整流程 (独立于主评审链路)
- resolve_messages(resume_mode, resumed, ...): resume 策略决策
- build_initial_message(...): 首轮 prompt 字符串拼装
"""

import argparse
import datetime
import os
import sys
from typing import Any, List, Optional, Tuple

from agent_config import DEFAULT_WORKSPACE
from interactive_io import is_noninteractive, read_input


def build_parser() -> argparse.ArgumentParser:
    """构造Pecker主 CLI 解析器。"""
    parser = argparse.ArgumentParser(
        description="Pecker PRD Review Agent",
        epilog="示例:\n"
               "  python run_session.py 搜索优化\n"
               "  python run_session.py 搜索优化 --model opus\n"
               "  python run_session.py 搜索优化 --no-parallel\n"
               "  python run_session.py 搜索优化 --workspace ./my-project\n",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("prd_name", nargs="?", help="PRD 名称")
    parser.add_argument("--model", choices=["opus", "sonnet"], default="opus",
                        help="主Pecker model tier (默认 opus, CC OAT 订阅 0 边际成本). "
                             "router.intent auto 路由已废弃 (2026-04-28)")
    parser.add_argument("--reviewer", default=os.environ.get("REVIEWER", "default"))
    parser.add_argument("--workspace", default=DEFAULT_WORKSPACE, help="工作目录路径")
    parser.add_argument("--no-parallel", action="store_true",
                        help="关闭并行 Workers，用单 agent 评审")
    parser.add_argument("--merge", nargs=2, metavar="REVIEWER",
                        help="合并两个 reviewer 的评审结果")
    parser.add_argument("--non-interactive", action="store_true",
                        help="非交互模式(CI/CD),禁止 input() 阻塞,缺省值走 fallback")
    parser.add_argument("--resume", choices=["prompt", "auto", "skip"], default="prompt",
                        help="session 恢复策略: prompt=询问(默认), auto=自动恢复, skip=忽略旧 session")
    parser.add_argument("--auto-decide",
                        choices=["off", "by-confidence", "accept-all", "reject-all"],
                        default="off",
                        help=("Phase 3 批量决策: by-confidence 按 confidence 自动 Y/N "
                              "(>=0.8 接受, <0.5 驳回, 中间挂起);accept-all 全 Y;reject-all 全 N"))
    # Wave 2: model_router 配置入口
    parser.add_argument("--routes-file", default=None,
                        help="覆盖默认 model_routes.yaml (灰度/实验用, 设 PECKER_ROUTES_FILE)")
    parser.add_argument("--enable-shadow-advisor", action="store_true",
                        help="启用影子苍鹰对照 (advisor.goshawk.shadow), 设 PECKER_ENABLE_SHADOW_ADVISOR=1")
    # 步骤 3 后半段: profile + tone_instructions (CodeRabbit 风格 chill/strict 二档)
    parser.add_argument("--profile", choices=["chill", "strict"], default="chill",
                        help=("报告渲染档位 (默认 chill): "
                              "chill=只展示 must + 高置信 should, 隐藏 could; "
                              "strict=全展示 (历史行为). 设 PECKER_PROFILE=<value>"))
    parser.add_argument("--tone-instructions", default=None,
                        help=("Worker prompt 注入的语气指令 (per-team max 250 字符), "
                              "如 '用建议改为...而不是此处违反 X 原则'. "
                              "未提供时读 .env PECKER_TONE_INSTRUCTIONS, 再退回内置默认值"))
    return parser


def apply_noninteractive_defaults(args: argparse.Namespace, stdin_is_tty: bool) -> argparse.Namespace:
    """检测 nohup/CI/管道,自动调整 args 和环境变量。

    返回修改后的 args (同对象,就地修改,便于测试),并副作用性地设置:
    - PECKER_NONINTERACTIVE (非交互模式)
    - PECKER_AUTO_DECIDE (post_review 链消费)
    """
    if not stdin_is_tty and not args.non_interactive:
        print("[auto] 检测到 stdin 非 tty (nohup/CI/管道),自动启用 --non-interactive")
        args.non_interactive = True

    if args.non_interactive:
        os.environ["PECKER_NONINTERACTIVE"] = "1"

    if is_noninteractive() and args.resume == "prompt":
        args.resume = "skip"

    if is_noninteractive() and args.auto_decide == "off":
        args.auto_decide = "by-confidence"
        print("[auto] 非交互模式自动启用 --auto-decide=by-confidence")

    os.environ["PECKER_AUTO_DECIDE"] = args.auto_decide

    # Wave 2: model_router 全局配置 (worker.* tier override / 路由表 / 影子苍鹰)
    # auto 等价不 override (model_router 实现里直接 noop)
    os.environ["PECKER_MODEL_OVERRIDE"] = args.model
    if getattr(args, "routes_file", None):
        os.environ["PECKER_ROUTES_FILE"] = args.routes_file
    if getattr(args, "enable_shadow_advisor", False):
        os.environ["PECKER_ENABLE_SHADOW_ADVISOR"] = "1"

    # 步骤 3 后半段: profile + tone_instructions 落到 env (post_review + prompting 消费)
    profile = getattr(args, "profile", "chill") or "chill"
    os.environ["PECKER_PROFILE"] = profile

    tone = getattr(args, "tone_instructions", None)
    if tone:
        # 截到 250 字符 (per-team 上限, 超出截断 + warning)
        if len(tone) > 250:
            print(f"[warn] --tone-instructions 超过 250 字符上限, 已截断")
            tone = tone[:250]
        os.environ["PECKER_TONE_INSTRUCTIONS"] = tone
    return args


def run_merge_mode(args: argparse.Namespace) -> None:
    """--merge 分支的完整流程 (独立于主评审链路)。

    读取两个 reviewer 的 items,合并后输出到 output/PRD_合并报告_<date>.md。
    """
    from merge_reviews import load_reviewer_items, merge_reviews, format_merged_report

    prd_name = args.prd_name or read_input("PRD 名称: ", fallback="unnamed") or "unnamed"
    workspace = os.path.abspath(args.workspace)
    reviewer_a, reviewer_b = args.merge

    items_a = load_reviewer_items(workspace, prd_name, reviewer_a)
    items_b = load_reviewer_items(workspace, prd_name, reviewer_b)
    print(f"[合并] {reviewer_a}: {len(items_a)} 条, {reviewer_b}: {len(items_b)} 条")

    result = merge_reviews(items_a, items_b, reviewer_a, reviewer_b)
    report = format_merged_report(result)

    output_path = os.path.join(
        workspace, "output",
        f"PRD_合并报告_{datetime.date.today().strftime('%Y%m%d')}.md",
    )
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(report)

    print(f"[合并] 共识 {result['agreement']['agreed']} 条，合并后 {result['agreement']['total']} 条")
    print(f"[合并] 报告: {output_path}")


def resolve_messages(
    resume_mode: str,
    resumed: Optional[Tuple[List[Any], Any]],
) -> Optional[List[Any]]:
    """根据 --resume 策略决定是否恢复旧 messages。

    返回 List[message] (恢复) 或 None (新建)。
    - auto: 有旧的就自动用
    - skip: 忽略旧的
    - prompt: 询问用户 y/n
    """
    if not resumed:
        return None
    prev_messages, _prev_meta = resumed
    if not prev_messages:
        return None

    if resume_mode == "auto":
        print(f"[resume=auto] 自动恢复 {len(prev_messages)} 条消息的会话。\n")
        return prev_messages

    if resume_mode == "skip":
        print("[resume=skip] 忽略已有 session,开始新评审。")
        return None

    # prompt
    answer = read_input(
        "发现未完成的评审 session,是否恢复？(y/n): ",
        fallback="n",
    ).lower()
    if answer == "y":
        print(f"已恢复 {len(prev_messages)} 条消息的会话。\n")
        return prev_messages
    return None


def build_initial_message(
    date_str: str,
    reviewer: str,
    prd_name: str,
    workspace: str,
    branch_name: str,
) -> str:
    """构造首轮 user 消息。"""
    return (
        f"今天是 {date_str}。\n"
        f"评审人：{reviewer}\n"
        f"PRD 名称：{prd_name}\n"
        f"工作目录：{workspace}\n"
        f"Git 分支：{branch_name}\n\n"
        f"请执行 Phase 0 初始化，检查工作目录结构，然后执行 Phase 0.5 知识库预检。"
    )
