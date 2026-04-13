"""
工具定义和执行 -- 啄木鸟 PRD 评审 Agent 的工具层
"""

import os
import subprocess
import glob as glob_module

# ============================================================
# 工具 Schema（供 Messages API 使用）
# ============================================================

TOOL_SCHEMAS = [
    {
        "name": "read_file",
        "description": "读取文件内容。支持文本文件、Markdown 等。",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "文件路径（相对于工作目录）"},
                "offset": {"type": "integer", "description": "起始行号（从 0 开始），默认 0"},
                "limit": {"type": "integer", "description": "读取行数，默认全部"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": "写入文件内容。目录不存在会自动创建。",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "文件路径（相对于工作目录）"},
                "content": {"type": "string", "description": "要写入的完整内容"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "list_directory",
        "description": "列出目录内容，返回文件和子目录列表。",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "目录路径，默认为工作目录"},
                "pattern": {"type": "string", "description": "glob 匹配模式，如 '*.md'"},
                "recursive": {"type": "boolean", "description": "是否递归，默认 false"},
            },
        },
    },
    {
        "name": "search_files",
        "description": "在文件中搜索文本内容（类似 grep），返回匹配的行。",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "搜索的文本或正则表达式"},
                "path": {"type": "string", "description": "搜索的目录或文件，默认工作目录"},
                "file_pattern": {"type": "string", "description": "文件名过滤，如 '*.md'，默认搜索所有文件"},
                "max_results": {"type": "integer", "description": "最大返回条数，默认 30"},
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "run_bash",
        "description": "执行 bash 命令。仅限 git 相关操作。",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "要执行的命令"},
            },
            "required": ["command"],
        },
    },
]


# ============================================================
# 工具执行
# ============================================================

def execute_tool(name, inputs, workspace):
    """
    执行工具并返回结果字符串
    workspace: 工作目录的绝对路径
    """
    try:
        if name == "read_file":
            return _read_file(inputs, workspace)
        elif name == "write_file":
            return _write_file(inputs, workspace)
        elif name == "list_directory":
            return _list_directory(inputs, workspace)
        elif name == "search_files":
            return _search_files(inputs, workspace)
        elif name == "run_bash":
            return _run_bash(inputs, workspace)
        else:
            return f"[error] 未知工具: {name}"
    except Exception as e:
        return f"[error] {name} 执行失败: {e}"


def _resolve_path(path, workspace):
    """解析路径，确保不会越权访问工作目录之外"""
    if not path:
        return workspace
    full = os.path.normpath(os.path.join(workspace, path))
    if not (full + os.sep).startswith(os.path.normpath(workspace) + os.sep):
        raise PermissionError(f"路径越权: {path}")
    return full


def _read_file(inputs, workspace):
    """读取文件内容"""
    path = _resolve_path(inputs["path"], workspace)
    if not os.path.exists(path):
        return f"[error] 文件不存在: {inputs['path']}"
    if not os.path.isfile(path):
        return f"[error] 不是文件: {inputs['path']}"

    with open(path, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()

    offset = inputs.get("offset", 0)
    limit = inputs.get("limit")
    if limit:
        lines = lines[offset:offset + limit]
    elif offset:
        lines = lines[offset:]

    # 加行号
    numbered = []
    for i, line in enumerate(lines, start=offset + 1):
        numbered.append(f"{i}\t{line.rstrip()}")

    result = "\n".join(numbered)
    if len(result) > 50000:
        result = result[:50000] + "\n...[截断，文件过大，请用 offset/limit 分段读取]"
    return result


def _write_file(inputs, workspace):
    """写入文件"""
    path = _resolve_path(inputs["path"], workspace)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(inputs["content"])
    return f"已写入: {inputs['path']} ({len(inputs['content'])} 字符)"


def _list_directory(inputs, workspace):
    """列出目录内容"""
    path = _resolve_path(inputs.get("path", ""), workspace)
    if not os.path.isdir(path):
        return f"[error] 目录不存在: {inputs.get('path', '.')}"

    pattern = inputs.get("pattern", "*")
    recursive = inputs.get("recursive", False)

    if recursive:
        full_pattern = os.path.join(path, "**", pattern)
        matches = glob_module.glob(full_pattern, recursive=True)
    else:
        full_pattern = os.path.join(path, pattern)
        matches = glob_module.glob(full_pattern)

    # 转为相对路径
    rel_paths = []
    for m in sorted(matches):
        rel = os.path.relpath(m, workspace)
        suffix = "/" if os.path.isdir(m) else ""
        rel_paths.append(rel + suffix)

    if not rel_paths:
        return "(空目录或无匹配)"
    return "\n".join(rel_paths[:200])


def _search_files(inputs, workspace):
    """搜索文件内容"""
    pattern = inputs["pattern"]
    path = _resolve_path(inputs.get("path", ""), workspace)
    file_pattern = inputs.get("file_pattern", "*")
    max_results = inputs.get("max_results", 30)

    # 用 grep 或 findstr 搜索
    try:
        cmd = [
            "grep", "-rn", "--include", file_pattern,
            "-m", str(max_results), pattern, path
        ]
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=15,
            cwd=workspace,
        )
        output = result.stdout.strip()
        if not output:
            return f"(无匹配: '{pattern}' in {file_pattern})"

        # 转为相对路径
        lines = []
        for line in output.split("\n")[:max_results]:
            line = line.replace(workspace + os.sep, "").replace(workspace + "/", "")
            lines.append(line)
        return "\n".join(lines)
    except subprocess.TimeoutExpired:
        return "[error] 搜索超时"
    except FileNotFoundError:
        # Windows 没有 grep，用 Python 实现
        return _search_files_python(pattern, path, file_pattern, max_results, workspace)


def _search_files_python(pattern, search_path, file_pattern, max_results, workspace):
    """纯 Python 搜索回退（Windows 兼容）"""
    import re
    try:
        regex = re.compile(pattern, re.IGNORECASE)
    except re.error:
        regex = re.compile(re.escape(pattern), re.IGNORECASE)

    matches = []
    for root, _, files in os.walk(search_path):
        for fname in files:
            # 简单的 pattern 匹配
            if file_pattern != "*" and not fname.endswith(file_pattern.lstrip("*")):
                continue
            fpath = os.path.join(root, fname)
            try:
                with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                    for i, line in enumerate(f, 1):
                        if regex.search(line):
                            rel = os.path.relpath(fpath, workspace)
                            matches.append(f"{rel}:{i}: {line.strip()}")
                            if len(matches) >= max_results:
                                return "\n".join(matches)
            except (OSError, UnicodeDecodeError):
                continue

    return "\n".join(matches) if matches else f"(无匹配: '{pattern}')"


def _run_bash(inputs, workspace):
    """执行 bash 命令"""
    command = inputs["command"]

    try:
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True,
            timeout=120, cwd=workspace,
        )
        output = ""
        if result.stdout:
            output += result.stdout
        if result.stderr:
            output += ("\n" if output else "") + result.stderr
        if result.returncode != 0:
            output += f"\n[exit code: {result.returncode}]"
        return output.strip() or "(无输出)"
    except subprocess.TimeoutExpired:
        return "[error] 命令超时 (120s)"
