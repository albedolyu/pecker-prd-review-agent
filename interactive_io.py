"""
交互 I/O 辅助 — 从 run_session.py 抽出

支持 CI/CD 等无 stdin 场景下的 input() 降级:
- PECKER_NONINTERACTIVE=1 时所有 _read_input 直接返回 fallback
- 检测 sys.stdin.isatty() 可在 main() 启动时自动开启
"""

import os


def is_noninteractive() -> bool:
    """检测是否处于非交互模式 (CI/CD 场景)

    触发条件:
    - 环境变量 PECKER_NONINTERACTIVE=1/true/yes
    - 或 CLI 参数 --non-interactive 被设置 (会在 main() 中设置环境变量)
    """
    return os.environ.get("PECKER_NONINTERACTIVE", "").lower() in ("1", "true", "yes")


def read_input(prompt: str, fallback: str = "") -> str:
    """非交互模式下直接返回 fallback,不调用 input()

    用法:
        name = read_input("PRD 名称: ", fallback="unnamed")
    """
    if is_noninteractive():
        return fallback
    try:
        return input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        return fallback
