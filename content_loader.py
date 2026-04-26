"""
PRD / Wiki 内容加载 + 分支名规整 — 从 run_session.py 抽出

纯 IO 函数,无副作用依赖,适合单测覆盖。
"""

import os
import re
import subprocess
from typing import Dict, List, Optional, Tuple

# wiki 加载的元文件白名单 — 不计入业务 wiki 内容
# (与 review.evidence_verify._META_WIKI_FILENAMES 保持语义一致, 但只在 wiki 模块内用,
# 这里独立放是为了避免循环依赖: evidence_verify / funnel_telemetry 都要调
# iter_wiki_files, 但都不能反向 import content_loader 之外的 review.* 符号)
_WIKI_META_FILENAMES = frozenset({
    "index.md", "log.md", "_scratchpad.md", "README.md", "TOC.md",
})


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


def iter_wiki_files(wiki_dir: str) -> List[str]:
    """统一 wiki 文件枚举入口 — 返回所有 wiki 文件的绝对路径 list.

    2026-04-27 P0-A 修法: 在此之前 evidence_verify 和 funnel_telemetry 都用
    `glob(workspace/wiki/*.md)` 自己扫, 不读外挂 canonical wiki, 也不递归子目录.
    导致即使 worker prompt 拿到 49 page (load_wiki_pages 已修), evidence_verify
    仍按 13 个 local page 判 sparse, authority_distribution 空 dict.

    本函数是 wiki 文件枚举的 single source of truth. caller (evidence_verify
    / funnel_telemetry / load_wiki_pages) 各自决定怎么算 key (basename / 子路径)
    + 怎么处理同名碰撞.

    合并语义:
      1. 先枚举外挂 canonical wiki (PECKER_EXTERNAL_CANONICAL_WIKI), os.walk 递归
      2. 再枚举 workspace local wiki_dir, os.listdir 不递归 (workspace 一般是平铺)
      3. 元文件 (index/log/_scratchpad/README/TOC) 跳过
      4. 不在此处去重: caller 决定语义 (evidence_verify 用 basename 去重 +
         workspace 优先; load_wiki_pages 用相对路径区分子目录同名)

    Args:
        wiki_dir: workspace/wiki 绝对路径. 不存在/不是目录时仅返回外挂部分.

    Returns:
        list of absolute file paths. 顺序: 先外挂 canonical (递归), 后 workspace local.
        caller 关心顺序时记得后到的覆盖前到的.
    """
    paths: List[str] = []

    # 1. 外挂 canonical (先加入, caller 同 key 应让 workspace 覆盖)
    external_path = _resolve_external_canonical_wiki()
    if external_path:
        for root, _dirs, files in os.walk(external_path):
            for wf in files:
                if not wf.endswith(".md"):
                    continue
                if wf in _WIKI_META_FILENAMES:
                    continue
                paths.append(os.path.join(root, wf))

    # 2. workspace local (后加入)
    if os.path.isdir(wiki_dir):
        for wf in os.listdir(wiki_dir):
            if not wf.endswith(".md"):
                continue
            if wf in _WIKI_META_FILENAMES:
                continue
            paths.append(os.path.join(wiki_dir, wf))

    return paths


def load_wiki_pages(wiki_path: str) -> Dict[str, str]:
    """读取 wiki 目录下所有 .md 页面(排除 index/log/scratchpad),返回 dict。

    key 为去掉 .md 后缀的文件名,value 为全文。
    目录不存在时返回 {}。

    修法 C: 同时合并外挂 canonical wiki (PECKER_EXTERNAL_CANONICAL_WIKI) — workspace
    内的同名 page 优先 (PM 本地 override > 全局 canonical), 路径不存在静默跳过.
    """
    wiki_pages: Dict[str, str] = {}

    # 先加载外挂 canonical (优先级低), workspace 内同名会覆盖
    #
    # P1 修法 (2026-04-26): 风鸟 wiki 是子目录结构 (api/ architecture/ concepts/ ...),
    # 顶层只有 index.md / log.md (白名单 exclude), os.listdir 不递归会拿 0 page —
    # calibration 数据 authority_distribution: {generated: 10, canonical: 0} 就是这个根因.
    # 改用 os.walk 递归, key 用相对路径 (forward slash 归一) 避免子目录间同名碰撞.
    external_path = _resolve_external_canonical_wiki()
    if external_path:
        for root, _dirs, files in os.walk(external_path):
            for wf in files:
                if not wf.endswith(".md"):
                    continue
                if wf in ("index.md", "log.md", "_scratchpad.md"):
                    continue
                wp = os.path.join(root, wf)
                rel = os.path.relpath(wp, external_path).replace(os.sep, "/")
                key = rel[:-3]  # 去 .md 后缀
                with open(wp, "r", encoding="utf-8", errors="replace") as f:
                    wiki_pages[key] = f.read()

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
