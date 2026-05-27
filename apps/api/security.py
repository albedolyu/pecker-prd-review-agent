"""
Pecker PRD 评审 Agent -- 安全与体验模块
文件权限围栏、Bash 白名单、Session 持久化、Git Worktree、飞书通知、安全执行包装

C2 (Phase 4): 引入 PermissionMode 枚举,借鉴 Claude Code 的四态模式。
主要用于 tool_loop 场景 — Worker 本来就只拿 submit_review_items 一个工具
(parallel_review.py:628),所以 PermissionMode 主要约束主 Agent 的 tool_loop。
"""

import enum
import json
import os
import subprocess
import time
import urllib.request
import urllib.error

from tools import execute_tool, get_tool, is_read_only_tool
from logger import get_logger

log = get_logger("security")


# ============================================================
# 0. PermissionMode 权限模式(C2)
# ============================================================

class PermissionMode(enum.Enum):
    """C2: 工具执行的权限模式(借鉴 Claude Code 的 permission-mode)

    - STRICT:  最严,所有写工具+需确认命令都直接拒绝(审阅只读场景)
    - NORMAL:  默认,按 DIR_PERMISSIONS + Bash 白名单 + 确认链正常走
    - AUTO:    CI/CD 无人值守,wiki push 等自动确认(原 PECKER_AUTO_CONFIRM 语义)
    - PLAN:    只读探索模式,只允许 is_read_only=True 的工具,其他全拒
    """
    STRICT = "strict"
    NORMAL = "normal"
    AUTO = "auto"
    PLAN = "plan"

    @classmethod
    def from_env(cls):
        """从环境变量 PECKER_PERMISSION_MODE 读取,默认 NORMAL"""
        val = os.environ.get("PECKER_PERMISSION_MODE", "").lower()
        for m in cls:
            if m.value == val:
                return m
        return cls.NORMAL


def get_current_permission_mode():
    """获取当前权限模式(供 safe_execute_tool 消费)"""
    return PermissionMode.from_env()


# ============================================================
# 1. 文件权限围栏
# ============================================================

# 目录权限定义（路径前缀 -> 读写权限）
DIR_PERMISSIONS = {
    "raw/":          {"read": True,  "write": False},
    "prd/":          {"read": True,  "write": False},
    "wiki/":         {"read": True,  "write": True},
    "output/":       {"read": True,  "write": True},
    "review-rules/": {"read": True,  "write": False},
}

# 敏感文件黑名单（即使在允许读取的目录中也不可读）
SENSITIVE_FILES = {".env", ".env.example", "achievements.json"}
SENSITIVE_PATTERNS = [".sessions/", "__pycache__/", ".git/"]


def check_file_permission(path, operation, workspace):
    """
    检查文件操作权限
    path: 文件路径（相对或绝对）
    operation: "read" 或 "write"
    workspace: 工作目录绝对路径
    返回 (allowed, reason)
    """
    # 统一为相对路径做前缀匹配
    if os.path.isabs(path):
        norm = os.path.normpath(path)
        ws = os.path.normpath(workspace)
        if not (norm + os.sep).startswith(ws + os.sep):
            return False, f"路径在工作目录之外: {path}"
        rel = os.path.relpath(norm, ws)
    else:
        rel = path

    # 统一用 / 分隔
    rel = rel.replace("\\", "/")
    rel_with_slash = rel if rel.endswith("/") else rel + "/"

    # 敏感文件检查（无论在哪个目录都禁止读取）
    basename = os.path.basename(rel)
    if basename in SENSITIVE_FILES:
        return False, f"禁止访问敏感文件: {basename}"
    for pattern in SENSITIVE_PATTERNS:
        if pattern in rel:
            return False, f"禁止访问敏感路径: {pattern}"

    # 逐个前缀匹配
    for prefix, perms in DIR_PERMISSIONS.items():
        if rel.startswith(prefix) or rel_with_slash.startswith(prefix):
            if perms.get(operation, False):
                return True, f"允许 {operation}: {prefix} 目录"
            else:
                return False, f"禁止 {operation}: {prefix} 目录为{'只读' if operation == 'write' else '不可访问'}"

    # 不在已知目录中：允许读，禁止写
    if operation == "read":
        return True, "未知目录，默认允许读取"
    return False, f"禁止写入未知目录: {rel}"


