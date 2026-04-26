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


# --- 非交互模式 helper(已抽至 interactive_io.py,此处保留旧名兼容) ---
from interactive_io import is_noninteractive as _is_noninteractive
from interactive_io import read_input as _read_input


def check_pending_feedback(non_interactive: bool):
    """启动自检 (Plan 4 Layer 3): 扫描 .pecker_registry.json 里的下游仓库,
    看是否有 HEAD 已前进但还没让信鸽扫过。

    交互模式: 弹 [y/N/s] 提示
        y — 立即跑 feedback.py --scan-registered-repos
        N — 跳过(默认),下次启动再提醒
        s — silently 标记为已扫(用于 PM 不想被不相关 WIP 仓骚扰时)

    非交互模式: 只打印警告,不阻塞评审流程。
    """
    try:
        from registry import load_registry, list_pending, mark_scanned
    except ImportError:
        return  # registry 模块不存在也不阻塞

    registry_path = ".pecker_registry.json"
    if not os.path.isfile(registry_path):
        return  # 未注册任何仓库,静默跳过

    try:
        reg = load_registry(registry_path)
        pending = list_pending(reg)
    except Exception as e:
        print(f"[警告] 读取信鸽 registry 失败(不阻断): {str(e)[:80]}")
        return

    if not pending:
        return  # 无未扫信号,静默通过

    print()
    print(f"[信鸽] 发现 {len(pending)} 个已注册仓库有新 commit:")
    for p in pending:
        print(f"  - {p['repo_path']} (scope={p.get('scope','')}, 新 HEAD={p['current_sha'][:8]})")

    if non_interactive:
        print("[信鸽] 非交互模式,跳过自检。请后续手工执行:")
        print("       python feedback.py --scan-registered-repos --triggered-by session_start")
        return

    answer = _read_input(
        "[信鸽] 现在跑一次信号采集? [y/N/s] (s=标记已扫不运行): ",
        fallback="N",
    ).strip().lower()
    if answer == "y":
        print("[信鸽] 开始采集...")
        try:
            result = subprocess.run(
                [sys.executable, "feedback.py", "--scan-registered-repos",
                 "--triggered-by", "session_start"],
                cwd=os.path.dirname(os.path.abspath(__file__)) or ".",
            )
            if result.returncode != 0:
                print("[信鸽] 采集出现错误(不阻断评审),详情见 pigeon_runs/ 日志")
        except Exception as e:
            print(f"[信鸽] 调用 feedback.py 失败(不阻断): {str(e)[:80]}")
    elif answer == "s":
        print("[信鸽] 标记所有 pending 仓库为已扫(不采集信号)")
        for p in pending:
            try:
                mark_scanned(registry_path, p["repo_path"], p["current_sha"])
            except Exception as e:
                print(f"  [错误] 标记 {p['repo_path']} 失败: {str(e)[:60]}")
    else:
        print("[信鸽] 已跳过,下次启动会再次提醒")


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
# 意图路由(已抽至 router.py,此处保留旧名兼容)
# ============================================================

from router import route_intent


# ============================================================
# Tool 执行循环(已抽至 tool_runtime.py,保留旧名兼容)
# ============================================================

from tool_runtime import (
    CONCURRENT_SAFE_TOOLS,
    TOOL_RESULT_PERSIST_THRESHOLD,
    tool_loop,
)
from tool_runtime import process_tool_result as _process_tool_result
from tool_runtime import brief_input as _brief_input


# ============================================================
# PRD / Wiki 共享读取(已抽至 content_loader.py,保留旧名兼容)
# ============================================================

from content_loader import load_prd_content, load_wiki_pages


# ============================================================
# 并行评审（Phase 2）
# ============================================================

