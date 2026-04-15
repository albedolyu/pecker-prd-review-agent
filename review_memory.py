"""
评审记忆提取 -- 评审结束后自动从会话中提取可复用知识
参考 Claude Code extractMemories.ts:326-567 的四类记忆模式

D1 (Phase 4): 写入前 MD5 去重 + 按 type 分组的滑窗淘汰,避免记忆无限累积
P1 (Phase 5 memory cleanup): 产出改为 wiki markdown 页面,向 Obsidian llm-wiki 方法论靠拢
    - 知识编译优于知识检索
    - 记忆与 wiki/ 合为一个家,自动享受鸮鹦 Lint / 双向链接 / 人工编辑
    - 老 JSON 向后兼容读取,新写入只走 wiki 路径
"""

import hashlib
import json
import os
import re
import time
from datetime import datetime

from logger import get_logger

log = get_logger("memory")

# 记忆目录(P1 后只用于向后兼容读取老 JSON)
MEMORY_DIR_NAME = ".review_memory"

# D1: 每个 type 最多保留多少条(滑窗淘汰 — 老 JSON 路径用)
MAX_KEEP_PER_TYPE = 20

# 记忆类型（CC 四类分类）
MEMORY_TYPES = {
    "feedback": "评审规则反馈（哪些规则在什么场景下容易误报/漏报）",
    "project": "项目上下文（模块特征、数据表结构、业务规则）",
    "reference": "外部引用（DDL 位置、API 文档、竞品参考）",
    "reviewer": "审阅人偏好（严格程度、关注维度、跳过偏好）",
}

# P1: type → wiki 文件名前缀映射(对齐 kakapo_dream.VALID_PREFIXES 命名规范)
TYPE_TO_WIKI_PREFIX = {
    "feedback":  "决策-",   # 评审决策/规则权重
    "project":   "实体-",   # 项目上下文 → 业务实体
    "reference": "约束-",   # 外部引用 → 外部约束
    "reviewer":  "概念-",   # 审阅人偏好 → 审阅概念
}

# 提取 prompt
EXTRACT_SYSTEM_PROMPT = """你是评审记忆提取器。从 PRD 评审会话中提取可复用的知识，分为以下 4 类：

1. feedback — 评审规则反馈：哪些规则在什么类型的 PRD 中容易误报或漏报
2. project — 项目上下文：模块的业务特征、数据表结构、关键约束
3. reference — 外部引用：DDL 表名、wiki 页面路径、竞品参考
4. reviewer — 审阅人偏好：对哪些规则更严格、哪些维度优先关注

输出 JSON 数组，每条记忆格式：
[
  {"type": "feedback", "title": "简短标题", "content": "具体内容，包含规则编号和场景"},
  ...
]

规则：
- 只提取未来评审中可复用的知识，不记录本次评审的具体结论
- 每类最多 3 条，总共不超过 8 条
- 如果没有可提取的记忆，返回空数组 []
"""


def get_memory_dir(workspace):
    """获取记忆存储目录"""
    d = os.path.join(workspace, "output", MEMORY_DIR_NAME)
    os.makedirs(d, exist_ok=True)
    return d


def build_memory_manifest(workspace):
    """构建已有记忆清单（CC manifest 预注入模式）"""
    mem_dir = get_memory_dir(workspace)
    lines = []
    for fname in sorted(os.listdir(mem_dir)):
        if not fname.endswith(".json"):
            continue
        fpath = os.path.join(mem_dir, fname)
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                data = json.load(f)
            mtime = datetime.fromtimestamp(os.path.getmtime(fpath)).strftime("%Y-%m-%d")
            title = data.get("title", fname)
            mtype = data.get("type", "unknown")
            lines.append(f"- [{mtype}] {title} ({mtime})")
        except (json.JSONDecodeError, OSError):
            continue
    return "\n".join(lines) if lines else "(暂无已有记忆)"


def _extract_json_array(text):
    """从文本中提取第一个平衡的 JSON 数组（避免贪婪正则问题）"""
    start = text.find("[")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                import re
                class _Match:
                    def group(self): return text[start:i+1]
                return _Match()
    return None


