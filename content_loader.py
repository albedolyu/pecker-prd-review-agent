"""
PRD / Wiki 内容加载 + 分支名规整 — 从 run_session.py 抽出

纯 IO 函数,无副作用依赖,适合单测覆盖。
"""

import os
import re
import subprocess
from typing import Dict, List, Optional, Tuple


def load_prd_content(workspace: str) -> Tuple[Optional[str], List[str]]:
    """读取 workspace/prd/ 下所有 .md 文件,返回 (prd_content, prd_files)。

    无 .md 文件时返回 (None, [])。
    多个文件用 '---' 分隔,文件名作为二级标题。
    """
    prd_dir = os.path.join(workspace, "prd")
    prd_files = [f for f in os.listdir(prd_dir) if f.endswith(".md")] if os.path.isdir(prd_dir) else []
    if not prd_files:
        return None, []
    prd_parts = []
    for pf in sorted(prd_files):
        with open(os.path.join(prd_dir, pf), "r", encoding="utf-8") as f:
            prd_parts.append(f"## {pf}\n\n{f.read()}")
    return "\n\n---\n\n".join(prd_parts), prd_files


# 修法 C (2026-04-26): 外挂 canonical wiki 默认路径
#
# PM 已经在 fengniao_wiki_frontmatter_batch 里把 51 个风鸟代码库 wiki 文件标了
# `authority: canonical`, 但之前 production code 0 处读 PECKER_EXTERNAL_CANONICAL_WIKI
# 这个 env (script docstring 说"已接通"但实际未接). 这里给一个默认值, 让单机 PM
# 不需要显式 export 也能享受 canonical wiki.
#
# 跨环境兼容: 路径不存在静默跳过 (CI/同事机器不破); 显式 env="" 完全不加载外挂.
DEFAULT_EXTERNAL_CANONICAL_WIKI = r"C:/Users/20834/Desktop/代码项目/风鸟代码库/wiki"


def _resolve_external_canonical_wiki() -> str:
    """读取 PECKER_EXTERNAL_CANONICAL_WIKI env, 兜底默认.

    返回值:
      - 存在的目录路径 → caller 加载它
      - "" → 不加载 (env 显式空 / 默认路径不存在)
    """
    raw = os.environ.get("PECKER_EXTERNAL_CANONICAL_WIKI")
    if raw is None:
        candidate = DEFAULT_EXTERNAL_CANONICAL_WIKI
    else:
        candidate = raw.strip()
    if candidate and os.path.isdir(candidate):
        return candidate
    return ""


def load_wiki_pages(wiki_path: str) -> Dict[str, str]:
    """读取 wiki 目录下所有 .md 页面(排除 index/log/scratchpad),返回 dict。

    key 为去掉 .md 后缀的文件名,value 为全文。
    目录不存在时返回 {}。

    修法 C: 同时合并外挂 canonical wiki (PECKER_EXTERNAL_CANONICAL_WIKI) — workspace
    内的同名 page 优先 (PM 本地 override > 全局 canonical), 路径不存在静默跳过.
    """
    wiki_pages: Dict[str, str] = {}

    # 先加载外挂 canonical (优先级低), workspace 内同名会覆盖
    external_path = _resolve_external_canonical_wiki()
    if external_path:
        for wf in os.listdir(external_path):
            if wf.endswith(".md") and wf not in ("index.md", "log.md", "_scratchpad.md"):
                wp = os.path.join(external_path, wf)
                with open(wp, "r", encoding="utf-8", errors="replace") as f:
                    wiki_pages[wf.replace(".md", "")] = f.read()

    # 再加载 workspace 内 wiki, 同名 key 覆盖外挂 (本地优先)
    if os.path.isdir(wiki_path):
        for wf in os.listdir(wiki_path):
            if wf.endswith(".md") and wf not in ("index.md", "log.md", "_scratchpad.md"):
                wp = os.path.join(wiki_path, wf)
                with open(wp, "r", encoding="utf-8", errors="replace") as f:
                    wiki_pages[wf.replace(".md", "")] = f.read()
    return wiki_pages


def sanitize_branch_name(name: str) -> str:
    """将中文/特殊字符转为 git 安全的分支名。

    - 允许的字符: 字母数字、中文、下划线、连字符
    - 连续的非法字符折叠成单个连字符
    - 首尾连字符去除
    - 空字符串返回 'unnamed'
    """
    name = re.sub(r"[^\w\u4e00-\u9fff-]", "-", name)
    name = re.sub(r"-+", "-", name).strip("-")
    return name or "unnamed"


def wiki_pull(wiki_path: str) -> None:
    """评审开始前拉取最新知识库,非 git 仓库静默跳过。

    失败不抛异常,只打印日志,避免阻塞评审流程。
    """
    if not os.path.isdir(os.path.join(wiki_path, ".git")):
        return
    result = subprocess.run(
        ["git", "pull", "--rebase", "--autostash"],
        capture_output=True, text=True, cwd=wiki_path,
    )
    if result.returncode == 0:
        print(f"[wiki] 已同步最新知识库")
    else:
        print(f"[wiki] pull 失败（继续评审）: {result.stderr.strip()[:80]}")