# ============================================================
# 2. Bash 命令白名单
# ============================================================

ALLOWED_BASH_PREFIXES = [
    "git status", "git add", "git commit", "git push",
    "git checkout", "git branch", "git log", "git diff",
    "git worktree", "git stash",
    "pwd",
]

BLOCKED_PATTERNS = [
    "rm -rf", "rm -r", "git push -f", "git push --force", "git push --force-with-lease",
    "git reset --hard", "git clean",
    "curl", "wget",
    "pip install", "npm install",
]

CONFIRM_REQUIRED = ["git push", "git checkout -b"]


def check_bash_permission(command):
    """
    检查 bash 命令是否允许执行
    返回 (verdict, reason)
    verdict: "allow" | "deny" | "confirm"
    """
    cmd = command.strip()

    # 检测命令链接/注入（shell chaining，参考 CC bashSecurity.ts 23 项检查）
    CHAIN_PATTERNS = ["&&", "||", ";", "|", "\n", ">", "<", "&"]
    for pattern in CHAIN_PATTERNS:
        if pattern in cmd:
            return "deny", f"命令包含链接操作符 '{pattern}'，禁止执行（防注入）"

    # Shell 注入模式检测（CC bashSecurity.ts — 命令替换、变量展开等）
    INJECTION_PATTERNS = [
        ("$(", "命令替换 $(...)"),
        ("${", "变量展开 ${...}"),
        ("`", "反引号命令替换"),
        ("\\x", "十六进制转义"),
        ("\x00", "空字节注入"),
    ]
    # 大括号展开只在含逗号时危险（如 {a,b}）
    import re as _re_bash
    if _re_bash.search(r'\{[^}]*,[^}]*\}', cmd):
        return "deny", "检测到 shell 大括号展开模式 {a,b}"
    for pattern, desc in INJECTION_PATTERNS:
        if pattern in cmd:
            return "deny", f"检测到 shell 注入模式 ({desc})"

    # Unicode 隐藏字符检测（零宽字符可隐藏恶意命令）
    import unicodedata
    for i, ch in enumerate(cmd):
        cat = unicodedata.category(ch)
        if cat in ("Cf", "Co", "Cn") or ch in ("\u200b", "\u200c", "\u200d", "\ufeff"):
            return "deny", f"命令包含隐藏 Unicode 字符 (U+{ord(ch):04X} {cat}) 在位置 {i}"

    # IFS 注入检测
    if "IFS" in cmd:
        return "deny", "命令包含 IFS 修改（可能导致命令解析异常）"

    # 先检查黑名单
    for pattern in BLOCKED_PATTERNS:
        if pattern in cmd:
            return "deny", f"命令包含被禁止的操作: {pattern}"

    # 再检查需要确认的命令
    for pattern in CONFIRM_REQUIRED:
        if cmd.startswith(pattern):
            return "confirm", f"命令需要用户确认: {pattern}"

    # 最后检查白名单
    for prefix in ALLOWED_BASH_PREFIXES:
        if cmd.startswith(prefix):
            return "allow", f"命令在白名单中: {prefix}"

    return "deny", f"命令不在白名单中: {cmd}"


# ============================================================
# 3. Session 持久化与恢复
# ============================================================

def get_session_path(session_dir, prd_name, reviewer):
    """生成 session 文件路径"""
    # 文件名：reviewer_prd_name.jsonl
    safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in prd_name)
    safe_reviewer = "".join(c if c.isalnum() or c in "-_" else "_" for c in reviewer)
    filename = f"{safe_reviewer}_{safe_name}.jsonl"
    return os.path.join(session_dir, ".sessions", filename)


# 模块级变量，跟踪上次保存时的消息数量
_last_saved_count = {}  # session_file -> last saved message count