def extract_memories(client, messages, workspace, model_tiers, prd_name="", reviewer="", wiki_path=None):
    """
    从评审会话中提取可复用记忆（CC extractMemories 模式）
    - 用 Haiku 做提取（快速、低成本）
    - 预注入已有记忆 manifest 避免重复
    - P1: 若提供 wiki_path,产出直接写为 wiki/*.md(否则降级老 JSON)
    """
    # 序列化最近的会话内容（不需要全部，最后 20 条够了）
    recent = messages[-20:] if len(messages) > 20 else messages
    session_text = _serialize_session(recent, prd_name, reviewer)

    # 构建 manifest
    manifest = build_memory_manifest(workspace)

    user_msg = (
        f"## 已有记忆清单\n{manifest}\n\n"
        f"## 本次评审会话\n{session_text}\n\n"
        f"请提取可复用的记忆（避免与已有记忆重复）。返回 JSON 数组。"
    )

    try:
        response = client.create(
            model=model_tiers.get("haiku", model_tiers.get("sonnet")),
            max_tokens=1500,
            system=EXTRACT_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
            retry_policy="router",
        )

        text = ""
        for block in response.content:
            if block.type == "text":
                text += block.text

        # 解析 JSON（用平衡括号提取，避免贪婪正则过度匹配）
        import re
        m = _extract_json_array(text)
        if not m:
            return []
        memories = json.loads(m.group())
        if not isinstance(memories, list):
            return []

        # 保存(P1: 走 wiki 优先)
        saved = _save_memories(memories, workspace, prd_name, wiki_path=wiki_path, reviewer=reviewer)
        return saved

    except Exception as e:
        log.warning(f"记忆提取失败: {str(e)[:60]}")
        return []


def _serialize_session(messages, prd_name, reviewer):
    """序列化会话为可提取的文本"""
    parts = [f"PRD: {prd_name}, 审阅人: {reviewer}"]
    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")
        if isinstance(content, str):
            text = content[:300]
        elif isinstance(content, list):
            text_parts = []
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") == "text":
                        text_parts.append(block.get("text", "")[:200])
                    elif block.get("type") == "tool_use":
                        text_parts.append(f"[{block.get('name', '')}]")
            text = " ".join(text_parts)[:300]
        else:
            text = str(content)[:200]
        parts.append(f"[{role}] {text}")
    return "\n".join(parts)


def _normalize_content(text):
    """文本归一化(去多余空白 + 小写),用于 dedupe hash"""
    if not isinstance(text, str):
        text = str(text)
    return re.sub(r"\s+", " ", text.strip().lower())


def _memory_hash(mtype, content):
    """D1: (type, 归一化 content) 的 MD5,用作去重 key"""
    key = f"{mtype}|{_normalize_content(content)}"
    return hashlib.md5(key.encode("utf-8")).hexdigest()


def _collect_existing_hashes(mem_dir):
    """扫描现有记忆文件,返回已有 hash 集合"""
    hashes = set()
    if not os.path.isdir(mem_dir):
        return hashes
    for fname in os.listdir(mem_dir):
        if not fname.endswith(".json"):
            continue
        try:
            with open(os.path.join(mem_dir, fname), "r", encoding="utf-8") as f:
                data = json.load(f)
            mtype = data.get("type", "")
            content = data.get("content", "")
            if content:
                hashes.add(_memory_hash(mtype, content))
        except (json.JSONDecodeError, OSError):
            continue
    return hashes


def _prune_old_memories(mem_dir, max_per_type=MAX_KEEP_PER_TYPE):
    """D1: 按 type 分组,每组只保留最新 max_per_type 条(滑窗淘汰)

    超出的老记忆直接删除磁盘文件。按 mtime 排序,保留最新的。
    """
    if not os.path.isdir(mem_dir):
        return 0
    by_type = {}
    for fname in os.listdir(mem_dir):
        if not fname.endswith(".json"):
            continue
        fpath = os.path.join(mem_dir, fname)
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                data = json.load(f)
            mtype = data.get("type", "unknown")
            mtime = os.path.getmtime(fpath)
            by_type.setdefault(mtype, []).append((mtime, fpath))
        except (json.JSONDecodeError, OSError):
            continue

    pruned = 0
    for mtype, items in by_type.items():
        if len(items) <= max_per_type:
            continue
        items.sort(key=lambda x: x[0], reverse=True)  # 新→旧
        for _mtime, fpath in items[max_per_type:]:
            try:
                os.remove(fpath)
                pruned += 1
            except OSError:
                pass
    if pruned:
        log.info(f"滑窗淘汰 {pruned} 条老记忆(保留每类最新 {max_per_type} 条)")
    return pruned


