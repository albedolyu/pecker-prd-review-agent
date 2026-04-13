"""
上下文管理 -- 控制 Messages API 的 token 消耗
- Microcompact: 清理旧 tool_result 内容
- Scratchpad: 维护评审状态文件
- 收敛保护: 检测 agent 在同一改进项上打转
- Turn 回调: 注入到 tool_loop 的每轮结束
"""

import os
import re

# ============================================================
# Microcompact（微压缩）
# ============================================================

# 可清理的工具列表（只读型工具，返回内容大且可丢弃）
COMPACTABLE_TOOLS = {"read_file", "list_directory", "search_files", "run_bash"}

# 存放不可清理的 tool_use_id（如 agent 后续还需引用的结果）
PINNED_TOOL_RESULTS = set()

COMPACT_PLACEHOLDER = "[已处理，原始内容已清理]"


def microcompact(messages, current_turn_index=None):
    """
    清理旧 tool_result 中的大内容，原地修改 messages
    规则：
    - 只清理 COMPACTABLE_TOOLS 中的工具返回
    - 2 轮以前的 tool_result 且 content 长度 > 500
    - 不删除消息结构，只替换 content 文本
    - PINNED_TOOL_RESULTS 中的 tool_use_id 跳过
    """
    if current_turn_index is None:
        current_turn_index = _count_turns(messages)

    # 收集可清理的 tool_use_id → 工具名映射
    tool_id_to_name = {}
    turn_counter = 0

    for msg in messages:
        if msg["role"] == "assistant":
            turn_counter += 1
            content = msg.get("content", [])
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        # 只记录 2 轮以前的
                        if current_turn_index - turn_counter >= 2:
                            if block.get("name") in COMPACTABLE_TOOLS:
                                tool_id_to_name[block["id"]] = block["name"]

    # 清理对应的 tool_result
    for msg in messages:
        if msg["role"] != "user":
            continue
        content = msg.get("content", [])
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") != "tool_result":
                continue
            tool_use_id = block.get("tool_use_id", "")
            if tool_use_id in PINNED_TOOL_RESULTS:
                continue
            if tool_use_id not in tool_id_to_name:
                continue
            # 检查 content 长度
            raw_content = block.get("content", "")
            if isinstance(raw_content, str) and len(raw_content) > 500:
                block["content"] = COMPACT_PLACEHOLDER

    # 同时处理纯文本格式的 tool results（OpenAI 兼容模式下 tool results 作为 user 消息）
    for msg in messages:
        if msg["role"] != "user":
            continue
        content = msg.get("content", "")
        if not isinstance(content, str):
            continue
        if not content.startswith("工具执行结果："):
            continue
        # 检查是否是早期轮次（至少 4 条消息前）
        msg_index = messages.index(msg)
        if len(messages) - msg_index < 4:
            continue
        # 截断长内容
        if len(content) > 2000:
            msg["content"] = content[:500] + "\n\n[...旧工具结果已压缩...]"


def _count_turns(messages):
    """计算 assistant 消息的轮数"""
    return sum(1 for m in messages if m["role"] == "assistant")


# ============================================================
# Scratchpad 状态板
# ============================================================

SCRATCHPAD_FILENAME = "_scratchpad.md"

# Phase 列表，用于校验
VALID_PHASES = {"phase0", "phase0.5", "phase1", "phase2", "phase3", "phase4"}


