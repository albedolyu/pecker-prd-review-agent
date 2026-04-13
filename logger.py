"""
啄木鸟统一日志配置
所有模块通过 get_logger(name) 获取 logger，替代 print()
"""
import logging
import sys
import io


def setup_logging(level=logging.INFO):
    """配置根 logger，只调用一次"""
    # UTF-8 handler（防 Windows GBK 崩溃）
    handler = logging.StreamHandler(
        io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    )
    handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    ))

    root = logging.getLogger("pecker")
    if not root.handlers:  # 防止重复添加
        root.addHandler(handler)
        root.setLevel(level)
    return root


def get_logger(name: str) -> logging.Logger:
    """获取模块 logger，如 get_logger('tools')"""
    return logging.getLogger(f"pecker.{name}")