def _save_memories(memories, workspace, prd_name, wiki_path=None, reviewer=""):
    """保存提取的记忆(P1: 优先写 wiki,向后兼容老 JSON 路径)

    新行为:
      - 若提供 wiki_path,走 wiki 路径,写 markdown 页面到 wiki/*.md
      - 否则降级到老 JSON 路径(`.review_memory/*.json`)
    去重策略保持:MD5 hash + 跳过已存在内容
    """
    if wiki_path and os.path.isdir(wiki_path):
        return _save_memories_as_wiki(memories, workspace, prd_name, wiki_path, reviewer)
    # 老 JSON 降级路径(兼容没有 wiki_path 的调用)
    return _save_memories_as_json(memories, workspace, prd_name)


def _save_memories_as_json(memories, workspace, prd_name):
    """老 JSON 路径 - 向后兼容(D1: MD5 去重 + 滑窗淘汰)"""
    mem_dir = get_memory_dir(workspace)
    existing_hashes = _collect_existing_hashes(mem_dir)

    saved = []
    skipped_dup = 0
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    for i, mem in enumerate(memories[:8]):
        if not isinstance(mem, dict):
            continue
        mtype = mem.get("type", "unknown")
        title = mem.get("title", f"memory_{i}")
        content = mem.get("content", "")
        if not content:
            continue

        h = _memory_hash(mtype, content)
        if h in existing_hashes:
            skipped_dup += 1
            continue
        existing_hashes.add(h)

        safe_title = "".join(c if c.isalnum() or c in "-_" else "_" for c in title)[:30]
        fname = f"{mtype}_{safe_title}_{ts}_{h[:8]}.json"
        fpath = os.path.join(mem_dir, fname)

        data = {
            "type": mtype,
            "title": title,
            "content": content,
            "prd_name": prd_name,
            "extracted_at": datetime.now().isoformat(),
            "content_hash": h,
        }

        with open(fpath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        saved.append(data)

    if saved:
        log.info(f"[JSON] 提取 {len(saved)} 条评审记忆" + (f"(跳过 {skipped_dup} 条重复)" if skipped_dup else ""))
    elif skipped_dup:
        log.info(f"[JSON] 本次评审记忆全部为重复 ({skipped_dup} 条),未写入")

    _prune_old_memories(mem_dir)
    return saved


def _safe_title(title, max_len=40):
    """把 title 转成合法的文件名片段(去除 / 等特殊字符)"""
    s = re.sub(r'[\\/:*?"<>|\[\]]', "_", title)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:max_len] or "untitled"


def _collect_wiki_hashes(wiki_path):
    """扫描 wiki 目录,收集所有带 content_hash 的页面 frontmatter 做去重"""
    hashes = set()
    if not os.path.isdir(wiki_path):
        return hashes
    for fname in os.listdir(wiki_path):
        if not fname.endswith(".md"):
            continue
        fpath = os.path.join(wiki_path, fname)
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                content = f.read(2048)  # 只读前 2KB 找 frontmatter
        except (OSError, UnicodeDecodeError):
            continue
        m = re.search(r"^content_hash:\s*([0-9a-f]{32})\s*$", content, re.MULTILINE)
        if m:
            hashes.add(m.group(1))
    return hashes


