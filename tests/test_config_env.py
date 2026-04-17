"""
config/ 跨环境一致性测试 — 防止某个 env 漏定义关键常量

背景: 2026-04-16 session 2 的苍鹰交叉校验崩溃,根因是 GOSHAWK_TIMEOUT 只在
config/dev.py 定义,prod/test 环境 import 时 ImportError。
本文件防止同类问题复发: 所有公共常量必须在 base.py 或 agent_config.py re-export
里都能找到。
"""

import importlib
import os
import subprocess
import sys

import pytest


# agent_config.py re-export 的全部公共常量(来自文件 __all__ 分析)
_AGENT_CONFIG_PUBLIC_SYMBOLS = [
    "BASE_DIR", "PROMPT_PATH", "PR_REVIEW_PROMPT_PATH", "DEFAULT_WORKSPACE",
    "MODEL_TIERS", "ROUTER_PROMPT",
    "MAX_TOKENS", "MAX_TOOL_TURNS",
    "WORKER_TIMEOUT", "TOTAL_REVIEW_TIMEOUT", "TOOL_LOOP_TIMEOUT",
    "GOSHAWK_TIMEOUT",  # 新增,曾在 session 2 崩溃
    "EVIDENCE_RELIABILITY_THRESHOLD",
    "MAX_CONSECUTIVE_WORKER_FAILURES", "MAX_ITEMS_PER_WORKER",
    "COMPACT_THRESHOLD", "MAX_WIKI_CHARS",
    "JITTER_MAX_FRAC", "EFFORT_TOKENS",
]


@pytest.mark.parametrize("env", ["dev", "prod", "test"])
def test_all_public_symbols_importable_in_env(env):
    """每个 env 下,agent_config 的所有 re-export 必须能 import 成功。

    用 subprocess 隔离,避免污染当前进程的 config 缓存。
    """
    symbols_list = ", ".join(_AGENT_CONFIG_PUBLIC_SYMBOLS)
    code = f"from agent_config import {symbols_list}"
    env_vars = os.environ.copy()
    env_vars["PECKER_ENV"] = env

    # 绕过 pytest 父进程的 sys.path,新 subprocess 自己加载 config
    proj_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=proj_root,
        env=env_vars,
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, (
        f"PECKER_ENV={env} 下 agent_config import 失败:\n"
        f"stderr: {result.stderr}"
    )


def test_dev_worker_timeout_sufficient_for_sonnet():
    """基于 2026-04-16 shadow run 实测数据:

    Sonnet worker (quality/structure/data_quality) 平均 200-250s,
    原 240s 导致 44-53% 被截断。WORKER_TIMEOUT 必须 ≥ 300s。
    参考 logs/shadow_20260416_174900/report.json。

    这个守卫避免未来 'worker 太慢' 的反应被错误归结为降低 timeout。
    """
    proj_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env_vars = os.environ.copy()
    env_vars["PECKER_ENV"] = "dev"
    result = subprocess.run(
        [sys.executable, "-c",
         "from agent_config import WORKER_TIMEOUT; print(WORKER_TIMEOUT)"],
        cwd=proj_root, env=env_vars,
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0
    value = int(result.stdout.strip())
    assert value >= 300, (
        f"dev WORKER_TIMEOUT={value} 过紧,Sonnet worker 会 44-53% 假静默。"
        f"参考 SHADOW_20RUN_FINAL_2026_04_16.md 数据,应 ≥ 300s (推荐 360)"
    )


@pytest.mark.parametrize("env", ["dev", "prod", "test"])
def test_goshawk_timeout_positive(env):
    """GOSHAWK_TIMEOUT 必须是正数 (0 或负值会让苍鹰立即超时)。"""
    proj_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env_vars = os.environ.copy()
    env_vars["PECKER_ENV"] = env
    result = subprocess.run(
        [sys.executable, "-c",
         "from agent_config import GOSHAWK_TIMEOUT; print(GOSHAWK_TIMEOUT)"],
        cwd=proj_root, env=env_vars,
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, f"{env} 导入失败: {result.stderr}"
    assert int(result.stdout.strip()) > 0


@pytest.mark.parametrize("env", ["dev", "prod", "test"])
def test_actually_imported_symbols_across_envs_via_ast(env):
    """Round 5 全仓防御: 扫全仓 AST,把所有实际被 'from agent_config import X'
    或 'from config import X' 里出现的符号聚合起来,在每个 env 下一次性 import。

    如果以后有人加了新常量只在 dev.py 定义,这个测试会立刻在 prod/test env 下红。
    """
    import ast

    proj_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    # 扫根目录 + api/ + eval/ 下的 .py,跳过 tests/ / worktrees/ / pecker-release/
    skip_parts = {"tests", "worktrees", ".claude", "pecker-release", "__pycache__"}
    symbols = set()
    for root, dirs, files in os.walk(proj_root):
        dirs[:] = [d for d in dirs if d not in skip_parts and not d.startswith(".")]
        for f in files:
            if not f.endswith(".py"):
                continue
            path = os.path.join(root, f)
            try:
                tree = ast.parse(open(path, encoding="utf-8").read())
            except (SyntaxError, UnicodeDecodeError):
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module in ("agent_config", "config"):
                    for alias in node.names:
                        if alias.name != "*":
                            symbols.add(alias.name)

    assert symbols, "AST 扫描未找到任何 agent_config 符号,路径或逻辑异常"

    # 一次 subprocess 把全部符号 import 进来,任何一个漏定义都会直接报错
    import_stmt = "from agent_config import " + ", ".join(sorted(symbols))
    env_vars = os.environ.copy()
    env_vars["PECKER_ENV"] = env
    result = subprocess.run(
        [sys.executable, "-c", import_stmt],
        cwd=proj_root, env=env_vars,
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, (
        f"PECKER_ENV={env} 下,全仓扫描到的 {len(symbols)} 个 agent_config 符号至少 "
        f"1 个无法 import。stderr:\n{result.stderr}"
    )
