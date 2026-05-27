"""
Pecker统一日志配置
所有模块通过 get_logger(name) 获取 logger，替代 print()

E4 (Phase 4): @log_agent_call 装饰器统一埋点 — 借鉴示例产品 AOP 日志方法论
"""
import functools
import io
import logging
import sys
import time


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


def log_agent_call(agent_name=None):
    """E4: 统一 Agent 埋点装饰器

    在 Agent 入口函数上加 @log_agent_call("苍鹰"),自动记录:
    - 开始时间
    - 结束 + 耗时
    - 异常(含 AgentTimeoutError 等子类)

    用法:
        @log_agent_call("苍鹰")
        def run_goshawk_review(...):
            ...

        @log_agent_call()  # 自动用函数名
        async def run_worker(...):
            ...

    同时支持同步和 async 函数,通过 inspect 判断。
    """
    def decorator(fn):
        import inspect
        is_async = inspect.iscoroutinefunction(fn)
        label = agent_name or fn.__name__
        log = get_logger("agent")

        if is_async:
            @functools.wraps(fn)
            async def async_wrapper(*args, **kwargs):
                start = time.time()
                log.info(f"[{label}] start")
                try:
                    result = await fn(*args, **kwargs)
                    elapsed = time.time() - start
                    log.info(f"[{label}] done ({elapsed:.1f}s)")
                    return result
                except Exception as e:
                    elapsed = time.time() - start
                    log.error(f"[{label}] FAIL after {elapsed:.1f}s: {type(e).__name__}: {str(e)[:80]}")
                    raise
            return async_wrapper
        else:
            @functools.wraps(fn)
            def sync_wrapper(*args, **kwargs):
                start = time.time()
                log.info(f"[{label}] start")
                try:
                    result = fn(*args, **kwargs)
                    elapsed = time.time() - start
                    log.info(f"[{label}] done ({elapsed:.1f}s)")
                    return result
                except Exception as e:
                    elapsed = time.time() - start
                    log.error(f"[{label}] FAIL after {elapsed:.1f}s: {type(e).__name__}: {str(e)[:80]}")
                    raise
            return sync_wrapper

    return decorator