def _save_memories_as_wiki(memories, workspace, prd_name, wiki_path, reviewer=""):
    """P1: 把提取的记忆写成 wiki markdown 页面

    产出格式:
        wiki/实体-对外投资核心数据实体.md
        ---
        title: 对外投资核心数据实体
        source: 啄木鸟评审提取
        created: 2026-04-15
        updated: 2026-04-15
        tags: [memory/project, extracted/auto]
        sources: 1
        scope: workspace
        category: entity
        extracted_from: 对外投资PRD-v1.0
        extracted_reviewer: xxx
        content_hash: <md5>
        ---

        # 对外投资核心数据实体

        <content>

    去重:wiki frontmatter 里记录 content_hash,下次提取时跳过已存在的
    命名冲突:同名追加 timestamp 后缀
    """
    existing_hashes = _collect_wiki_hashes(wiki_path)

    saved = []
    skipped_dup = 0
    today = datetime.now().strftime("%Y-%m-%d")

    # 尝试从 kakapo_dream 借用 frontmatter 推断(优雅降级)
    try:
        from kakapo_dream import _infer_extended_frontmatter
    except Exception:
        def _infer_extended_frontmatter(fname):
            return {"title": fname, "scope": "workspace", "category": "misc"}

    for i, mem in enumerate(memories[:8]):
        if not isinstance(mem, dict):
            continue
        mtype = mem.get("type", "unknown")
        title = mem.get("title", f"memory_{i}")
        content = mem.get("content", "")
        if not content:
            continue

        h = _memory_hash(mtype, content)
        if h in existing_hashes:
            skipped_dup += 1
            continue
        existing_hashes.add(h)

        # 生成文件名:前缀 + 安全 title
        prefix = TYPE_TO_WIKI_PREFIX.get(mtype, "概念-")
        safe_t = _safe_title(title)
        fname = f"{prefix}{safe_t}.md"
        fpath = os.path.join(wiki_path, fname)

        # 命名冲突 → 追加 hash 短缀
        if os.path.exists(fpath):
            fname = f"{prefix}{safe_t}-{h[:8]}.md"
            fpath = os.path.join(wiki_path, fname)

        # frontmatter 推断
        ext = _infer_extended_frontmatter(fname)

        # 组装 wiki 页
        page = (
            f"---\n"
            f"title: {ext['title']}\n"
            f"source: 啄木鸟评审提取\n"
            f"created: {today}\n"
            f"updated: {today}\n"
            f"tags: [memory/{mtype}, extracted/auto]\n"
            f"sources: 1\n"
            f"scope: {ext['scope']}\n"
            f"category: {ext['category']}\n"
            f"extracted_from: {prd_name}\n"
            f"extracted_reviewer: {reviewer}\n"
            f"content_hash: {h}\n"
            f"---\n\n"
            f"# {title}\n\n"
            f"{content}\n\n"
            f"> 本页面由啄木鸟自动从 `{prd_name}` 评审会话中提取 ({today})\n"
        )

        try:
            with open(fpath, "w", encoding="utf-8") as f:
                f.write(page)
            saved.append({
                "type": mtype, "title": title, "content": content,
                "prd_name": prd_name, "wiki_file": fname,
                "extracted_at": datetime.now().isoformat(),
                "content_hash": h,
            })
        except OSError as e:
            log.warning(f"写 wiki 记忆失败 {fname}: {e}")

    if saved:
        log.info(f"[Wiki] 提取 {len(saved)} 条评审记忆 → {wiki_path}" +
                 (f" (跳过 {skipped_dup} 条重复)" if skipped_dup else ""))
    elif skipped_dup:
        log.info(f"[Wiki] 本次评审记忆全部为重复 ({skipped_dup} 条),未写入")

    return saved


def _parse_wiki_memory_page(fpath):
    """解析一个 wiki 记忆页面的 frontmatter + body,返回 dict 或 None

    P1: 只识别带 tags: [memory/xxx, extracted/auto] 的页面作为"记忆"
    """
    try:
        with open(fpath, "r", encoding="utf-8") as f:
            content = f.read()
    except (OSError, UnicodeDecodeError):
        return None

    if not content.startswith("---"):
        return None
    end = content.find("---", 3)
    if end == -1:
        return None

    fm_section = content[3:end]
    body = content[end + 3:].strip()

    # 只识别 memory/* tag 的页面
    if not re.search(r"memory/", fm_section):
        return None

    # 解析简单 frontmatter(不引入 yaml 依赖)
    fm = {}
    for line in fm_section.split("\n"):
        m = re.match(r"^(\w[\w_]*):\s*(.+?)\s*$", line)
        if m:
            fm[m.group(1)] = m.group(2).strip()

    # 提取 type(从 tags 里)
    mtype = "unknown"
    tags_line = fm.get("tags", "")
    m = re.search(r"memory/(\w+)", tags_line)
    if m:
        mtype = m.group(1)

    # body 的第一段作为 content(跳过 # title 行)
    content_lines = []
    for line in body.split("\n"):
        if line.startswith("# "):
            continue
        if line.startswith(">"):
            break  # 截到自动生成签名之前
        content_lines.append(line)
    content_text = "\n".join(content_lines).strip()

    # 优先用 frontmatter 里的 content_hash(迁移时写入);否则现算
    content_hash = fm.get("content_hash", "") or _memory_hash(mtype, content_text)

    return {
        "type": mtype,
        "title": fm.get("title", ""),
        "content": content_text,
        "prd_name": fm.get("extracted_from", ""),
        "reviewer": fm.get("extracted_reviewer", ""),
        "extracted_at": fm.get("created", fm.get("updated", "")),
        "wiki_file": os.path.basename(fpath),
        "content_hash": content_hash,
        "_mtime": os.path.getmtime(fpath),
    }


