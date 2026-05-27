"""
Pecker分环境配置包 — 根据 PECKER_ENV 加载对应配置

用法:
    PECKER_ENV=prod python run_session.py ...
    PECKER_ENV=test pytest ...

默认环境是 dev。agent_config.py 向后兼容地从本包重新 export 配置。

设计:
- config/base.py:    所有环境共享的默认值
- config/{env}.py:   `from .base import *` 后覆盖需要改的字段
- config/__init__.py(本文件): 根据 PECKER_ENV 动态 import 对应 env 模块,
  把所有 UPPER_CASE 常量和 get_xxx 函数提升到包命名空间

这意味着下游可以直接:
    from config import MODEL_TIERS, WORKER_TIMEOUT
"""

import os
import importlib

# 支持的环境列表
_SUPPORTED_ENVS = {"dev", "prod", "test"}

# 读取环境变量,默认 dev
PECKER_ENV = os.environ.get("PECKER_ENV", "dev").lower()
if PECKER_ENV not in _SUPPORTED_ENVS:
    import warnings
    warnings.warn(
        f"未知的 PECKER_ENV={PECKER_ENV!r},回退到 dev。支持的值: {sorted(_SUPPORTED_ENVS)}"
    )
    PECKER_ENV = "dev"

# 动态 import 对应 env 模块
_env_module = importlib.import_module(f"config.{PECKER_ENV}")

# 把 env 模块里所有 UPPER_CASE 常量 + get_ 函数提升到本包
for _name in dir(_env_module):
    if _name.startswith("_"):
        continue
    if _name.isupper() or _name.startswith("get_"):
        globals()[_name] = getattr(_env_module, _name)


def load_system_prompt():
    """读取Pecker系统提示词(从 PROMPT_PATH)"""
    with open(PROMPT_PATH, "r", encoding="utf-8") as f:  # noqa: F405
        return f.read()


def load_pr_review_prompt():
    """读取小啄系统提示词(从 PR_REVIEW_PROMPT_PATH)"""
    with open(PR_REVIEW_PROMPT_PATH, "r", encoding="utf-8") as f:  # noqa: F405
        return f.read()
