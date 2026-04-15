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
    for msg_index, msg in enumerate(messages):
        if msg["role"] != "user":
            continue
        content = msg.get("content", "")
        if not isinstance(content, str):
            continue
        if not content.startswith("工具执行结果："):
            continue
        # 检查是否是早期轮次（至少 4 条消息前）
        if len(messages) - msg_index < 4:
            continue
        # 截断长内容
        if len(content) > 2000:
            msg["content"] = content[:500] + "\n\n[...旧工具结果已压缩...]"


def _count_turns(messages):
    """计算 assistant 消息的轮数"""
    return sum(1 for m in messages if m["role"] == "assistant")


# ============================================================
# Autocompact（参考 CC autoCompact.ts:72-91 + compact.ts:450-491）
# ============================================================

# CC 常量
AUTOCOMPACT_BUFFER_TOKENS = 13000   # context_window - buffer = 触发阈值
MAX_COMPACT_FAILURES = 3             # 连续失败 3 次则熔断
KEEP_RECENT_MESSAGES = 10            # 保留最近 5 轮（10 条 message）


def estimate_tokens_rough(content):
    """粗估 token 数（4 bytes/token，CC tokenEstimation.ts:203-208）"""
    if isinstance(content, str):
        return len(content.encode("utf-8")) // 4
    if isinstance(content, list):
        return sum(estimate_tokens_rough(c) for c in content)
    if isinstance(content, dict):
        import json
        return estimate_tokens_rough(json.dumps(content, ensure_ascii=False))
    return 0


def estimate_messages_tokens(messages):
    """估算 messages 列表的 token，含 4/3 安全系数"""
    total = sum(estimate_tokens_rough(m.get("content", "")) for m in messages)
    return int(total * 4 / 3)


class AutocompactManager:
    """自动压缩管理器，含熔断器（CC autoCompact.ts:257-265）"""

    def __init__(self, max_context_tokens=200000):
        self.max_context = max_context_tokens
        self.compact_failures = 0
        self.total_tokens_saved = 0

    @property
    def threshold(self):
        return self.max_context - AUTOCOMPACT_BUFFER_TOKENS

    @property
    def is_circuit_broken(self):
        return self.compact_failures >= MAX_COMPACT_FAILURES

    def should_compact(self, messages):
        """判断是否需要 autocompact"""
        if self.is_circuit_broken:
            return False
        current = estimate_messages_tokens(messages)
        return current >= self.threshold

    def compact(self, client, messages, model_tiers):
        """用 Haiku 做摘要压缩（CC compact.ts:400-491 的简化版）"""
        if len(messages) <= KEEP_RECENT_MESSAGES:
            return messages  # 消息太少，不压缩

        old_msgs = messages[:-KEEP_RECENT_MESSAGES]
        recent_msgs = messages[-KEEP_RECENT_MESSAGES:]

        # 序列化旧消息为文本
        old_text = _serialize_messages_for_summary(old_msgs)
        old_tokens = estimate_tokens_rough(old_text)

        try:
            summary_response = client.create(
                model=model_tiers.get("haiku", model_tiers.get("sonnet")),
                max_tokens=2000,
                system="你是对话历史压缩器。将以下 PRD 评审对话压缩为简洁摘要，保留：1) 所有已发现的改进项编号和状态；2) 关键决策和理由；3) 当前评审进度。去掉工具调用细节。",
                messages=[{"role": "user", "content": old_text}],
                retry_policy="router",  # 快速失败，不阻塞主流程
            )
            summary_text = ""
            for block in summary_response.content:
                if block.type == "text":
                    summary_text += block.text

            if not summary_text.strip():
                raise ValueError("摘要为空")

            compressed = [
                {"role": "user", "content": f"[之前的评审对话摘要（约 {old_tokens} token 压缩而来）]\n\n{summary_text}"},
                {"role": "assistant", "content": "好的，我已了解之前的评审进展，继续当前工作。"},
            ] + recent_msgs

            new_tokens = estimate_messages_tokens(compressed)
            saved = estimate_messages_tokens(messages) - new_tokens
            self.total_tokens_saved += saved
            self.compact_failures = 0  # 重置熔断计数

            return compressed

        except Exception as e:
            self.compact_failures += 1
            from logger import get_logger
            log = get_logger("compact")
            log.warning(f"Autocompact 失败 ({self.compact_failures}/{MAX_COMPACT_FAILURES}): {str(e)[:60]}")
            return messages  # 失败时返回原始消息

    def status(self):
        """返回压缩状态摘要"""
        return (
            f"autocompact: saved={self.total_tokens_saved:,} tokens, "
            f"failures={self.compact_failures}/{MAX_COMPACT_FAILURES}, "
            f"breaker={'OPEN' if self.is_circuit_broken else 'closed'}"
        )


def _serialize_messages_for_summary(messages):
    """将 messages 序列化为可摘要的文本"""
    parts = []
    for msg in messages:
        role = msg["role"]
        content = msg.get("content", "")
        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            # 提取文本块，跳过 tool_result 细节
            text_parts = []
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") == "text":
                        text_parts.append(block.get("text", ""))
                    elif block.get("type") == "tool_result":
                        text_parts.append(f"[tool result: {block.get('content', '')[:100]}...]")
                    elif block.get("type") == "tool_use":
                        text_parts.append(f"[tool call: {block.get('name', '')}]")
            text = "\n".join(text_parts)
        else:
            text = str(content)

        # 截断单条消息到 500 字符（只是做摘要，不需要全文）
        if len(text) > 500:
            text = text[:500] + "..."
        parts.append(f"[{role}] {text}")

    return "\n\n".join(parts)