def save_session_turn(session_file, messages, response_meta):
    """
    每轮追加新增消息到 session 文件（增量保存，不丢失中间消息）
    """
    os.makedirs(os.path.dirname(session_file), exist_ok=True)

    # 计算本次新增的消息
    norm_key = os.path.normpath(session_file)
    last_count = _last_saved_count.get(norm_key, 0)
    new_messages = messages[last_count:]

    if not new_messages:
        return  # 没有新消息，跳过

    turn = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "turn_index": len(messages),
        "total_messages": len(messages),
        "last_role": messages[-1]["role"] if messages else None,
        "response_meta": response_meta,
        "messages": new_messages,
    }

    with open(session_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(turn, ensure_ascii=False) + "\n")

    _last_saved_count[norm_key] = len(messages)


def resume_session(session_dir, prd_name):
    """
    从 JSONL 增量记录重建完整 messages
    遍历所有行，按顺序拼接每轮的增量消息
    返回 (messages, metadata) 或 None
    metadata 包含 response_meta + 恢复统计信息
    """
    sessions_path = os.path.join(session_dir, ".sessions")
    if not os.path.isdir(sessions_path):
        return None

    safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in prd_name)
    for fname in os.listdir(sessions_path):
        # 精确匹配 prd_name 部分（格式：reviewer_prdname.jsonl）
        fname_without_ext = fname.replace(".jsonl", "")
        if fname.endswith(".jsonl") and fname_without_ext.endswith(f"_{safe_name}"):
            fpath = os.path.join(sessions_path, fname)
            all_messages = []
            last_meta = None
            first_timestamp = None
            last_timestamp = None
            turn_count = 0
            with open(fpath, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        turn = json.loads(line)
                        recent = turn.get("messages", [])
                        last_meta = turn.get("response_meta")
                        ts = turn.get("timestamp")
                        if first_timestamp is None:
                            first_timestamp = ts
                        last_timestamp = ts
                        turn_count += 1
                        all_messages.extend(recent)
                    except json.JSONDecodeError:
                        continue

            if all_messages:
                _last_saved_count[os.path.normpath(fpath)] = len(all_messages)
                meta = {
                    "response_meta": last_meta,
                    "first_timestamp": first_timestamp,
                    "last_timestamp": last_timestamp,
                    "turn_count": turn_count,
                    "message_count": len(all_messages),
                    "session_file": fpath,
                }
                return all_messages, meta
    return None


# ============================================================
# 4. Git Worktree 管理
# ============================================================

def create_worktree(workspace, reviewer, prd_name):
    """
    创建 git worktree 用于隔离评审
    返回 worktree 路径
    """
    safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in prd_name)
    safe_reviewer = "".join(c if c.isalnum() or c in "-_" else "_" for c in reviewer)
    branch_name = f"review/{safe_reviewer}/{safe_name}"
    worktree_dir = os.path.join(workspace, ".worktrees", f"{safe_reviewer}_{safe_name}")

    if os.path.isdir(worktree_dir):
        return worktree_dir

    os.makedirs(os.path.dirname(worktree_dir), exist_ok=True)

    # 基于 main 创建新分支并关联 worktree（用列表参数防止命令注入）
    result = subprocess.run(
        ["git", "worktree", "add", "-b", branch_name, worktree_dir, "main"],
        capture_output=True, text=True,
        timeout=30, cwd=workspace,
    )
    if result.returncode != 0:
        raise RuntimeError(f"创建 worktree 失败: {result.stderr.strip()}")

    return worktree_dir


def cleanup_worktree(worktree_path):
    """移除 worktree"""
    # 先找到主仓库目录（worktree 的上两级 .worktrees 的父目录）
    parent = os.path.dirname(os.path.dirname(worktree_path))
    result = subprocess.run(
        ["git", "worktree", "remove", worktree_path, "--force"],
        capture_output=True, text=True,
        timeout=30, cwd=parent,
    )
    if result.returncode != 0:
        raise RuntimeError(f"移除 worktree 失败: {result.stderr.strip()}")


# ============================================================
# 5. 飞书通知
# ============================================================

