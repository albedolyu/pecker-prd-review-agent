"""
kakapo_dream.py -- 鸮鹦(Kakapo) Wiki Dream Agent
啄木鸟知识库的夜间巡逻员，负责定期扫描、整理、修复 wiki 知识库。

四阶段工作流：Orient -> Gather -> Consolidate -> Prune/Index
灵感来自 Claude Code 的 Auto Dream 设计。
"""

import os
import sys
import re
import json
import time
import argparse
import datetime
import difflib
from collections import defaultdict
from pathlib import Path

# ============================================================
# ASCII Art
# ============================================================

KAKAPO_ART = r"""
      ___
     /   \
    | o o |    ~  鸮鹦 Kakapo  ~
    |  >  |    不会飞的夜行鹦鹉
     \___/     但能整理整片森林
      | |
     _/ \_
"""

# ============================================================
# 常量
# ============================================================

LOCK_FILE = ".consolidation.lock"
LOCK_STALE_SECONDS = 3600  # 1小时后锁自动过期

# wiki 页面命名前缀规范
VALID_PREFIXES = ("概念-", "场景-", "竞品-", "约束-", "决策-", "实体-")

# frontmatter 必需字段
REQUIRED_FRONTMATTER = ["source", "created", "updated", "tags"]

# 过时判定阈值（天）
STALE_DAYS = 90

# 重复页面相似度阈值
SIMILARITY_THRESHOLD = 0.70

# 排除的特殊页面（不参与健康检查的命名规范检测）
EXCLUDED_FILES = {"index.md", "log.md", "_scratchpad.md"}


# ============================================================
# 路径安全检查
# ============================================================

def _safe_path(wiki_path, target):
    """确保目标路径在 wiki_path 内，防止路径穿越"""
    wiki_real = os.path.realpath(wiki_path)
    target_real = os.path.realpath(os.path.join(wiki_path, target))
    if not (target_real + os.sep).startswith(wiki_real + os.sep):
        raise ValueError(f"路径越界: {target}")
    return target_real


# ============================================================
# 1. 并发锁
# ============================================================

def try_acquire_lock(wiki_path):
    """尝试获取整理锁，成功返回 True"""
    lock_path = _safe_path(wiki_path, LOCK_FILE)

    # 先检查是否有过期锁
    if os.path.exists(lock_path) and is_lock_stale(wiki_path):
        os.remove(lock_path)

    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, json.dumps({"pid": os.getpid(), "time": time.time()}).encode("utf-8"))
        os.close(fd)
        return True
    except FileExistsError:
        return False


def release_lock(wiki_path):
    """释放整理锁"""
    lock_path = _safe_path(wiki_path, LOCK_FILE)
    if os.path.exists(lock_path):
        os.remove(lock_path)