def load_memories_for_context(workspace, max_items=10, reviewer=None, wiki_path=None):
    """加载记忆用于注入评审上下文

    P0 (Phase 5 memory cleanup): 支持 reviewer 过滤参数
    P1 (Phase 5 memory cleanup): 优先读 wiki/*.md 里带 memory/* tag 的页面,
                                  失败降级读老 JSON 做向后兼容

    Args:
        workspace: 工作目录
        max_items: 最多加载多少条记忆
        reviewer: 若提供,额外加载该 reviewer 专属的偏好记忆
        wiki_path: wiki 目录路径,若提供则从这里读记忆页
    """
    all_memories = []
    seen_hashes = set()  # P1: 双源去重 — wiki 和老 JSON 同一条(content_hash 相同)只保留一份

    # --- P1: 优先从 wiki/ 读记忆页 ---
    if wiki_path and os.path.isdir(wiki_path):
        for fname in os.listdir(wiki_path):
            if not fname.endswith(".md"):
                continue
            if not any(fname.startswith(p) for p in TYPE_TO_WIKI_PREFIX.values()):
                continue
            parsed = _parse_wiki_memory_page(os.path.join(wiki_path, fname))
            if not parsed:
                continue
            h = parsed.get("content_hash", "")
            if h and h in seen_hashes:
                continue
            if h:
                seen_hashes.add(h)
            all_memories.append(parsed)

    # --- 降级:从老 JSON 读(向后兼容,已迁移的会被 hash 去重跳过) ---
    mem_dir = get_memory_dir(workspace)
    if os.path.isdir(mem_dir):
        for fname in sorted(os.listdir(mem_dir), reverse=True):
            if not fname.endswith(".json"):
                continue
            fpath = os.path.join(mem_dir, fname)
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except (json.JSONDecodeError, OSError):
                continue
            # P1: 老 JSON 可能没 content_hash,现算一个用于去重
            h = data.get("content_hash") or _memory_hash(data.get("type", ""), data.get("content", ""))
            if h and h in seen_hashes:
                continue
            if h:
                seen_hashes.add(h)
            data["_mtime"] = os.path.getmtime(fpath)
            all_memories.append(data)

    if not all_memories:
        return ""

    # 按 mtime 排序(新的在前)
    all_memories.sort(key=lambda m: m.get("_mtime", 0), reverse=True)

    # 分流:reviewer 偏好 vs 普通记忆
    memories = []
    reviewer_prefs = []
    for mem in all_memories:
        mtype = mem.get("type", "")
        if mtype == "reviewer":
            # reviewer 类型单独收集
            if reviewer is None or mem.get("reviewer", "") == reviewer or reviewer in mem.get("content", ""):
                reviewer_prefs.append(mem)
            continue
        if len(memories) < max_items:
            memories.append(mem)

    if not memories and not reviewer_prefs:
        return ""

    lines = []
    if memories:
        lines.append("## 评审记忆（来自历史评审）")
        for mem in memories:
            mtype = mem.get("type", "")
            title = mem.get("title", "")
            content = mem.get("content", "")
            wiki_ref = f" [[{mem['wiki_file'][:-3]}]]" if mem.get("wiki_file") else ""
            lines.append(f"- [{mtype}] **{title}**{wiki_ref}: {content}")

    if reviewer_prefs:
        if lines:
            lines.append("")
        label = f"（{reviewer}）" if reviewer else ""
        lines.append(f"## 审阅人偏好{label}")
        for mem in reviewer_prefs[:5]:
            title = mem.get("title", "")
            content = mem.get("content", "")
            lines.append(f"- **{title}**: {content}")
        latest = reviewer_prefs[0].get("extracted_at", "")
        if latest:
            try:
                # 兼容 iso 和 YYYY-MM-DD 两种格式
                try:
                    dt = datetime.fromisoformat(latest)
                except ValueError:
                    dt = datetime.strptime(latest, "%Y-%m-%d")
                days = (datetime.now() - dt).days
                if days > 30:
                    lines.append(f"\n[偏好记录于 {days} 天前,可能已过时]")
            except ValueError:
                pass

    return "\n".join(lines)