# ============================================================
# Scratchpad 状态板
# ============================================================

SCRATCHPAD_FILENAME = "_scratchpad.md"


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
# Tool Use Summary（参考 CC toolUseSummaryGenerator.ts:15-96）
# ============================================================

def generate_tool_summary(client, tool_calls_info, model_tiers):
    """
    用 Haiku 生成工具执行摘要（30 字内，过去时，像 git commit subject）
    tool_calls_info: [{"name": "read_file", "input": {...}, "output": "..."}, ...]
    """
    if not tool_calls_info:
        return ""

    import json as _json
    tool_descs = []
    for tc in tool_calls_info[:5]:  # 最多 5 个
        input_str = _json.dumps(tc.get("input", {}), ensure_ascii=False)[:300]
        output_str = str(tc.get("output", ""))[:300]
        tool_descs.append(f"Tool: {tc.get('name')}\nInput: {input_str}\nOutput: {output_str}")

    try:
        resp = client.create(
            model=model_tiers.get("haiku", model_tiers.get("sonnet")),
            max_tokens=50,
            system="用过去时写一句话总结这些工具调用完成了什么。30字以内，像 git commit subject。中文回答。示例：读取了 3 个配置文件、搜索了认证模块代码、执行了单元测试",
            messages=[{"role": "user", "content": "\n\n".join(tool_descs) + "\n\n摘要："}],
            retry_policy="router",
        )
        for block in resp.content:
            if block.type == "text":
                return block.text.strip()
    except Exception:
        pass
    return ""


# ============================================================
# Context Collapse（参考 CC collapseReadSearch.ts:762-950）
# ============================================================

# 可折叠的只读工具
COLLAPSIBLE_TOOLS = {"read_file", "search_files", "list_directory"}


def collapse_consecutive_reads(messages, min_consecutive=3):
    """
    合并连续只读工具结果为摘要行，减少上下文占用
    只处理 4 条消息之前的旧内容（不动最近的）
    """
    if len(messages) < 8:
        return  # 消息太少，不处理

    # 找连续的只读 tool_use + tool_result 对
    i = 0
    safe_end = len(messages) - 4  # 不动最近 4 条

    while i < safe_end:
        msg = messages[i]
        # 找 assistant 消息中连续的只读 tool_use
        if msg.get("role") != "assistant":
            i += 1
            continue

        content = msg.get("content", [])
        if not isinstance(content, list):
            i += 1
            continue

        # 统计这条 assistant 消息中的只读工具调用
        read_tool_ids = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                if block.get("name") in COLLAPSIBLE_TOOLS:
                    read_tool_ids.append(block["id"])

        if len(read_tool_ids) < min_consecutive:
            i += 1
            continue

        # 找对应的 tool_result 消息并折叠
        if i + 1 < safe_end:
            next_msg = messages[i + 1]
            if next_msg.get("role") == "user" and isinstance(next_msg.get("content"), list):
                collapsed_count = 0
                tool_names = []
                for block in next_msg["content"]:
                    if isinstance(block, dict) and block.get("type") == "tool_result":
                        if block.get("tool_use_id") in read_tool_ids:
                            old_content = block.get("content", "")
                            if isinstance(old_content, str) and len(old_content) > 200:
                                block["content"] = f"[已折叠，原始 {len(old_content)} 字符]"
                                collapsed_count += 1
                                # 从 assistant 消息中找工具名
                                for ab in content:
                                    if isinstance(ab, dict) and ab.get("id") == block["tool_use_id"]:
                                        tool_names.append(ab.get("name", "unknown"))

                if collapsed_count > 0:
                    from logger import get_logger
                    log = get_logger("collapse")
                    log.info(f"折叠 {collapsed_count} 个连续只读工具结果: {', '.join(tool_names[:5])}")

        i += 1


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

# 全局 autocompact 管理器实例
_autocompact_mgr = None


def get_autocompact_manager(max_context_tokens=200000):
    """获取或创建全局 autocompact 管理器"""
    global _autocompact_mgr
    if _autocompact_mgr is None:
        _autocompact_mgr = AutocompactManager(max_context_tokens)
    return _autocompact_mgr


def create_turn_callback(workspace):
    """
    返回一个 callback 函数，签名 callback(messages, response)
    供 run_session.py 的 tool_loop 使用
    每轮结束后：
    1. 执行 microcompact 清理旧 tool_result
    2. 检查收敛，必要时注入 nudge 消息
    （autocompact 由 run_session 主循环在 tool_loop 外触发）
    """
    def _callback(messages, response):
        # 微压缩
        microcompact(messages)

        # 连续只读工具折叠（CC collapseReadSearch 模式）
        collapse_consecutive_reads(messages)

        # 收敛保护
        nudge = check_convergence(messages)
        if nudge:
            messages.append(nudge)

    return _callback
