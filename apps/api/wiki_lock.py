"""
Wiki 并发写入锁 — 防止多个评审 session 同时写 wiki 导致互相覆盖
使用文件锁实现跨进程互斥
"""

import os
import time
import contextlib
from exceptions import WikiError

LOCK_FILE = ".wiki_write.lock"
LOCK_TIMEOUT = 30  # 最多等 30 秒
LOCK_STALE = 120   # 超过 2 分钟视为过期锁


@contextlib.contextmanager
def wiki_write_lock(wiki_path):
    """
    获取 wiki 写入锁的上下文管理器
    用法: with wiki_write_lock(wiki_path): ...
    """
    lock_path = os.path.join(wiki_path, LOCK_FILE)
    acquired = False
    start = time.time()

    while time.time() - start < LOCK_TIMEOUT:
        # 检查过期锁
        if os.path.exists(lock_path):
            try:
                mtime = os.path.getmtime(lock_path)
                if time.time() - mtime > LOCK_STALE:
                    os.remove(lock_path)
            except OSError:
                pass

        # 尝试原子创建锁文件
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            acquired = True
            break
        except FileExistsError:
            time.sleep(0.1 + (hash(os.getpid()) % 100) / 1000)  # 随机退避

    if not acquired:
        # 超时仍未获取，不强制抢锁（避免 TOCTOU 竞争），走 warning 路径
        from logger import get_logger
        get_logger("wiki_lock").warning("Wiki 写入锁获取超时，继续执行（可能有并发冲突）")

    try:
        yield acquired
    finally:
        if acquired:
            try:
                os.remove(lock_path)
            except OSError:
                pass
