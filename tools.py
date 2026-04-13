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
    except PermissionError as e:
        return f"[blocked] {name} 权限不足: {e}"
    except Exception as e:
        from exceptions import ToolError
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
    """写入文件，wiki/ 目录下的写入加锁"""
    path = _resolve_path(inputs["path"], workspace)

    # 检测是否写入 wiki 目录
    rel = os.path.relpath(path, workspace).replace("\\", "/")
    is_wiki = rel.startswith("wiki/")

    if is_wiki:
        from wiki_lock import wiki_write_lock
        # 从 path 反推 wiki 目录
        wiki_dir = os.path.dirname(path)
        while os.path.basename(wiki_dir) != "wiki" and wiki_dir != os.path.dirname(wiki_dir):
            wiki_dir = os.path.dirname(wiki_dir)
        if os.path.basename(wiki_dir) != "wiki":
            wiki_dir = os.path.join(workspace, "wiki")

        with wiki_write_lock(wiki_dir):
            return _write_file_impl(path, inputs, is_log=os.path.basename(path) == "log.md")
    else:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(inputs["content"])
        return f"已写入: {inputs['path']} ({len(inputs['content'])} 字符)"


def _write_file_impl(path, inputs, is_log=False):
    """实际写入逻辑（在锁保护下执行）"""
    import re
    os.makedirs(os.path.dirname(path), exist_ok=True)

    if is_log and os.path.exists(path):
        # log.md 特殊处理：只追加新的日志条目，不覆盖
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            existing = f.read()

        new_content = inputs["content"]
        # 提取新内容中的日志条目（## [xxxx] 开头的段落）
        new_sections = re.findall(r'(## \[.+?\].*?)(?=\n## \[|\Z)', new_content, re.DOTALL)

        if new_sections:
            # 只追加 existing 中不存在的条目
            appended = []
            for section in new_sections:
                # 用第一行做去重判断
                first_line = section.strip().split('\n')[0]
                if first_line not in existing:
                    appended.append(section.strip())

            if appended:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(existing.rstrip() + "\n\n" + "\n\n".join(appended) + "\n")
                return f"已追加: {inputs['path']} ({len(appended)} 条新记录)"
            return f"已跳过: {inputs['path']} (无新记录需追加)"
        else:
            # 没有日志格式的内容，直接覆盖
            with open(path, "w", encoding="utf-8") as f:
                f.write(new_content)
            return f"已写入: {inputs['path']} ({len(new_content)} 字符)"
    else:
        with open(path, "w", encoding="utf-8") as f:
            f.write(inputs["content"])
        return f"已写入: {inputs['path']} ({len(inputs['content'])} 字符)"


def _is_sensitive_path(rel_path):
    """检查路径是否命中敏感文件/目录黑名单"""
    from security import SENSITIVE_FILES, SENSITIVE_PATTERNS
    basename = os.path.basename(rel_path)
    if basename in SENSITIVE_FILES:
        return True
    normalized = rel_path.replace("\\", "/")
    for pattern in SENSITIVE_PATTERNS:
        if pattern in normalized:
            return True
    return False


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

    # 转为相对路径，过滤敏感路径
    rel_paths = []
    for m in sorted(matches):
        rel = os.path.relpath(m, workspace)
        if _is_sensitive_path(rel):
            continue
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

        # 转为相对路径，过滤敏感路径
        lines = []
        for line in output.split("\n")[:max_results]:
            line = line.replace(workspace + os.sep, "").replace(workspace + "/", "")
            # 取文件路径部分检查敏感性
            file_part = line.split(":")[0] if ":" in line else line
            if _is_sensitive_path(file_part):
                continue
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
        # 跳过敏感目录
        rel_root = os.path.relpath(root, workspace)
        if _is_sensitive_path(rel_root):
            continue
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