def notify_feishu(webhook_url, title, content):
    """
    发送飞书 interactive card 消息
    webhook_url 为空时静默跳过
    """
    if not webhook_url:
        return

    payload = {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title": {"tag": "plain_text", "content": title},
                "template": "blue",
            },
            "elements": [
                {
                    "tag": "markdown",
                    "content": content,
                }
            ],
        },
    }

    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        webhook_url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp.read()
    except Exception as e:
        log.warning(f"飞书通知发送失败: {e}")


# ============================================================
# 5.5 Unicode 消毒（参考 CC sanitization.ts）
# ============================================================

def sanitize_unicode(text):
    """移除隐藏格式字符，防止通过不可见字符注入指令"""
    import unicodedata
    if not isinstance(text, str):
        return text
    # NFKC 归一化
    text = unicodedata.normalize("NFKC", text)
    # 移除格式字符（Cf）、私有区（Co）、未分配（Cn）
    return "".join(
        c for c in text
        if unicodedata.category(c) not in ("Cf", "Co", "Cn")
    )


# ============================================================
# 6. 安全工具执行包装器
# ============================================================

def safe_execute_tool(name, inputs, workspace):
    """
    包装 tools.execute_tool，执行前检查权限
    被拒绝的操作返回 "[blocked] 原因"
    需要确认的操作交互等待用户输入

    v1.2: 用 tools.get_tool(name) 查询 AgentTool 契约做决策,而不再内嵌工具名白名单
    C2: 增加 PermissionMode 检查 — PLAN 模式只允许只读工具,STRICT 拒绝所有写工具
    """
    # 未注册的工具直接拒绝(契约化防御)
    tool_def = get_tool(name)
    if tool_def is None:
        return f"[blocked] 未注册的工具: {name}"

    # C2: PermissionMode 前置检查
    mode = get_current_permission_mode()
    if mode == PermissionMode.PLAN and not tool_def.is_read_only:
        return f"[blocked] plan 模式:工具 {name} 非只读,本模式仅允许 is_read_only=True 的工具"
    if mode == PermissionMode.STRICT and not tool_def.is_read_only:
        return f"[blocked] strict 模式:工具 {name} 非只读,本模式拒绝所有写操作"

    # Unicode 消毒：写入类工具的文本内容清理隐藏字符(非只读工具统一做)
    if not tool_def.is_read_only and "content" in inputs:
        inputs = {**inputs, "content": sanitize_unicode(inputs["content"])}
    # 文件类工具：检查文件权限
    if name in ("read_file", "write_file"):
        path = inputs.get("path", "")
        operation = "write" if not tool_def.is_read_only else "read"
        allowed, reason = check_file_permission(path, operation, workspace)
        if not allowed:
            return f"[blocked] {reason}"

    # 搜索和目录列举：过滤敏感路径
    if name in ("search_files", "list_directory"):
        path = inputs.get("path", "")
        allowed, reason = check_file_permission(path or ".", "read", workspace)
        if not allowed:
            return f"[blocked] {reason}"

    # Bash 工具：检查命令权限
    if name == "run_bash":
        command = inputs.get("command", "")
        verdict, reason = check_bash_permission(command)
        if verdict == "deny":
            return f"[blocked] {reason}"
        if verdict == "confirm":
            print(f"\n⚠ 需要确认执行: {command}")
            print(f"  原因: {reason}")
            # C2: AUTO 模式无需人工确认(CI/CD 无人值守),直接放行
            if mode == PermissionMode.AUTO:
                log.info(f"auto 模式:自动确认执行 {command}")
            else:
                # 非交互模式:保守默认拒绝,避免 CI 里执行需确认的命令
                if os.environ.get("PECKER_NONINTERACTIVE", "").lower() in ("1", "true", "yes"):
                    return "[blocked] 非交互模式下拒绝执行需确认的命令(设置 PECKER_PERMISSION_MODE=auto 可强制通过)"
                try:
                    answer = input("  是否继续？(y/n): ").strip().lower()
                except (EOFError, KeyboardInterrupt):
                    answer = "n"
                if answer != "y":
                    return "[blocked] 用户拒绝执行"

    # 权限检查通过，执行工具
    return execute_tool(name, inputs, workspace)