@log_agent_call("啄木鸟并行评审")
def run_parallel_review(client, workspace, wiki_path, prd_content, prd_files, wiki_pages, diff_context=None):
    """
    调用并行 Workers 评审 PRD，返回结构化改进项列表
    prd_content / prd_files / wiki_pages 由 main() 预读传入

    2026-04-16: CLI 路径也补上 EventStore 事件流,让 shadow_run 能采集
    telemetry (empty_retry_used / items_count / error / turns_used),
    与 api/routes/review.py 的 web 路径持平,STATUS.md 聚合数据两条路径都有。
    """
    from parallel_review import parallel_review, parallel_review_sync, verify_evidence
    from easter_eggs import calculate_peck_score, format_peck_score as format_peck

    if not prd_content:
        print("  [并行评审] prd/ 目录中没有 .md 文件，跳过")
        return None

    print(f"\n  [并行评审] PRD: {', '.join(sorted(prd_files))} ({len(prd_content)} 字)")
    print(f"  [并行评审] Wiki: {len(wiki_pages)} 页")
    print(f"  [并行评审] 派出: 织布鸟(结构) + 猫头鹰(质量) + 渡鸦(AI Coding) + 鸬鹚(数据)")

    # 构造 EventStore,记录本次 review 的事件流 (供 STATUS 聚合)
    from event_store import EventStore
    import time as _time
    import uuid as _uuid
    review_id = f"rev_{int(_time.time())}_{_uuid.uuid4().hex[:8]}"
    evt = EventStore(workspace=workspace, review_id=review_id)
    evt.append("review_started", {
        "prd_files": prd_files,
        "wiki_pages_count": len(wiki_pages),
        "mode": "cli",
    })
    evt.append("workers_started", {"mode": "cli"})

    def _on_worker_done(dim, r):
        """Worker 完成回调: 把 items_count / error / telemetry 落盘。"""
        if isinstance(r, dict):
            telemetry = r.get("telemetry") or {}
            evt.append("worker_done", {
                "dim": dim,
                "items_count": len(r.get("items", [])),
                "error": str(r.get("error", ""))[:200] if r.get("error") else None,
                "empty_retry_used": telemetry.get("empty_retry_used"),
                "turns_used": telemetry.get("turns_used"),
                "duration_ms": telemetry.get("duration_ms"),
                "cost_usd": telemetry.get("cost_usd") or r.get("cost_usd"),
            })
        else:
            evt.append("worker_done", {"dim": dim, "items_count": 0, "error": str(r)[:200]})

    # 用 adapter client 调 workers（并行 async）
    import asyncio
    # Windows 兼容：避免 asyncio 在 Windows 上的 ProactorEventLoop 问题
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    t_start = _time.time()
    result = asyncio.run(parallel_review(client, prd_content, wiki_pages, MODEL_TIERS,
                                          wiki_path=wiki_path, diff_context=diff_context,
                                          on_worker_done=_on_worker_done))
    elapsed = _time.time() - t_start
    print(f"  [并行评审] 4 个 worker 并行完成，耗时 {elapsed:.1f}s")
    evt.append("checkpoint", {
        "workers_done": len(result.get("workers", [])),
        "items_count": len(result.get("merged_items", [])),
    })

    # T3 2026-04-24: funnel stage N0/N1 (CLI path) — 失败不阻塞
    _funnel_stages = {}
    try:
        from review.funnel_telemetry import compute_worker_raw_stage, compute_dedup_stage
        _worker_raw = compute_worker_raw_stage(result.get("workers", []))
        evt.append("funnel_stage_worker_raw", _worker_raw)
        _funnel_stages["N0_worker_raw"] = _worker_raw["count"]
        _after_dedup = compute_dedup_stage(_worker_raw["count"], result.get("merged_items", []))
        evt.append("funnel_stage_after_dedup", _after_dedup)
        _funnel_stages["N1_after_dedup"] = _after_dedup["count"]
    except Exception as _fn_err:
        print(f"  [funnel] N0/N1 emit 失败不阻塞: {_fn_err}")

    # 打印 worker 结果
    for w in result["workers"]:
        if "error" in w and w["error"]:
            print(f"  [{w['dimension_name']}] 失败: {w['error'][:60]}")
        else:
            print(f"  [{w['dimension_name']}] 发现 {len(w['items'])} 条改进项")

    # 依据验证
    # 2026-04-26 Sprint #6 step 2: 注入 client + wiki_pages 启用 LLM NLI 升级.
    # client + wiki_pages 都从 main 顶层传到本函数 scope, 直接用. 失败 NLI 自动 skip 主流程不破.
    from parallel_review import summarize_verification
    verified = verify_evidence(result["merged_items"], workspace,
                               client=client, wiki_pages=wiki_pages)
    retracted = [i for i in verified if i.get("status") == "RETRACTED"]
    verification_summary = summarize_verification(verified)

    # T3 2026-04-24: funnel stage N2 (after_evidence_verify)
    try:
        from review.funnel_telemetry import compute_evidence_verify_stage, get_wiki_telemetry
        wiki_tele = get_wiki_telemetry(workspace)
        _after_ev = compute_evidence_verify_stage(verification_summary, wiki_tele)
        evt.append("funnel_stage_after_evidence_verify", _after_ev)
        _funnel_stages["N2_after_evidence_verify"] = _after_ev["count"]
    except Exception as _fn_err2:
        print(f"  [funnel] N2 emit 失败不阻塞: {_fn_err2}")
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

    evt.append("review_completed", {
        "items_count": len(valid_items),
        "duration_ms": int(elapsed * 1000),
    })

    return {
        "items": valid_items,
        "retracted": retracted,
        "verification_summary": verification_summary,
        "peck_score": peck,
        "usage": result["total_usage"],
        "event_store": evt,  # 供 run_goshawk_review 继续追加 final_reviewer_* 事件
        "_funnel_stages": _funnel_stages,  # T3: 给 run_goshawk_review 继续填 N3
    }


# ============================================================
# Phase 2.5: 苍鹰交叉校验
# ============================================================