def is_lock_stale(wiki_path):
    """检查锁是否已过期（超过 1 小时）"""
    lock_path = _safe_path(wiki_path, LOCK_FILE)
    if not os.path.exists(lock_path):
        return False
    try:
        with open(lock_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return (time.time() - data.get("time", 0)) > LOCK_STALE_SECONDS
    except (json.JSONDecodeError, OSError):
        return True


# ============================================================
# 辅助函数
# ============================================================

def _list_wiki_pages(wiki_path):
    """列出 wiki 目录下所有 .md 文件（仅文件名，不含路径）"""
    pages = []
    for f in os.listdir(wiki_path):
        if f.endswith(".md") and os.path.isfile(os.path.join(wiki_path, f)):
            pages.append(f)
    return pages


def _read_page(wiki_path, filename):
    """读取页面内容"""
    path = _safe_path(wiki_path, filename)
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def _parse_frontmatter(content):
    """解析 YAML frontmatter，返回 (fields_dict, has_frontmatter)"""
    if not content.startswith("---"):
        return {}, False

    end = content.find("---", 3)
    if end == -1:
        return {}, False

    fm_text = content[3:end].strip()
    fields = {}
    for line in fm_text.split("\n"):
        line = line.strip()
        if ":" in line:
            key = line.split(":", 1)[0].strip()
            val = line.split(":", 1)[1].strip()
            fields[key] = val
    return fields, True


def _extract_wiki_links(content):
    """提取页面中所有 [[链接]] 目标"""
    return re.findall(r'\[\[([^\]]+)\]\]', content)


def _page_name_to_file(name):
    """wiki 链接名 -> 文件名（加 .md 后缀）"""
    if not name.endswith(".md"):
        return name + ".md"
    return name


def _file_to_page_name(filename):
    """文件名 -> wiki 链接名（去 .md 后缀）"""
    if filename.endswith(".md"):
        return filename[:-3]
    return filename


def _get_file_mtime(wiki_path, filename):
    """获取文件修改时间"""
    path = os.path.join(wiki_path, filename)
    try:
        return datetime.datetime.fromtimestamp(os.path.getmtime(path))
    except OSError:
        return None


def _text_similarity(text1, text2):
    """计算两段文本的相似度（SequenceMatcher ratio）"""
    return difflib.SequenceMatcher(None, text1, text2).ratio()


# ============================================================
# 2. Wiki 健康检查（Orient + Gather）
# ============================================================

def scan_wiki_health(wiki_path):
    """
    扫描 wiki 目录，返回 WikiHealthReport 字典。
    检查项：孤立页面、断链、命名不规范、缺少 frontmatter、
    过时内容、矛盾检测、重复页面。
    """
    pages = _list_wiki_pages(wiki_path)
    page_set = set(pages)  # 所有存在的文件名
    page_name_set = {_file_to_page_name(p) for p in pages}  # 不带 .md

    # 构建入链/出链映射
    outlinks = {}  # filename -> [链接目标名]
    inlinks = defaultdict(set)  # filename -> set(被哪些文件引用)
    page_contents = {}  # filename -> content

    for p in pages:
        content = _read_page(wiki_path, p)
        page_contents[p] = content
        links = _extract_wiki_links(content)
        outlinks[p] = links
        for link in links:
            target_file = _page_name_to_file(link)
            inlinks[target_file].add(p)

    total_links = sum(len(v) for v in outlinks.values())

    report = {
        "total_pages": len(pages),
        "total_links": total_links,
        "orphan_pages": [],
        "broken_links": [],
        "naming_issues": [],
        "missing_frontmatter": [],
        "stale_pages": [],
        "potential_duplicates": [],
        "potential_contradictions": [],
        "missing_crossrefs": [],
        "missing_concepts": [],
    }

    now = datetime.datetime.now()

    for p in pages:
        if p in EXCLUDED_FILES:
            continue

        content = page_contents[p]
        fm, has_fm = _parse_frontmatter(content)

        # --- 孤立页面：没有任何入链 ---
        if p not in inlinks or len(inlinks[p]) == 0:
            # index.md 引用不算（因为 index 会列所有页面）
            non_index_refs = {src for src in inlinks.get(p, set()) if src != "index.md"}
            if not non_index_refs:
                report["orphan_pages"].append({
                    "file": p,
                    "reason": "没有其他页面引用此页面"
                })

        # --- 断链：引用了不存在的页面 ---
        for link in outlinks.get(p, []):
            target_file = _page_name_to_file(link)
            if target_file not in page_set and link not in page_name_set:
                report["broken_links"].append({
                    "file": p,
                    "target": link
                })

        # --- 命名不规范 ---
        if not any(p.startswith(prefix) for prefix in VALID_PREFIXES):
            # 建议一个前缀
            suggestion = _suggest_prefix(p, content)
            report["naming_issues"].append({
                "file": p,
                "suggestion": suggestion
            })

        # --- 缺少 frontmatter ---
        if not has_fm:
            report["missing_frontmatter"].append({
                "file": p,
                "missing_fields": REQUIRED_FRONTMATTER[:]
            })
        else:
            missing = [f for f in REQUIRED_FRONTMATTER if f not in fm]
            if missing:
                report["missing_frontmatter"].append({
                    "file": p,
                    "missing_fields": missing
                })

        # --- 过时内容 ---
        updated_str = fm.get("updated", "")
        last_updated = None
        if updated_str:
            try:
                last_updated = datetime.datetime.strptime(updated_str, "%Y-%m-%d")
            except ValueError:
                pass
        if last_updated is None:
            last_updated = _get_file_mtime(wiki_path, p)
        if last_updated and (now - last_updated).days > STALE_DAYS:
            report["stale_pages"].append({
                "file": p,
                "last_updated": last_updated.strftime("%Y-%m-%d")
            })

    # --- 重复页面检测 ---
    content_pages = [(p, page_contents[p]) for p in pages if p not in EXCLUDED_FILES]
    for i in range(len(content_pages)):
        for j in range(i + 1, len(content_pages)):
            p1, c1 = content_pages[i]
            p2, c2 = content_pages[j]
            # 先比标题（文件名去前缀去后缀）
            name1 = re.sub(r'^(概念|场景|竞品|约束|决策|实体)-', '', _file_to_page_name(p1))
            name2 = re.sub(r'^(概念|场景|竞品|约束|决策|实体)-', '', _file_to_page_name(p2))
            title_sim = _text_similarity(name1, name2)
            # 内容相似度（截取正文前 2000 字符比对，避免大文件性能问题）
            body1 = _strip_frontmatter(c1)[:2000]
            body2 = _strip_frontmatter(c2)[:2000]
            content_sim = _text_similarity(body1, body2)
            # 标题高度相似或内容高度相似
            sim = max(title_sim, content_sim)
            if sim >= SIMILARITY_THRESHOLD:
                report["potential_duplicates"].append({
                    "file1": p1,
                    "file2": p2,
                    "similarity": round(sim, 2)
                })

    # --- 矛盾检测（简单关键词交叉） ---
    # 提取每个页面的"定义性"关键词（标题中的核心名词）
    definitions = {}  # 核心概念 -> [(file, 定义句)]
    for p in pages:
        if p in EXCLUDED_FILES:
            continue
        content = page_contents[p]
        body = _strip_frontmatter(content)
        # 找 "# 标题" 后面的第一段作为定义
        lines = body.strip().split("\n")
        title_keyword = re.sub(r'^(概念|场景|竞品|约束|决策|实体)-', '', _file_to_page_name(p))
        # 取正文前 300 字符作为定义区域
        definition_zone = body[:300]
        if title_keyword:
            definitions.setdefault(title_keyword, []).append((p, definition_zone))

    # 同一个关键词出现在多个页面，且定义区域相似度低（可能矛盾）
    for keyword, items in definitions.items():
        if len(items) < 2:
            continue
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                f1, def1 = items[i]
                f2, def2 = items[j]
                sim = _text_similarity(def1, def2)
                # 相似度太低说明对同一概念说法不同 -> 可能矛盾
                if 0.1 < sim < 0.5:
                    report["potential_contradictions"].append({
                        "file1": f1,
                        "file2": f2,
                        "keyword": keyword
                    })

    # --- 交叉引用补全建议 ---
    # 提取每个页面的中文关键词（2-4字），用前3000字符
    CROSSREF_STOPWORDS = {"文档", "说明", "需求", "版本", "内容", "数据", "系统", "功能",
                          "用户", "信息", "通过", "支持", "进行", "使用", "相关", "以下",
                          "如下", "其中", "包括", "目前", "对于", "可以"}
    page_keywords = {}  # filename -> set(关键词)
    crossref_pages = [p for p in pages if p not in {"index.md", "log.md"}]
    for p in crossref_pages:
        body = _strip_frontmatter(page_contents[p])[:3000]
        kws = set(re.findall(r'[\u4e00-\u9fff]{2,4}', body)) - CROSSREF_STOPWORDS
        page_keywords[p] = kws

    # 构建每个页面的出链目标文件集合（用于判断是否已有链接）
    outlink_files = {}
    for p in crossref_pages:
        targets = set()
        for link in outlinks.get(p, []):
            targets.add(_page_name_to_file(link))
        outlink_files[p] = targets

    for i in range(len(crossref_pages)):
        for j in range(i + 1, len(crossref_pages)):
            p1 = crossref_pages[i]
            p2 = crossref_pages[j]
            shared = page_keywords[p1] & page_keywords[p2]
            if len(shared) >= 5:
                # 检查是否 A->B 或 B->A 已有链接
                a_links_b = p2 in outlink_files.get(p1, set())
                b_links_a = p1 in outlink_files.get(p2, set())
                if not a_links_b and not b_links_a:
                    shared_list = sorted(shared)
                    report["missing_crossrefs"].append({
                        "file1": p1,
                        "file2": p2,
                        "shared_keywords": shared_list,
                        "count": len(shared_list),
                    })

    # --- 缺失概念发现 ---
    # 收集已有概念（所有 [[链接]] 目标 + 所有页面标题）
    existing_concepts = set()
    for p in pages:
        # 页面标题 = 文件名去前缀去后缀
        title = re.sub(r'^(概念|场景|竞品|约束|决策|实体)-', '', _file_to_page_name(p))
        existing_concepts.add(title)
    for p in pages:
        for link in outlinks.get(p, []):
            existing_concepts.add(link)

    # 统计所有关键词（3-4字）在各页面中的出现
    concept_pages = [p for p in pages if p not in {"index.md", "log.md"}]
    keyword_occurrences = defaultdict(set)  # keyword -> set(出现的文件名)
    for p in concept_pages:
        body = _strip_frontmatter(page_contents[p])[:3000]
        kws = set(re.findall(r'[\u4e00-\u9fff]{3,4}', body)) - CROSSREF_STOPWORDS
        for kw in kws:
            keyword_occurrences[kw].add(p)

    for kw, files in keyword_occurrences.items():
        if len(files) >= 3 and kw not in existing_concepts:
            report["missing_concepts"].append({
                "concept": kw,
                "mentioned_in": sorted(files),
                "count": len(files),
            })

    return report


def _strip_frontmatter(content):
    """去除 frontmatter，返回正文"""
    if not content.startswith("---"):
        return content
    end = content.find("---", 3)
    if end == -1:
        return content
    return content[end + 3:].strip()


def _suggest_prefix(filename, content):
    """根据文件名和内容猜测合适的命名前缀"""
    name = _file_to_page_name(filename)
    lower_content = content.lower()

    # 关键词匹配
    if any(w in lower_content for w in ["定义", "规则", "术语", "概念"]):
        return f"建议重命名为: 概念-{name}.md"
    if any(w in lower_content for w in ["场景", "用户故事", "流程", "操作"]):
        return f"建议重命名为: 场景-{name}.md"
    if any(w in lower_content for w in ["竞品", "对比", "企查查", "天眼查"]):
        return f"建议重命名为: 竞品-{name}.md"
    if any(w in lower_content for w in ["约束", "限制", "ddl", "表结构", "api"]):
        return f"建议重命名为: 约束-{name}.md"
    if any(w in lower_content for w in ["决策", "决定", "选择", "方案"]):
        return f"建议重命名为: 决策-{name}.md"
    if any(w in lower_content for w in ["实体", "系统", "产品", "角色"]):
        return f"建议重命名为: 实体-{name}.md"
    return f"建议根据内容添加前缀（概念/场景/竞品/约束/决策/实体）: {name}.md"


# ============================================================
# 3. 自动修复（Consolidate）
# ============================================================

def auto_fix(wiki_path, health_report, dry_run=True):
    """
    根据健康报告自动修复问题。
    dry_run=True 时只打印不执行。
    返回变更记录列表。
    """
    changes = []

    # --- 断链修复：创建占位页面 ---
    created_targets = set()
    for item in health_report.get("broken_links", []):
        target = item["target"]
        target_file = _page_name_to_file(target)
        if target_file in created_targets:
            continue
        created_targets.add(target_file)

        now_str = datetime.date.today().isoformat()
        placeholder = (
            f"---\n"
            f"source: 自动修复\n"
            f"created: {now_str}\n"
            f"updated: {now_str}\n"
            f"tags: [status/待补充]\n"
            f"---\n\n"
            f"# {target}\n\n"
            f"> 此页面由鸮鹦自动创建，因为有其他页面引用了 [[{target}]] 但该页面不存在。\n"
            f"> 请补充具体内容。\n"
        )

        path = _safe_path(wiki_path, target_file)
        if dry_run:
            changes.append({"type": "create_placeholder", "file": target_file, "dry_run": True})
            print(f"  [DRY RUN] 将创建占位页面: {target_file}")
        else:
            with open(path, "w", encoding="utf-8") as f:
                f.write(placeholder)
            changes.append({"type": "create_placeholder", "file": target_file, "dry_run": False})

    # --- 缺少 frontmatter：自动补充 ---
    for item in health_report.get("missing_frontmatter", []):
        filename = item["file"]
        missing = item["missing_fields"]
        path = _safe_path(wiki_path, filename)
        content = _read_page(wiki_path, filename)
        fm, has_fm = _parse_frontmatter(content)

        # 获取文件 mtime 作为 created/updated 的默认值
        mtime = _get_file_mtime(wiki_path, filename)
        mtime_str = mtime.strftime("%Y-%m-%d") if mtime else datetime.date.today().isoformat()
        now_str = datetime.date.today().isoformat()

        if not has_fm:
            # 整个 frontmatter 都没有，加上完整的
            new_fm = (
                f"---\n"
                f"source: 自动修复\n"
                f"created: {mtime_str}\n"
                f"updated: {now_str}\n"
                f"tags: [status/待验证]\n"
                f"---\n\n"
            )
            new_content = new_fm + content
        else:
            # 有 frontmatter 但缺字段，在已有 frontmatter 中补充
            end = content.find("---", 3)
            fm_section = content[3:end]
            for field in missing:
                if field == "source":
                    fm_section += "source: 自动修复\n"
                elif field == "created":
                    fm_section += f"created: {mtime_str}\n"
                elif field == "updated":
                    fm_section += f"updated: {now_str}\n"
                elif field == "tags":
                    fm_section += "tags: [status/待验证]\n"
            new_content = "---\n" + fm_section + "---" + content[end + 3:]

        if dry_run:
            changes.append({"type": "fix_frontmatter", "file": filename, "missing": missing, "dry_run": True})
            print(f"  [DRY RUN] 将补充 frontmatter: {filename} (缺: {', '.join(missing)})")
        else:
            with open(path, "w", encoding="utf-8") as f:
                f.write(new_content)
            changes.append({"type": "fix_frontmatter", "file": filename, "missing": missing, "dry_run": False})

    # --- 命名不规范：建议重命名（仅打印建议，不自动改名） ---
    for item in health_report.get("naming_issues", []):
        changes.append({"type": "naming_suggestion", "file": item["file"], "suggestion": item["suggestion"]})
        if dry_run:
            print(f"  [DRY RUN] {item['suggestion']}")
        else:
            print(f"  [建议] {item['suggestion']}（需手动重命名）")

    # --- 孤立页面：在 index.md 中补充引用 ---
    orphans = [item["file"] for item in health_report.get("orphan_pages", [])]
    if orphans:
        index_path = _safe_path(wiki_path, "index.md")
        if os.path.exists(index_path):
            index_content = _read_page(wiki_path, "index.md")
        else:
            index_content = "# 知识库索引\n\n"

        # 找出 index 中已有的链接
        existing_links = set(_extract_wiki_links(index_content))
        new_orphans = [o for o in orphans if _file_to_page_name(o) not in existing_links]

        if new_orphans:
            if dry_run:
                for o in new_orphans:
                    changes.append({"type": "add_to_index", "file": o, "dry_run": True})
                    print(f"  [DRY RUN] 将在 index.md 中添加: [[{_file_to_page_name(o)}]]")
            else:
                append_lines = "\n## 待整理\n\n"
                for o in new_orphans:
                    name = _file_to_page_name(o)
                    append_lines += f"- [[{name}]]\n"
                    changes.append({"type": "add_to_index", "file": o, "dry_run": False})

                with open(index_path, "w", encoding="utf-8") as f:
                    f.write(index_content.rstrip() + "\n" + append_lines)

    return changes


# ============================================================
# 4. 索引重建（Prune/Index）
# ============================================================

def rebuild_index(wiki_path):
    """
    重建 index.md：
    - 扫描所有 .md 文件
    - 按命名前缀分类
    - 每个条目一行: - [[页面名]] -- 一句话摘要
    - 末尾附加知识森林状态
    """
    pages = _list_wiki_pages(wiki_path)
    # 排除特殊页面
    pages = [p for p in pages if p not in EXCLUDED_FILES]

    # 分类
    categories = {
        "概念": [],
        "场景": [],
        "竞品": [],
        "约束": [],
        "决策": [],
        "实体": [],
        "其他": [],
    }

    for p in sorted(pages):
        content = _read_page(wiki_path, p)
        summary = _extract_summary(content)
        name = _file_to_page_name(p)

        placed = False
        for prefix in ("概念", "场景", "竞品", "约束", "决策", "实体"):
            if p.startswith(f"{prefix}-"):
                categories[prefix].append((name, summary))
                placed = True
                break
        if not placed:
            categories["其他"].append((name, summary))

    # 构建 index 内容
    lines = ["# 知识库索引\n"]
    lines.append(f"> 自动生成于 {datetime.date.today().isoformat()}，由鸮鹦维护\n")

    category_labels = {
        "概念": "概念页",
        "场景": "场景页",
        "竞品": "竞品页",
        "约束": "约束页",
        "决策": "决策页",
        "实体": "实体页",
        "其他": "其他页面",
    }

    for cat_key in ("概念", "场景", "竞品", "约束", "决策", "实体", "其他"):
        items = categories[cat_key]
        if not items:
            continue
        lines.append(f"\n## {category_labels[cat_key]}（{len(items)}）\n")
        for name, summary in items:
            lines.append(f"- [[{name}]] -- {summary}")

    # 知识森林状态
    try:
        # 尝试调用 easter_eggs.py 的 format_forest_status
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from easter_eggs import format_forest_status
        status = format_forest_status(wiki_path)
        status_md = status.replace("--- 知识森林状态 ---", "## 知识森林状态")
        lines.append(f"\n{status_md.strip()}")
    except ImportError:
        # easter_eggs 不可用，用简化版
        lines.append(f"\n## 知识森林状态\n")
        lines.append(f"  页面总数: {len(pages)}")

    content = "\n".join(lines) + "\n"

    index_path = _safe_path(wiki_path, "index.md")
    with open(index_path, "w", encoding="utf-8") as f:
        f.write(content)

    return len(pages)


def _extract_summary(content):
    """提取页面的一句话摘要（第一个非标题、非空行）"""
    body = _strip_frontmatter(content)
    for line in body.split("\n"):
        line = line.strip()
        if not line:
            continue
        if line.startswith("#"):
            continue
        if line.startswith(">"):
            continue
        if line.startswith("---"):
            continue
        # 截取前 60 个字符
        return line[:60] + ("..." if len(line) > 60 else "")
    return "(无摘要)"


# ============================================================
# 4.5 Ingest -- 导入新资料到 wiki
# ============================================================

# 中文停用词（来自 app.py scan_wiki_for_prd）
_INGEST_STOP_WORDS = {
    "文档", "说明", "需求", "版本", "内容", "数据", "系统", "功能",
    "用户", "信息", "通过", "支持", "进行", "使用", "相关", "以下",
    "如下", "其中",
}


def _extract_chinese_keywords(text, max_chars=5000):
    """从文本中提取 2-4 字中文关键词，去停用词，返回 set"""
    snippet = text[:max_chars]
    raw = re.findall(r'[\u4e00-\u9fff]{2,4}', snippet)
    return {w for w in raw if w not in _INGEST_STOP_WORDS}


def _infer_prefix(content):
    """根据资料内容推断 wiki 页面前缀"""
    lower = content[:3000].lower()
    if any(w in lower for w in ["定义", "规则", "术语", "概念"]):
        return "概念"
    if any(w in lower for w in ["场景", "用户故事", "流程", "操作"]):
        return "场景"
    if any(w in lower for w in ["竞品", "对比", "企查查", "天眼查"]):
        return "竞品"
    if any(w in lower for w in ["约束", "限制", "ddl", "表结构", "api"]):
        return "约束"
    if any(w in lower for w in ["决策", "决定", "选择", "方案"]):
        return "决策"
    if any(w in lower for w in ["实体", "产品", "角色"]):
        return "实体"
    return "场景"


def _derive_page_name(source_filename, content):
    """从源文件名推导 wiki 页面名（前缀-名称.md）"""
    base = os.path.splitext(os.path.basename(source_filename))[0]
    if any(base.startswith(p) for p in ("概念-", "场景-", "竞品-", "约束-", "决策-", "实体-")):
        return base + ".md"
    prefix = _infer_prefix(content)
    return f"{prefix}-{base}.md"


def ingest_source(wiki_path, source_path):
    """
    导入新资料到 wiki：
    1. 读取源文件
    2. 创建摘要页（frontmatter + 前 3000 字符占位）
    3. 扫描关联页面（中文关键词交集）
    4. 输出关联报告
    5. 追加 log.md
    6. 重建 index
    """
    source_path = os.path.abspath(source_path)
    if not os.path.isfile(source_path):
        print(f"错误: 源文件不存在: {source_path}")
        sys.exit(1)

    with open(source_path, "r", encoding="utf-8", errors="replace") as f:
        source_content = f.read()

    source_filename = os.path.basename(source_path)
    print(f"读取源文件: {source_filename} ({len(source_content)} 字符)\n")

    # --- 创建摘要页 ---
    page_name = _derive_page_name(source_filename, source_content)
    page_path = _safe_path(wiki_path, page_name)

    now_str = datetime.date.today().isoformat()
    summary_body = source_content[:3000]
    if len(source_content) > 3000:
        summary_body += "\n\n> **注意**: 以上为源文件前 3000 字符的摘要占位，建议用 LLM 精炼。\n"

    page_content = (
        f"---\n"
        f"source: {source_filename}\n"
        f"created: {now_str}\n"
        f"updated: {now_str}\n"
        f"tags: [status/新增]\n"
        f"---\n\n"
        f"# {_file_to_page_name(page_name)}\n\n"
        f"{summary_body}\n"
    )

    with open(page_path, "w", encoding="utf-8") as f:
        f.write(page_content)
    print(f"已创建摘要页: {page_name}\n")

    # --- 扫描关联页面 ---
    new_keywords = _extract_chinese_keywords(source_content)
    print(f"提取新资料关键词: {len(new_keywords)} 个\n")

    existing_pages = _list_wiki_pages(wiki_path)
    scan_pages = [p for p in existing_pages if p not in EXCLUDED_FILES and p != page_name]

    strong_related = []
    weak_related = []

    for p in scan_pages:
        content = _read_page(wiki_path, p)
        page_keywords = _extract_chinese_keywords(content)
        overlap = new_keywords & page_keywords
        hit_count = len(overlap)

        if hit_count >= 3:
            strong_related.append((p, hit_count, sorted(overlap)[:8]))
        elif hit_count >= 1:
            weak_related.append((p, hit_count, sorted(overlap)[:5]))

    strong_related.sort(key=lambda x: x[1], reverse=True)
    weak_related.sort(key=lambda x: x[1], reverse=True)

    # --- 输出关联报告 ---
    print("=== 关联页面分析报告 ===\n")

    if strong_related:
        print(f"### 强关联页面（命中 >=3 个关键词）共 {len(strong_related)} 个\n")
        for p, count, keywords in strong_related:
            kw_str = "、".join(keywords)
            print(f"  - {p}  (命中 {count} 个: {kw_str})")
            print(f"    -> 建议: 检查是否需要在该页面中引用 [[{_file_to_page_name(page_name)}]]")
        print()

    if weak_related:
        print(f"### 弱关联页面（命中 1-2 个关键词）共 {len(weak_related)} 个\n")
        for p, count, keywords in weak_related:
            kw_str = "、".join(keywords)
            print(f"  - {p}  (命中 {count} 个: {kw_str})")
        print()

    if not strong_related and not weak_related:
        print("未发现关联页面。\n")

    # --- 追加 log.md ---
    log_path = _safe_path(wiki_path, "log.md")
    if os.path.exists(log_path):
        existing_log = _read_page(wiki_path, "log.md")
    else:
        existing_log = "# 操作日志\n\n"

    log_entry = (
        f"## [{now_str}] ingest | {source_filename}\n\n"
        f"- 创建页面: `{page_name}`\n"
        f"- 强关联: {len(strong_related)} 个页面\n"
        f"- 弱关联: {len(weak_related)} 个页面\n"
    )

    with open(log_path, "w", encoding="utf-8") as f:
        f.write(existing_log.rstrip() + "\n\n" + log_entry + "\n")
    print("已追加 log.md\n")

    # --- 重建 index ---
    count = rebuild_index(wiki_path)
    print(f"索引重建完成，共收录 {count} 个页面。")

    return page_name


# ============================================================
# 5. 变更 Diff 报告
# ============================================================

def generate_diff_report(wiki_path, changes):
    """
    根据变更记录生成 diff 报告，写入 log.md，返回 markdown 摘要。
    """
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    # 统计
    created = [c for c in changes if c["type"] == "create_placeholder" and not c.get("dry_run")]
    fixed_fm = [c for c in changes if c["type"] == "fix_frontmatter" and not c.get("dry_run")]
    indexed = [c for c in changes if c["type"] == "add_to_index" and not c.get("dry_run")]
    naming = [c for c in changes if c["type"] == "naming_suggestion"]

    lines = [
        f"## [{now_str}] consolidation | 鸮鹦自动整理",
        "",
    ]

    if created:
        lines.append(f"### 创建占位页面 ({len(created)})")
        for c in created:
            lines.append(f"- `{c['file']}`")
        lines.append("")

    if fixed_fm:
        lines.append(f"### 修复 frontmatter ({len(fixed_fm)})")
        for c in fixed_fm:
            lines.append(f"- `{c['file']}` (补充: {', '.join(c.get('missing', []))})")
        lines.append("")

    if indexed:
        lines.append(f"### 添加到索引 ({len(indexed)})")
        for c in indexed:
            lines.append(f"- `{c['file']}`")
        lines.append("")

    if naming:
        lines.append(f"### 命名建议 ({len(naming)})")
        for c in naming:
            lines.append(f"- `{c['file']}`: {c['suggestion']}")
        lines.append("")

    if not any([created, fixed_fm, indexed, naming]):
        lines.append("无变更。\n")

    report_text = "\n".join(lines)

    # 写入 log.md
    log_path = _safe_path(wiki_path, "log.md")
    if os.path.exists(log_path):
        existing = _read_page(wiki_path, "log.md")
    else:
        existing = "# 操作日志\n\n"

    with open(log_path, "w", encoding="utf-8") as f:
        f.write(existing.rstrip() + "\n\n" + report_text + "\n")

    return report_text


# ============================================================
# 6. 定时触发逻辑
# ============================================================

def should_run_dream(wiki_path, min_hours=24, min_reviews=3):
    """
    判断是否应该执行整理：
    - 距离上次 consolidation 超过 min_hours
    - 期间有至少 min_reviews 次新评审
    """
    log_path = os.path.join(wiki_path, "log.md")
    if not os.path.exists(log_path):
        return True  # 从未执行过，需要执行

    try:
        with open(log_path, "r", encoding="utf-8") as f:
            content = f.read()
    except OSError:
        return True

    # 找最后一次 consolidation 的时间
    last_consolidation = None
    # 找所有 review 条目的时间
    review_times = []

    for line in content.split("\n"):
        line = line.strip()
        # 匹配 ## [YYYY-MM-DD HH:MM] consolidation | ... 或 ## [YYYY-MM-DD] consolidation | ...
        m = re.match(r'^## \[(\d{4}-\d{2}-\d{2}[\s\d:]*)\] consolidation', line)
        if m:
            try:
                ts = m.group(1).strip()
                if " " in ts:
                    last_consolidation = datetime.datetime.strptime(ts, "%Y-%m-%d %H:%M")
                else:
                    last_consolidation = datetime.datetime.strptime(ts, "%Y-%m-%d")
            except ValueError:
                pass

        # 匹配 review 条目
        m2 = re.match(r'^## \[(\d{4}-\d{2}-\d{2}[\s\d:]*)\] (review|ingest)', line)
        if m2:
            try:
                ts = m2.group(1).strip()
                if " " in ts:
                    t = datetime.datetime.strptime(ts, "%Y-%m-%d %H:%M")
                else:
                    t = datetime.datetime.strptime(ts, "%Y-%m-%d")
                review_times.append(t)
            except ValueError:
                pass

    if last_consolidation is None:
        return True  # 从未整理过

    now = datetime.datetime.now()
    hours_since = (now - last_consolidation).total_seconds() / 3600

    if hours_since < min_hours:
        return False  # 距离上次整理不够久

    # 统计上次整理后的评审次数
    recent_reviews = sum(1 for t in review_times if t > last_consolidation)
    return recent_reviews >= min_reviews


# ============================================================
# 7. 报告格式化（用于终端输出）
# ============================================================

def format_health_report(report):
    """将 WikiHealthReport 格式化为可读文本"""
    lines = [
        f"页面总数: {report['total_pages']}  |  双向链接: {report['total_links']} 条",
        "",
    ]

    sections = [
        ("orphan_pages", "孤立页面", lambda i: f"  - {i['file']} ({i['reason']})"),
        ("broken_links", "断链", lambda i: f"  - {i['file']} -> [[{i['target']}]]"),
        ("naming_issues", "命名不规范", lambda i: f"  - {i['file']}: {i['suggestion']}"),
        ("missing_frontmatter", "缺少 frontmatter", lambda i: f"  - {i['file']} (缺: {', '.join(i['missing_fields'])})"),
        ("stale_pages", "过时内容 (>90天)", lambda i: f"  - {i['file']} (最后更新: {i['last_updated']})"),
        ("potential_duplicates", "疑似重复页面", lambda i: f"  - {i['file1']} <-> {i['file2']} (相似度: {i['similarity']})"),
        ("potential_contradictions", "疑似矛盾", lambda i: f"  - {i['file1']} vs {i['file2']} (关键词: {i['keyword']})"),
        ("missing_crossrefs", "交叉引用补全建议", lambda i: f"  - {i['file1']} <-> {i['file2']} (共享关键词{i['count']}个: {', '.join(i['shared_keywords'][:5])}{'...' if i['count'] > 5 else ''})"),
        ("missing_concepts", "缺失概念", lambda i: f"  - 「{i['concept']}」出现在{i['count']}个页面: {', '.join(i['mentioned_in'])}"),
    ]

    total_issues = 0
    for key, label, formatter in sections:
        items = report.get(key, [])
        if items:
            total_issues += len(items)
            lines.append(f"### {label} ({len(items)})")
            for item in items:
                lines.append(formatter(item))
            lines.append("")

    return total_issues, "\n".join(lines)


# ============================================================
# CLI 入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="鸮鹦(Kakapo) Wiki Dream Agent -- 知识库夜间巡逻员"
    )
    parser.add_argument("--wiki-path", required=True, help="wiki 目录路径")
    parser.add_argument("--scan-only", action="store_true", help="只扫描不修复")
    parser.add_argument("--dry-run", action="store_true", help="预览修复但不执行")
    parser.add_argument("--rebuild-index", action="store_true", help="只重建索引")
    parser.add_argument("--ingest", metavar="FILE", help="导入新资料到 wiki 并分析关联页面")

    args = parser.parse_args()
    wiki_path = os.path.abspath(args.wiki_path)

    if not os.path.isdir(wiki_path):
        print(f"错误: wiki 目录不存在: {wiki_path}")
        sys.exit(1)

    # 启动画面
    print(KAKAPO_ART)
    print("鸮鹦开始夜间巡逻...\n")

    # --- 只重建索引模式 ---
    if args.rebuild_index:
        count = rebuild_index(wiki_path)
        print(f"索引重建完成，共收录 {count} 个页面。")
        print("\n森林已整理完毕，鸮鹦继续守护。")
        return

    # --- Ingest 模式：导入新资料 ---
    if args.ingest:
        page_name = ingest_source(wiki_path, args.ingest)
        print(f"\n鸮鹦已将 {os.path.basename(args.ingest)} 收入森林，新页面: {page_name}")
        print("森林已整理完毕，鸮鹦继续守护。")
        return

    # --- 获取锁 ---
    if not try_acquire_lock(wiki_path):
        print("另一只鸮鹦正在巡逻中，稍后再试。")
        sys.exit(1)

    try:
        # --- Phase 1: Orient + Gather ---
        print("=== Phase 1: 扫描知识库健康状态 ===\n")
        report = scan_wiki_health(wiki_path)
        total_issues, report_text = format_health_report(report)

        print(report_text)

        if total_issues == 0:
            print("知识库状态良好，没有发现需要整理的角落。")
        else:
            print(f"发现 {total_issues} 处需要整理的角落\n")

        # --- 只扫描模式到此结束 ---
        if args.scan_only:
            release_lock(wiki_path)
            print("\n森林已整理完毕，鸮鹦继续守护。")
            return

        # --- Phase 2: Consolidate ---
        if total_issues > 0:
            print("=== Phase 2: 自动修复 ===\n")
            dry_run = args.dry_run
            changes = auto_fix(wiki_path, report, dry_run=dry_run)

            if not dry_run and changes:
                # --- Phase 3: Diff 报告 ---
                print("\n=== Phase 3: 生成变更报告 ===\n")
                diff = generate_diff_report(wiki_path, changes)
                print(diff)

                # --- Phase 4: 重建索引 ---
                print("=== Phase 4: 重建索引 ===\n")
                count = rebuild_index(wiki_path)
                print(f"索引重建完成，共收录 {count} 个页面。")
            elif dry_run:
                print("\n[DRY RUN 模式] 以上操作未实际执行。去掉 --dry-run 参数可真正执行。")
        else:
            # 无问题也重建一下索引保持最新
            print("\n=== 重建索引 ===\n")
            count = rebuild_index(wiki_path)
            print(f"索引重建完成，共收录 {count} 个页面。")

    finally:
        release_lock(wiki_path)

    print("\n森林已整理完毕，鸮鹦继续守护。")


if __name__ == "__main__":
    main()
