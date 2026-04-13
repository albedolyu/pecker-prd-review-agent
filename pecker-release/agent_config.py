"""
共享配置 -- 模型、提示词、常量
"""

import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# --- 系统提示词 ---
PROMPT_PATH = os.path.join(BASE_DIR, "啄木鸟_系统提示词.md")
PR_REVIEW_PROMPT_PATH = os.path.join(BASE_DIR, "小啄_系统提示词.md")


def load_system_prompt():
    with open(PROMPT_PATH, "r", encoding="utf-8") as f:
        return f.read()


def load_pr_review_prompt():
    with open(PR_REVIEW_PROMPT_PATH, "r", encoding="utf-8") as f:
        return f.read()


# --- 三档模型 ---
MODEL_TIERS = {
    "opus":   "claude-opus-4-6",
    "sonnet": "claude-sonnet-4-6",
    "haiku":  "claude-haiku-4-5-20251001",  # pikachu 中转站 haiku 需要完整版本号
}

# --- 意图路由提示词 ---
ROUTER_PROMPT = """你是 PRD 评审的意图路由器。根据用户指令和 PRD 名称，判断评审复杂度，输出一个词：

- opus：复杂 PRD 首次评审、涉及 AI Coding 友好度检查、多维度交叉验证、需要深度推理
- sonnet：常规 PRD 评审、标准结构的 PRD
- haiku：纯格式检查、lint、已评审 PRD 的迭代复核

只输出 opus / sonnet / haiku 一个词。"""

# --- 默认工作目录（可通过 --workspace 覆盖）---
DEFAULT_WORKSPACE = os.path.join(BASE_DIR, "workspace")

# --- API 调用参数 ---
MAX_TOKENS = 8192
MAX_TOOL_TURNS = 30
