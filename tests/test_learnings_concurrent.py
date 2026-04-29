"""verify sqlite + file lock 后端在并发下不 corrupt.

策略:
  10 thread 各 add 5 条 → 共 50 条; 验证 list_all() 数量 = 50, 无重复 id, db 文件可读.
  同时跑 1 个 reader 线程不停 list_all, 确保 reader 不被写阻塞 (WAL 模式).
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from review.learnings_store import LearningsStore  # noqa: E402


def _safe_tmpdir():
    """Windows 下 sqlite WAL 文件偶发延迟释放, 用 mkdtemp + ignore_errors 模式."""
    return tempfile.mkdtemp()


def _safe_rmtree(path: str):
    import gc
    gc.collect()
    time.sleep(0.2)
    shutil.rmtree(path, ignore_errors=True)


def test_concurrent_add_no_corruption():
    tmp = _safe_tmpdir()
    try:
        store = LearningsStore(tmp)

        N_THREADS = 10
        PER_THREAD = 5
        errors: list[Exception] = []

        def worker(tid: int):
            try:
                local_store = LearningsStore(tmp)
                for i in range(PER_THREAD):
                    local_store.add(
                        trigger_pattern=f"trigger-{tid}-{i}",
                        instruction=f"do something {tid}-{i}",
                        scope="pr_local",
                        reviewer=f"pm-{tid}",
                        dim_keys=["test"],
                    )
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(t,)) for t in range(N_THREADS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        assert not errors, f"并发 add 抛异常: {errors[:3]}"
        all_records = store.list_all()
        assert len(all_records) == N_THREADS * PER_THREAD, (
            f"期望 {N_THREADS * PER_THREAD} 条, 实际 {len(all_records)}"
        )
        ids = [r.id for r in all_records]
        assert len(set(ids)) == len(ids), "出现重复 id, dedup 逻辑失败"
    finally:
        _safe_rmtree(tmp)


def test_concurrent_read_during_write():
    """WAL 模式下 reader 不被 writer 阻塞."""
    # Windows 下 sqlite WAL 文件 cleanup 偶发延迟释放, 用 mkdtemp 手动 try/except 兜底
    tmp = tempfile.mkdtemp()
    try:
        store = LearningsStore(tmp)
        stop_flag = threading.Event()
        read_counts: list[int] = []
        read_errors: list[Exception] = []

        def reader():
            while not stop_flag.is_set():
                try:
                    rows = store.list_all()
                    read_counts.append(len(rows))
                except Exception as e:  # noqa: BLE001
                    read_errors.append(e)
                time.sleep(0.01)

        def writer():
            for i in range(20):
                store.add(
                    trigger_pattern=f"t-{i}",
                    instruction=f"i-{i}",
                    scope="team_local",
                    reviewer="x",
                )

        rt = threading.Thread(target=reader, daemon=True)
        rt.start()
        time.sleep(0.05)  # 先让 reader warm up 几轮
        wt = threading.Thread(target=writer)
        wt.start()
        wt.join(timeout=30)
        # 让 reader 再跑一会儿确保至少累积几次
        time.sleep(0.1)
        stop_flag.set()
        rt.join(timeout=5)

        assert not read_errors, f"读路径出错: {read_errors[:3]}"
        # 写完 20 条 + 前后各跑几轮 read, 至少应该 >= 3 次成功
        assert len(read_counts) >= 3, f"reader 应跑多次, 实际 {len(read_counts)}"
        assert len(store.list_all()) == 20
    finally:
        # WAL handle 偶发延迟释放, 强制 GC 后忽略 unlink 失败
        import gc
        gc.collect()
        time.sleep(0.2)
        shutil.rmtree(tmp, ignore_errors=True)


def test_yaml_export_import_roundtrip():
    tmp, out, ws2 = _safe_tmpdir(), _safe_tmpdir(), _safe_tmpdir()
    try:
        store = LearningsStore(tmp)
        for i in range(3):
            store.add(
                trigger_pattern=f"trigger-{i}",
                instruction=f"do {i}",
                scope="org_global",
                reviewer="alice",
                dim_keys=["d1", "d2"],
            )
        n = store.export_yaml(out)
        assert n == 3
        yaml_files = [f for f in os.listdir(out) if f.endswith(".yaml")]
        assert len(yaml_files) == 3

        store2 = LearningsStore(ws2)
        imported = store2.import_yaml(out)
        assert imported == 3
        rows = store2.list_all()
        assert len(rows) == 3
        assert set(r.scope for r in rows) == {"org_global"}
    finally:
        for d in (tmp, out, ws2):
            _safe_rmtree(d)


def test_delete_and_update_usage():
    tmp = _safe_tmpdir()
    try:
        store = LearningsStore(tmp)
        l = store.add("a", "b", reviewer="x")
        assert store.update_usage(l.id) is True
        got = store.get(l.id)
        assert got is not None and got.usage_count == 1
        assert got.last_used is not None
        assert store.delete(l.id) is True
        assert store.get(l.id) is None
        assert store.delete("nonexistent") is False
    finally:
        _safe_rmtree(tmp)


if __name__ == "__main__":
    test_concurrent_add_no_corruption()
    test_concurrent_read_during_write()
    test_yaml_export_import_roundtrip()
    test_delete_and_update_usage()
    print("[OK] all concurrent tests passed")
