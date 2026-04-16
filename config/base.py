"""
啄木鸟配置基类 — 所有环境共享的默认值

dev/prod/test 配置通过 `from .base import *` 继承,只覆盖需要改的字段。

字段分层:
- 路径类: BASE_DIR, PROMPT_PATH, DEFAULT_WORKSPACE
- 模型类: MODEL_TIERS, ROUTER_PROMPT
- API 参数: MAX_TOKENS, MAX_TOOL_TURNS
- 超时: WORKER_TIMEOUT, TOTAL_REVIEW_TIMEOUT
- 阈值: EVIDENCE_RELIABILITY_THRESHOLD
- 敏感字段: API_KEY / BASE_URL / FEISHU_WEBHOOK 从环境变量读(不写这里)
"""

import os

# ============================================================
# 路径
# ============================================================

# BASE_DIR 指向项目根(config/ 的上一级)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PROMPT_PATH = os.path.join(BASE_DIR, "啄木鸟_系统提示词.md")
PR_REVIEW_PROMPT_PATH = os.path.join(BASE_DIR, "小啄_系统提示词.md")

# 默认工作目录(可被 --workspace CLI 覆盖)
DEFAULT_WORKSPACE = os.path.join(BASE_DIR, "workspace")


# ============================================================
# 模型
# ============================================================

MODEL_TIERS = {
    "opus":   "claude-opus-4-6",
    "sonnet": "claude-sonnet-4-6",
    "haiku":  "claude-haiku-4-5-20251001",
}

ROUTER_PROMPT = """你是 PRD 评审的意图路由器。根据用户指令和 PRD 名称，判断评审复杂度，输出一个词：

- opus：复杂 PRD 首次评审、涉及 AI Coding 友好度检查、多维度交叉验证、需要深度推理
- sonnet：常规 PRD 评审、标准结构的 PRD
- haiku：纯格式检查、lint、已评审 PRD 的迭代复核

只输出 opus / sonnet / haiku 一个词。"""


# ============================================================
# API 调用参数
# ============================================================

MAX_TOKENS = 8192
MAX_TOOL_TURNS = 30


# ============================================================
# Worker 并行超时(秒)
# ============================================================

# 单个 Worker 最多跑 7 分钟;总体并行评审最多 15 分钟(含合并去重)
WORKER_TIMEOUT = 420
TOTAL_REVIEW_TIMEOUT = 900

# Phase G #9: 苍鹰(Opus via CLI)交叉校验超时(秒)
# 苍鹰在 4 worker 全部完成后运行,不受 TOTAL_REVIEW_TIMEOUT 覆盖
GOSHAWK_TIMEOUT = 600

# tool_loop wall-clock 上限(秒),A4: 防止死循环或单次评审跑飞
# 20 分钟足够 opus 打 30 轮工具调用;超时抛 AgentTimeoutError
TOOL_LOOP_TIMEOUT = 1200


# ============================================================
# 质量阈值
# ============================================================

# 依据可靠率低于此值则伯劳 Gate 6 失败
EVIDENCE_RELIABILITY_THRESHOLD = 0.80

# F4: Eval CI gate 阈值(pytest -m eval 会断言 scorer 输出 >= 此值)
# 低于则 CI 红,保护评审质量回归
EVAL_MIN_OVERALL_SCORE = 0.50   # scorer.calculate_scores() overall_score
EVAL_MIN_RECALL = 0.40          # 召回率下限
EVAL_MIN_PRECISION = 0.40       # 精确率下限


# ============================================================
# 环境变量读取 helper
# ============================================================

def get_api_key():
    """从环境变量读 API Key(敏感字段不写配置文件)"""
    return os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("API_KEY") or ""


def get_base_url():
    """API Base URL,允许环境变量覆盖"""
    return os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com")


def get_feishu_webhook():
    """飞书通知 webhook"""
    return os.environ.get("FEISHU_WEBHOOK", "")
