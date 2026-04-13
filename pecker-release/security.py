"""
啄木鸟 PRD 评审 Agent -- 安全与体验模块
文件权限围栏、Bash 白名单、Session 持久化、Git Worktree、飞书通知、安全执行包装
"""

import json
import os
import subprocess
import time
import urllib.request
import urllib.error

from tools import execute_tool


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
    if not rel.endswith("/"):
        rel_with_slash = rel + "/"

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
    "rm -rf", "rm -r", "git push -f", "git push --force",
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


def save_session_turn(session_file, messages, response_meta):
    """
    每轮追加一行 JSON 到 session 文件（只存最后 2 条消息，不存完整 messages）
    messages: 当前完整消息列表
    response_meta: 本轮响应的元信息（model, usage, stop_reason 等）
    """
    os.makedirs(os.path.dirname(session_file), exist_ok=True)

    # 只存本轮新增的消息（最后 2 条），不存完整 messages
    recent = messages[-2:] if len(messages) >= 2 else messages

    turn = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "turn_index": len(messages),
        "last_role": messages[-1]["role"] if messages else None,
        "response_meta": response_meta,
        "messages": recent,
    }

    with open(session_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(turn, ensure_ascii=False) + "\n")


def resume_session(session_dir, prd_name):
    """
    检查是否有未完成的 session
    返回 (messages, metadata) 或 None
    """
    sessions_path = os.path.join(session_dir, ".sessions")
    if not os.path.isdir(sessions_path):
        return None

    # 查找包含该 prd_name 的 session 文件
    safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in prd_name)
    for fname in os.listdir(sessions_path):
        if safe_name in fname and fname.endswith(".jsonl"):
            fpath = os.path.join(sessions_path, fname)
            # 读取最后一行获取最新状态
            last_line = None
            with open(fpath, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        last_line = line

            if last_line:
                try:
                    turn = json.loads(last_line)
                    return turn.get("messages"), turn.get("response_meta")
                except json.JSONDecodeError:
                    continue
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

    # 基于 main 创建新分支并关联 worktree
    cmd = f'git worktree add -b "{branch_name}" "{worktree_dir}" main'
    result = subprocess.run(
        cmd, shell=True, capture_output=True, text=True,
        timeout=30, cwd=workspace,
    )
    if result.returncode != 0:
        raise RuntimeError(f"创建 worktree 失败: {result.stderr.strip()}")

    return worktree_dir


def cleanup_worktree(worktree_path):
    """移除 worktree"""
    # 先找到主仓库目录（worktree 的上两级 .worktrees 的父目录）
    parent = os.path.dirname(os.path.dirname(worktree_path))
    cmd = f'git worktree remove "{worktree_path}" --force'
    result = subprocess.run(
        cmd, shell=True, capture_output=True, text=True,
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
        print(f"[warn] 飞书通知发送失败: {e}")


# ============================================================
# 6. 安全工具执行包装器
# ============================================================

def safe_execute_tool(name, inputs, workspace):
    """
    包装 tools.execute_tool，执行前检查权限
    被拒绝的操作返回 "[blocked] 原因"
    需要确认的操作交互等待用户输入
    """
    # 文件类工具：检查文件权限
    if name in ("read_file", "write_file"):
        path = inputs.get("path", "")
        operation = "write" if name == "write_file" else "read"
        allowed, reason = check_file_permission(path, operation, workspace)
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
            answer = input("  是否继续？(y/n): ").strip().lower()
            if answer != "y":
                return "[blocked] 用户拒绝执行"

    # 权限检查通过，执行工具
    return execute_tool(name, inputs, workspace)