@log_agent_call("苍鹰 meta 评审")
def run_goshawk_review(client, workspace, wiki_path, parallel_result, model, system_blocks, messages, session_file, turn_cb, prd_content, wiki_pages):
    """Phase 2.5: 苍鹰交叉校验。prd_content / wiki_pages 由 main() 预读传入。"""
    # 修法 C (2026-04-26): 默认走 advisor_review_default → 内部 advisor_review_with_resampling
    # 让 sprint #2 (LLM-as-Verifier 多次重采样) + DAR (少数派保留) + sprint #6 (NLI) 真在
    # production 跑. PM 可 PECKER_GOSHAWK_RESAMPLE=1 紧急回退老单次行为.
    from goshawk_advisor import advisor_review_default, apply_advisor_result, format_advisor_report, summarize_resample_telemetry
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

    evt = parallel_result.get("event_store") if isinstance(parallel_result, dict) else None
    if evt:
        evt.append("final_reviewer_started", {"items_count": len(parallel_result.get("items", []))})

    try:
        goshawk_result = advisor_review_default(
            client, prd_content, parallel_result["items"], wiki_pages,
        )
        elapsed = _time.time() - t_start

        updated_items = apply_advisor_result(parallel_result["items"], goshawk_result)
        parallel_result["items"] = updated_items
        parallel_result["goshawk"] = goshawk_result

        # T3 2026-04-24: funnel stage N3 (after_goshawk) + summary (CLI 无 PM, N4 留空)
        try:
            from review.funnel_telemetry import compute_goshawk_stage, compute_funnel_summary
            stages = parallel_result.setdefault("_funnel_stages", {})
            _after_g = compute_goshawk_stage(updated_items, goshawk_result)
            if evt:
                evt.append("funnel_stage_after_goshawk", _after_g)
            stages["N3_after_goshawk"] = _after_g["count"]
            # CLI 没 Phase 3, summary 直接发
            _summary = compute_funnel_summary(stages)
            if evt:
                evt.append("funnel_summary", _summary)
        except Exception as _fn_err3:
            print(f"  [funnel] N3/summary emit 失败不阻塞: {_fn_err3}")

        fp_count = len(goshawk_result.get("flagged_as_false_positive", []))
        add_count = len(goshawk_result.get("additional_findings", []))
        conf_count = len(goshawk_result.get("conflict_resolutions", []))
        print(f"\n  苍鹰审核完毕 ({elapsed:.1f}s)：误报 {fp_count}，补充 {add_count}，调解 {conf_count}，"
              f"信心度 {goshawk_result.get('confidence', 0):.0%}")

        if evt:
            _final_evt = {
                "false_positive": fp_count,
                "additional": add_count,
                "verdict": goshawk_result.get("verdict", "UNKNOWN"),
                "confidence": goshawk_result.get("confidence", 0.0),
                "empty_retry_used": goshawk_result.get("empty_retry_used", False),
            }
            # 修法 C: 多轮采样时附带 DAR retention_kind 分布 + n_samples (单轮时为空 dict)
            _final_evt.update(summarize_resample_telemetry(goshawk_result))
            evt.append("final_reviewer_done", _final_evt)

        goshawk_report = format_advisor_report(goshawk_result)
        messages.append({"role": "user", "content": f"苍鹰交叉校验已完成：\n{goshawk_report}\n\n请结合苍鹰的审核意见，进入 Phase 3 交互确认。"})
        from security import save_session_turn
        messages = tool_loop(client, model, system_blocks, messages, workspace, turn_callback=turn_cb)
        save_session_turn(session_file, messages, {"model": model, "turn": "goshawk"})
    except Exception as e:
        print(f"  苍鹰交叉校验失败（继续评审）: {str(e)[:80]}")
        if evt:
            evt.append("final_reviewer_done", {"error": str(e)[:200]})

    return messages


# ============================================================
# System Prompt 构建(已抽至 router.py,保留旧名兼容)
# ============================================================

from router import build_system_blocks


# ============================================================
# Wiki 同步(已抽至 content_loader.py,保留旧名兼容)
# ============================================================

from content_loader import sanitize_branch_name, wiki_pull



# ============================================================
# 主流程
# ============================================================

def main():
    _init_config()

    from session_setup import (
        build_parser, apply_noninteractive_defaults,
        run_merge_mode, resolve_messages, build_initial_message,
    )

    args = build_parser().parse_args()
    apply_noninteractive_defaults(args, stdin_is_tty=sys.stdin.isatty())

    # 合并模式 (--merge) — 独立流程,早返
    if args.merge:
        run_merge_mode(args)
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

    # Plan 4 Layer 3: 信鸽反馈自检 — 注册的下游仓有新 commit 就提醒 PM
    check_pending_feedback(non_interactive=_is_noninteractive())

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
    messages = resolve_messages(args.resume, resumed)

    # 首轮消息
    date_str = datetime.date.today().strftime("%Y-%m-%d")
    safe_reviewer = sanitize_branch_name(args.reviewer)
    safe_prd = sanitize_branch_name(prd_name)
    branch_name = f"review/{safe_reviewer}/{safe_prd}/{date_str}"

    if messages is None:
        messages = [{
            "role": "user",
            "content": build_initial_message(date_str, args.reviewer, prd_name,
                                             workspace, branch_name),
        }]

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