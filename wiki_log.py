"""
Wiki log.md 追记 helper (v1.2 D2)

风鸟 wiki 方法论中的 `log.md` 机制:wiki 下每次变更追加一行
`## [YYYY-MM-DD] action | detail`,按首行去重,可被多次调用而不重复。

鸮鹦(auto_fix/rebuild_index)、post_review 等模块通过本模块主动写 log.md。

tools.py:_write_file_impl 已经有类似的追加+去重逻辑,但那是 write_file 工具的
内部实现,不适合外部直接 import。本模块提供面向业务的简洁接口。
"""

import os
import re
import datetime
from wiki_lock import wiki_write_lock


def append_log_entry(wiki_path, action, detail="", *, date=None):
    """追加一条 log.md 条目,如同一天同一 action 已存在则跳过

    Args:
        wiki_path: wiki 目录绝对路径(必须存在)
        action: 动作名,例如 "auto_fix" / "rebuild_index" / "review_done"
        detail: 详细描述(可选,会出现在标题行)
        date: 可选覆盖日期字符串(YYYY-MM-DD),默认今天

    Returns:
        bool: 追加成功返回 True,跳过(已存在)返回 False
    """
    if not os.path.isdir(wiki_path):
        return False

    date_str = date or datetime.date.today().isoformat()
    first_line = f"## [{date_str}] {action}"
    if detail:
        entry = f"{first_line} | {detail}\n"
    else:
        entry = f"{first_line}\n"

    log_path = os.path.join(wiki_path, "log.md")

    # 用 wiki 锁保护,避免多 session 并发写冲突
    with wiki_write_lock(wiki_path):
        existing = ""
        if os.path.exists(log_path):
            with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                existing = f.read()

        # 去重:同一首行(含日期+action)+detail 已存在则跳过
        # 只用首行作为去重 key,保证同一天同一 action 只写一次(风鸟方法论)
        if first_line in existing:
            # 再检查 detail 是否已匹配(同一天同 action 不同 detail 视为不同条目)
            if detail:
                if entry.rstrip() in existing:
                    return False
                # 同一天同 action 但 detail 不同——追加新条目
            else:
                return False

        # 确保文件存在且有合理的开头
        if not existing:
            header = "# Wiki 变更日志\n\n"
            new_content = header + entry
        else:
            # 追加到末尾,和已有内容之间保留空行
            new_content = existing.rstrip() + "\n\n" + entry

        with open(log_path, "w", encoding="utf-8") as f:
            f.write(new_content)

    return True


def append_multiple_log_entries(wiki_path, entries):
    """批量追加多条 log 条目(用于一次操作触发多条记录的场景)

    Args:
        wiki_path: wiki 目录
        entries: [(action, detail), ...] 或 [(action, detail, date), ...]

    Returns:
        int: 实际追加的条目数(去重后)
    """
    count = 0
    for entry in entries:
        if len(entry) == 2:
            action, detail = entry
            date = None
        elif len(entry) == 3:
            action, detail, date = entry
        else:
            continue
        if append_log_entry(wiki_path, action, detail, date=date):
            count += 1
    return count