def update_scratchpad(workspace, phase, review_items=None, wiki_changes=None, knowledge_gaps=None):
    """
    更新工作目录下的 _scratchpad.md
    - phase: 当前阶段
    - review_items: [{"item": "...", "status": "pending|confirmed|rejected"}, ...]
    - wiki_changes: ["变更描述1", "变更描述2", ...]
    - knowledge_gaps: ["盲区1", "盲区2", ...]
    """
    path = os.path.join(workspace, SCRATCHPAD_FILENAME)

    # 先读取已有内容，做增量更新
    existing = parse_scratchpad(workspace)

    # 合并数据：新值覆盖旧值，列表追加去重
    existing["phase"] = phase

    if review_items is not None:
        # 用 item 文本做 key，更新状态
        item_map = {r["item"]: r["status"] for r in existing.get("review_items", [])}
        for ri in review_items:
            item_map[ri["item"]] = ri["status"]
        existing["review_items"] = [{"item": k, "status": v} for k, v in item_map.items()]

    if wiki_changes is not None:
        old_changes = set(existing.get("wiki_changes", []))
        old_changes.update(wiki_changes)
        existing["wiki_changes"] = list(old_changes)

    if knowledge_gaps is not None:
        old_gaps = set(existing.get("knowledge_gaps", []))
        old_gaps.update(knowledge_gaps)
        existing["knowledge_gaps"] = list(old_gaps)

    # 写文件
    lines = [
        f"# 啄木鸟评审状态板",
        f"",
        f"## Phase",
        f"{existing['phase']}",
        f"",
        f"## 改进项",
    ]
    for ri in existing.get("review_items", []):
        marker = "x" if ri["status"] == "confirmed" else " "
        status_label = f"({ri['status']})" if ri["status"] == "rejected" else ""
        lines.append(f"- [{marker}] {ri['item']} {status_label}".rstrip())

    lines.append("")
    lines.append("## Wiki 变更记录")
    for wc in existing.get("wiki_changes", []):
        lines.append(f"- {wc}")

    lines.append("")
    lines.append("## 知识盲区")
    for kg in existing.get("knowledge_gaps", []):
        lines.append(f"- {kg}")

    lines.append("")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def read_scratchpad(workspace):
    """读取 _scratchpad.md 原始内容"""
    path = os.path.join(workspace, SCRATCHPAD_FILENAME)
    if not os.path.exists(path):
        return ""
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def parse_scratchpad(workspace):
    """
    解析 _scratchpad.md 为结构化 dict
    返回: {
        "phase": "phase1",
        "review_items": [{"item": "...", "status": "pending|confirmed|rejected"}],
        "wiki_changes": [...],
        "knowledge_gaps": [...],
    }
    """
    content = read_scratchpad(workspace)
    result = {
        "phase": "phase0",
        "review_items": [],
        "wiki_changes": [],
        "knowledge_gaps": [],
    }
    if not content:
        return result

    current_section = None
    for line in content.split("\n"):
        stripped = line.strip()
        if stripped == "## Phase":
            current_section = "phase"
            continue
        elif stripped == "## 改进项":
            current_section = "review_items"
            continue
        elif stripped == "## Wiki 变更记录":
            current_section = "wiki_changes"
            continue
        elif stripped == "## 知识盲区":
            current_section = "knowledge_gaps"
            continue
        elif stripped.startswith("##"):
            current_section = None
            continue

        if not stripped:
            continue

        if current_section == "phase":
            result["phase"] = stripped
        elif current_section == "review_items":
            # 解析 - [x] item (rejected) 或 - [ ] item
            m = re.match(r"^- \[( |x)\]\s*(.+?)(?:\s*\((rejected)\))?\s*$", stripped)
            if m:
                checked, item_text, rejected = m.groups()
                if rejected:
                    status = "rejected"
                elif checked == "x":
                    status = "confirmed"
                else:
                    status = "pending"
                result["review_items"].append({"item": item_text, "status": status})
        elif current_section == "wiki_changes":
            if stripped.startswith("- "):
                result["wiki_changes"].append(stripped[2:])
        elif current_section == "knowledge_gaps":
            if stripped.startswith("- "):
                result["knowledge_gaps"].append(stripped[2:])

    return result


# ============================================================
# 收敛保护
# ============================================================

def check_convergence(messages, threshold=3):
    """
    检测 agent 是否在打转：最近 N 轮 assistant 输出的文本增量持续很低
    如果最近 threshold 轮每轮 assistant 文本 < 200 字符，返回 nudge 消息
    """
    # 收集最近 N 轮 assistant 的文本长度
    assistant_lengths = []
    for msg in reversed(messages):
        if msg["role"] == "assistant":
            text_len = _extract_text_length(msg)
            assistant_lengths.append(text_len)
            if len(assistant_lengths) >= threshold:
                break

    if len(assistant_lengths) < threshold:
        return None

    # 如果最近每轮都很短，说明在打转
    if all(length < 200 for length in assistant_lengths):
        return {
            "role": "user",
            "content": (
                "[系统提示] 检测到最近几轮输出内容很少，可能在同一个问题上反复纠结。"
                "请决策：1) 标记为「已确认」并继续下一项；2) 标记为「知识盲区」跳过；"
                "3) 用不同的方式重新分析。"
            ),
        }

    return None


def _extract_text_length(assistant_msg):
    """提取 assistant 消息中的纯文本长度"""
    content = assistant_msg.get("content", [])
    if isinstance(content, str):
        return len(content)
    total = 0
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                total += len(block.get("text", ""))
    return total


# ============================================================
# Turn 回调
# ============================================================

def create_turn_callback(workspace):
    """
    返回一个 callback 函数，签名 callback(messages, response)
    供 run_session.py 的 tool_loop 使用
    每轮结束后：
    1. 执行 microcompact 清理旧 tool_result
    2. 检查收敛，必要时注入 nudge 消息
    """
    def _callback(messages, response):
        # 微压缩
        microcompact(messages)

        # 收敛保护
        nudge = check_convergence(messages)
        if nudge:
            messages.append(nudge)

    return _callback
