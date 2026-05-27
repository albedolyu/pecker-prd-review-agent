"""
Wiki 定期合并清理 -- 参考 Claude Code autoDream.ts
功能：
  1. 门控：24h + 3 次 session 后才触发
  2. PID 锁：防止并发
  3. 合并/清理：删除矛盾、过期页面，转换相对日期
  4. 可独立 CLI 运行
"""

import json
import os
import time
from datetime import datetime

from logger import get_logger

log = get_logger("consolidation")

# CC autoDream.ts 门控常量
MIN_HOURS_SINCE_LAST = 24
MIN_SESSIONS_SINCE_LAST = 3
LOCK_STALE_SECONDS = 3600  # 1 小时后视为过期锁


# ============================================================
# 锁（CC consolidationLock.ts 模式）
# ============================================================

def _lock_path(workspace):
    return os.path.join(workspace, "output", ".consolidate_lock")


def _state_path(workspace):
    return os.path.join(workspace, "output", ".consolidation_state.json")


def _read_state(workspace):
    """读取合并状态"""
    fpath = _state_path(workspace)
    if not os.path.exists(fpath):
        return {"last_consolidated_at": 0, "session_count_since": 0}
    try:
        with open(fpath, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {"last_consolidated_at": 0, "session_count_since": 0}


def _write_state(workspace, state):
    """写入合并状态"""
    os.makedirs(os.path.dirname(_state_path(workspace)), exist_ok=True)
    with open(_state_path(workspace), "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def increment_session_count(workspace):
    """每次评审 session 结束时调用，累计 session 计数"""
    state = _read_state(workspace)
    state["session_count_since"] = state.get("session_count_since", 0) + 1
    _write_state(workspace, state)


def _is_process_alive(pid):
    """跨平台检查进程是否存活"""
    import sys
    if sys.platform == "win32":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
            if handle:
                kernel32.CloseHandle(handle)
                return True
            return False
        except Exception:
            return False
    else:
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False


def try_acquire_lock(workspace):
    """尝试获取合并锁（CC consolidationLock.ts PID 模式）"""
    lock = _lock_path(workspace)
    os.makedirs(os.path.dirname(lock), exist_ok=True)

    # 检查已有锁
    if os.path.exists(lock):
        try:
            mtime = os.path.getmtime(lock)
            age = time.time() - mtime
            if age < LOCK_STALE_SECONDS:
                # 锁还新鲜，检查 PID 是否还活着
                with open(lock, "r") as f:
                    pid = int(f.read().strip())
                if _is_process_alive(pid):
                    return False  # 进程活着，锁有效
                # 进程已死，锁过期
            # 锁过期，清理
            os.remove(lock)
        except (OSError, ValueError):
            try:
                os.remove(lock)
            except OSError:
                pass

    # 写入新锁
    try:
        with open(lock, "w") as f:
            f.write(str(os.getpid()))
        return True
    except OSError:
        return False


def release_lock(workspace):
    """释放合并锁"""
    lock = _lock_path(workspace)
    try:
        os.remove(lock)
    except OSError:
        pass


# ============================================================
# 门控检查（CC autoDream.ts:95-108）
# ============================================================

def should_consolidate(workspace):
    """检查是否满足合并条件"""
    state = _read_state(workspace)
    last_ts = state.get("last_consolidated_at", 0)
    sessions = state.get("session_count_since", 0)

    hours_since = (time.time() - last_ts) / 3600 if last_ts > 0 else float("inf")

    if hours_since < MIN_HOURS_SINCE_LAST:
        return False, f"距上次合并仅 {hours_since:.1f}h（需 {MIN_HOURS_SINCE_LAST}h）"
    if sessions < MIN_SESSIONS_SINCE_LAST:
        return False, f"仅 {sessions} 次 session（需 {MIN_SESSIONS_SINCE_LAST} 次）"
    return True, f"已满足条件: {hours_since:.0f}h + {sessions} sessions"


# ============================================================
# 合并执行（CC consolidationPrompt.ts 的简化版）
# ============================================================

def consolidate_wiki(client, wiki_path, workspace, model_tiers):
    """
    用 Haiku 执行 wiki 合并清理
    返回: {"merged": N, "deleted": N, "updated": N}
    """
    if not os.path.isdir(wiki_path):
        return {"merged": 0, "deleted": 0, "updated": 0}

    # 收集所有 wiki 页面信息
    pages = []
    for fname in sorted(os.listdir(wiki_path)):
        if not fname.endswith(".md") or fname in ("index.md", "log.md", "_scratchpad.md"):
            continue
        fpath = os.path.join(wiki_path, fname)
        try:
            mtime = os.path.getmtime(fpath)
            days = (time.time() - mtime) / 86400
            with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            pages.append({
                "name": fname,
                "days_old": int(days),
                "size": len(content),
                "first_line": content.split("\n")[0][:100] if content else "",
            })
        except OSError:
            continue

    if not pages:
        return {"merged": 0, "deleted": 0, "updated": 0}

    # 构建页面清单
    manifest = "\n".join(
        f"- {p['name']} ({p['days_old']}天前, {p['size']}字): {p['first_line']}"
        for p in pages
    )

    # 也收集反馈历史摘要
    feedback_summary = _load_feedback_summary(workspace)

    prompt = (
        f"## Wiki 页面清单\n{manifest}\n\n"
        f"## 反馈历史摘要\n{feedback_summary}\n\n"
        "请分析以上 wiki 页面，识别：\n"
        "1. 可合并的重复/重叠页面（列出页面名对）\n"
        "2. 超过 30 天未更新且可能过期的页面\n"
        "3. 内容矛盾的页面（如果有）\n\n"
        "输出 JSON：{\"merge\": [[\"a.md\",\"b.md\"]], \"stale\": [\"c.md\"], \"conflicts\": [\"d.md\"]}"
    )

    try:
        resp = client.create(
            model=model_tiers.get("haiku", model_tiers.get("sonnet")),
            max_tokens=1000,
            system="你是知识库健康检查器。分析 wiki 页面清单，识别可合并、过期、矛盾的内容。只输出 JSON。",
            messages=[{"role": "user", "content": prompt}],
            retry_policy="router",
        )

        text = ""
        for block in resp.content:
            if block.type == "text":
                text += block.text

        import re
        m = re.search(r'\{[\s\S]*\}', text)
        if not m:
            return {"merged": 0, "deleted": 0, "updated": 0}

        result = json.loads(m.group())
        stats = {
            "merged": len(result.get("merge", [])),
            "deleted": len(result.get("stale", [])),
            "updated": len(result.get("conflicts", [])),
        }

        # 标记过期页面（不删除，只加标记）
        for stale_page in result.get("stale", []):
            _mark_stale(wiki_path, stale_page)

        # 更新合并状态
        state = _read_state(workspace)
        state["last_consolidated_at"] = time.time()
        state["session_count_since"] = 0
        state["last_result"] = stats
        _write_state(workspace, state)

        return stats

    except Exception as e:
        log.warning(f"Wiki 合并失败: {str(e)[:60]}")
        return {"merged": 0, "deleted": 0, "updated": 0}


def _mark_stale(wiki_path, page_name):
    """给过期页面加标记（不删除）"""
    fpath = os.path.join(wiki_path, page_name)
    if not os.path.exists(fpath):
        return
    try:
        with open(fpath, "r", encoding="utf-8") as f:
            content = f.read()
        if "[STALE]" in content:
            return  # 已标记
        with open(fpath, "w", encoding="utf-8") as f:
            f.write(f"<!-- [STALE] 此页面可能已过期，由 wiki_consolidation 标记于 {datetime.now().strftime('%Y-%m-%d')} -->\n{content}")
    except OSError:
        pass


def _load_feedback_summary(workspace):
    """加载反馈历史摘要"""
    fpath = os.path.join(workspace, "output", "rule_performance_history.json")
    if not os.path.exists(fpath):
        return "(无反馈历史)"
    try:
        with open(fpath, "r", encoding="utf-8") as f:
            history = json.load(f)
        # 只取异常规则
        flagged = []
        for rule_id, stats in history.items():
            if not isinstance(stats, dict):
                continue
            rr = stats.get("rejection_rate", 0)
            missed = stats.get("stats", {}).get("missed", 0)
            if rr > 0.3 or missed > 2:
                flagged.append(f"{rule_id}: 驳回率{int(rr*100)}%, 漏报{missed}次")
        return "\n".join(flagged) if flagged else "(所有规则表现正常)"
    except (json.JSONDecodeError, OSError):
        return "(读取失败)"


# ============================================================
# 自动触发入口（从 run_session.py 调用）
# ============================================================

def try_auto_consolidate(client, wiki_path, workspace, model_tiers):
    """
    尝试自动合并（满足门控 + 拿到锁才执行）
    返回: stats dict 或 None
    """
    should, reason = should_consolidate(workspace)
    if not should:
        log.info(f"跳过合并: {reason}")
        return None

    if not try_acquire_lock(workspace):
        log.info("跳过合并: 另一个进程持有锁")
        return None

    try:
        log.info("开始 wiki 定期合并...")
        stats = consolidate_wiki(client, wiki_path, workspace, model_tiers)
        log.info(f"合并完成: {stats}")
        return stats
    finally:
        release_lock(workspace)


# ============================================================
# CLI 入口
# ============================================================

if __name__ == "__main__":
    import argparse
    from dotenv import load_dotenv
    load_dotenv()

    parser = argparse.ArgumentParser(description="Wiki 定期合并清理")
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--wiki", required=True)
    parser.add_argument("--force", action="store_true", help="跳过门控检查")
    args = parser.parse_args()

    from api_adapter import create_client
    from agent_config import MODEL_TIERS
    client = create_client()

    if args.force:
        print("强制执行合并...")
        stats = consolidate_wiki(client, args.wiki, args.workspace, MODEL_TIERS)
    else:
        stats = try_auto_consolidate(client, args.wiki, args.workspace, MODEL_TIERS)

    if stats:
        print(f"合并结果: {json.dumps(stats, ensure_ascii=False)}")
    else:
        print("未执行合并")
