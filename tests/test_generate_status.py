"""
scripts/generate_status.py classifier 单测

聚焦: classify_session 正确区分 4 类 session 结果。
这是 STATUS.md 核心指标的基础,错了会误导整个团队的优化方向。
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))


QUOTA_ERR = 'claude -p 退出码 1: {"is_error":true,"result":"You\'ve hit your limit · resets 8am"}'


def _w(dim: str, items: int, error: str = None, confirmed_empty: bool = False):
    """Worker done event helper."""
    return {
        "type": "worker_done",
        "dim": dim,
        "items_count": items,
        "error": error,
        "empty_submission_confirmed": confirmed_empty,
    }


class TestIsQuotaError:
    def test_none_not_quota(self):
        from generate_status import _is_quota_error
        assert _is_quota_error(None) is False
        assert _is_quota_error("") is False

    def test_hit_your_limit(self):
        from generate_status import _is_quota_error
        assert _is_quota_error(QUOTA_ERR) is True

    def test_usage_limit(self):
        from generate_status import _is_quota_error
        assert _is_quota_error("CLI returned: usage limit exceeded") is True

    def test_quotaexhausted(self):
        from generate_status import _is_quota_error
        assert _is_quota_error("QuotaExhaustedError: resets 8am") is True

    def test_non_quota_error(self):
        from generate_status import _is_quota_error
        assert _is_quota_error("JSONDecodeError: unexpected EOF") is False
        assert _is_quota_error("Timeout after 60s") is False


class TestClassifySession:
    def test_empty_input(self):
        from generate_status import classify_session
        assert classify_session([]) == "error_other"

    def test_all_productive(self):
        from generate_status import classify_session
        workers = [_w("structure", 7), _w("quality", 2), _w("ai_coding", 6), _w("data_quality", 1)]
        assert classify_session(workers) == "productive"

    def test_all_quota(self):
        from generate_status import classify_session
        workers = [_w(d, 0, QUOTA_ERR) for d in ["structure", "quality", "ai_coding", "data_quality"]]
        assert classify_session(workers) == "quota_exhausted"

    def test_partial_silent(self):
        """真实 session 2 的形态: structure + ai_coding 出了 items,quality + data_quality 静默。"""
        from generate_status import classify_session
        workers = [
            _w("structure", 7),
            _w("ai_coding", 6),
            _w("quality", 0),
            _w("data_quality", 0),
        ]
        assert classify_session(workers) == "partial_silent"

    def test_confirmed_empty_is_not_silent(self):
        """显式填写 null_finding_reason 的 0-items worker 是 clean 结果,不算静默。"""
        from generate_status import classify_session
        workers = [
            _w("structure", 7),
            _w("ai_coding", 6),
            _w("quality", 0, confirmed_empty=True),
            _w("data_quality", 0, confirmed_empty=True),
        ]
        assert classify_session(workers) == "productive"

    def test_all_confirmed_empty_is_productive_clean(self):
        from generate_status import classify_session
        workers = [_w(d, 0, confirmed_empty=True) for d in ["structure", "quality"]]
        assert classify_session(workers) == "productive"

    def test_all_silent_empty_bug(self):
        from generate_status import classify_session
        workers = [_w(d, 0) for d in ["structure", "quality", "ai_coding", "data_quality"]]
        assert classify_session(workers) == "empty_bug"

    def test_mixed_error_types_is_other(self):
        """配额 + 非配额 error 混合不该归为 quota_exhausted。"""
        from generate_status import classify_session
        workers = [
            _w("structure", 0, QUOTA_ERR),
            _w("quality", 0, "Timeout"),
            _w("ai_coding", 0, QUOTA_ERR),
            _w("data_quality", 0, QUOTA_ERR),
        ]
        # 非全 quota → 不是 quota_exhausted,也不是 empty_bug (有 error),应归 error_other
        result = classify_session(workers)
        assert result == "error_other"

    def test_single_worker_productive(self):
        from generate_status import classify_session
        assert classify_session([_w("structure", 5)]) == "productive"

    def test_single_worker_quota(self):
        from generate_status import classify_session
        assert classify_session([_w("structure", 0, QUOTA_ERR)]) == "quota_exhausted"


class TestAuthErrorClassification:
    """Round 15: 新增的 401 auth 分类"""

    AUTH_ERR_401 = ('claude -p 退出码 1: {"api_error_status":401,"result":'
                    '"Failed to authenticate. API Error: 401 ..."}')

    def test_is_auth_error_401(self):
        from generate_status import _is_auth_error
        assert _is_auth_error(self.AUTH_ERR_401) is True

    def test_is_auth_error_none(self):
        from generate_status import _is_auth_error
        assert _is_auth_error(None) is False
        assert _is_auth_error("") is False

    def test_is_auth_error_quota_not_auth(self):
        from generate_status import _is_auth_error
        assert _is_auth_error("hit your limit · resets 8am") is False

    def test_is_auth_error_authentication_error_phrase(self):
        from generate_status import _is_auth_error
        assert _is_auth_error("...authentication_error...") is True

    def test_classify_all_auth_is_auth_expired(self):
        from generate_status import classify_session
        workers = [{"type": "worker_done", "dim": d, "items_count": 0,
                    "error": self.AUTH_ERR_401}
                   for d in ["structure", "quality", "ai_coding", "data_quality"]]
        assert classify_session(workers) == "auth_expired"

    def test_classify_auth_and_quota_mixed_is_other(self):
        """auth + quota 混合,不算 pure auth_expired,退回 error_other."""
        from generate_status import classify_session
        workers = [
            {"type": "worker_done", "dim": "structure", "items_count": 0,
             "error": self.AUTH_ERR_401},
            {"type": "worker_done", "dim": "quality", "items_count": 0,
             "error": "hit your limit"},
            {"type": "worker_done", "dim": "ai_coding", "items_count": 0,
             "error": self.AUTH_ERR_401},
            {"type": "worker_done", "dim": "data_quality", "items_count": 0,
             "error": self.AUTH_ERR_401},
        ]
        # 混合 error → 不是 all_quota 也不是 all_auth
        assert classify_session(workers) == "error_other"


class TestErrorFingerprint:
    """_error_fingerprint 归一化聚合验证."""

    def test_none_returns_empty(self):
        from generate_status import _error_fingerprint
        assert _error_fingerprint(None) == ""
        assert _error_fingerprint("") == ""

    def test_windows_path_normalized(self):
        from generate_status import _error_fingerprint
        err = r"ImportError in C:\Users\foo\Desktop\agent\prd review\module.py"
        fp = _error_fingerprint(err)
        assert "<path>" in fp
        assert "C:\\" not in fp

    def test_unix_path_normalized(self):
        from generate_status import _error_fingerprint
        err = "ImportError in /home/user/project/module.py line 42"
        fp = _error_fingerprint(err)
        assert "<path>" in fp

    def test_duration_stripped(self):
        from generate_status import _error_fingerprint
        err = 'returncode 1: {"duration_ms":4611,"result":"x"}'
        fp = _error_fingerprint(err)
        assert "duration_ms:<n>" in fp
        assert "4611" not in fp

    def test_quota_reset_time_stripped(self):
        from generate_status import _error_fingerprint
        err = "You've hit your limit · resets 8am (America/Los_Angeles)"
        fp = _error_fingerprint(err)
        assert "resets <time>" in fp
        assert "8am" not in fp

    def test_length_capped_at_80(self):
        from generate_status import _error_fingerprint
        long_err = "x" * 200
        assert len(_error_fingerprint(long_err)) <= 80

    def test_similar_errors_produce_same_fingerprint(self):
        """两个只在 path/timestamp 不同的错误应该聚合成同一 fingerprint。"""
        from generate_status import _error_fingerprint
        err1 = r"cannot import name 'X' from 'Y' (C:\Users\alice\proj\a.py)"
        err2 = r"cannot import name 'X' from 'Y' (C:\Users\bob\proj\b.py)"
        assert _error_fingerprint(err1) == _error_fingerprint(err2)


class TestEmptyRetryAggregation:
    """Round 2: 验证 generate_status 正确消费 empty_retry_used telemetry."""

    def _session_file(self, tmp_path, name: str, events: list):
        """写一个 workspace-*/output/sessions/*.jsonl 供 collect_session_stats 扫描。"""
        import json as _j
        p = tmp_path / f"workspace-{name}" / "output" / "sessions"
        p.mkdir(parents=True, exist_ok=True)
        jsonl = p / f"{name}.jsonl"
        with jsonl.open("w", encoding="utf-8") as f:
            for e in events:
                f.write(_j.dumps(e, ensure_ascii=False) + "\n")
        return jsonl

    def test_retry_stats_trigger_and_rescue(self, tmp_path, monkeypatch):
        """构造:3 worker 触发 retry,其中 2 个救回 1 个仍空 → trigger_rate 3/4, rescue 2/3."""
        from generate_status import collect_session_stats
        import generate_status as gs

        self._session_file(tmp_path, "t1", [
            {"type": "review_started"},
            {"type": "workers_started"},
            {"type": "worker_done", "dim": "structure", "items_count": 5,
             "error": None, "empty_retry_used": False},
            {"type": "worker_done", "dim": "quality", "items_count": 2,
             "error": None, "empty_retry_used": True},   # triggered + rescued
            {"type": "worker_done", "dim": "ai_coding", "items_count": 3,
             "error": None, "empty_retry_used": True},   # triggered + rescued
            {"type": "worker_done", "dim": "data_quality", "items_count": 0,
             "error": None, "empty_retry_used": True,
             "empty_submission_confirmed": True},        # triggered + kept_empty + confirmed clean
            {"type": "review_completed"},
        ])

        # monkeypatch ROOT 指向 tmp_path,让 glob 命中刚写的 jsonl
        monkeypatch.setattr(gs, "ROOT", tmp_path)

        stats = collect_session_stats()
        retry = stats["empty_retry"]
        assert retry["instrumented_workers"] == 4
        assert retry["triggered"] == 3
        assert retry["rescued"] == 2
        assert retry["kept_empty"] == 1
        assert retry["confirmed_empty"] == 1
        assert retry["trigger_rate"] == 0.75
        assert abs(retry["rescue_rate"] - 2/3) < 1e-3  # 服从 round(..., 3) 精度

    def test_confirmed_empty_workers_not_counted_as_silent_rate(self, tmp_path, monkeypatch):
        """worker silent_rate 分母纳入 clean 结果,但 confirmed empty 不进 silent 分子。"""
        from generate_status import collect_session_stats
        import generate_status as gs

        self._session_file(tmp_path, "clean", [
            {"type": "review_started"},
            {"type": "worker_done", "dim": "quality", "items_count": 0,
             "error": None, "empty_submission_confirmed": True},
            {"type": "worker_done", "dim": "data_quality", "items_count": 0,
             "error": None, "empty_submission_confirmed": False},
            {"type": "review_completed"},
        ])
        monkeypatch.setattr(gs, "ROOT", tmp_path)

        stats = collect_session_stats()
        assert stats["worker_silent_rate"]["quality"] == 0
        assert stats["worker_silent_rate"]["data_quality"] == 1
        assert stats["worker_confirmed_empty"] == {"quality": 1}

    def test_retry_stats_no_telemetry_yields_zero_instrumented(self, tmp_path, monkeypatch):
        """老 session 没 empty_retry_used 字段 → instrumented_workers=0, rates=0."""
        from generate_status import collect_session_stats
        import generate_status as gs

        self._session_file(tmp_path, "old", [
            {"type": "review_started"},
            {"type": "workers_started"},
            {"type": "worker_done", "dim": "structure", "items_count": 5, "error": None},
            {"type": "worker_done", "dim": "quality", "items_count": 0, "error": None},
            {"type": "review_completed"},
        ])
        monkeypatch.setattr(gs, "ROOT", tmp_path)

        stats = collect_session_stats()
        retry = stats["empty_retry"]
        assert retry["instrumented_workers"] == 0
        assert retry["triggered"] == 0
        assert retry["trigger_rate"] == 0
        assert retry["rescue_rate"] == 0

    def test_retry_stats_ignored_in_quota_sessions(self, tmp_path, monkeypatch):
        """quota_exhausted session 不该影响 retry 统计 (worker 根本没跑到 retry 分支)."""
        from generate_status import collect_session_stats
        import generate_status as gs

        quota_err = "claude -p 退出码 1: hit your limit"
        self._session_file(tmp_path, "quota", [
            {"type": "review_started"},
            {"type": "worker_done", "dim": "structure", "items_count": 0,
             "error": quota_err, "empty_retry_used": False},
            {"type": "worker_done", "dim": "quality", "items_count": 0,
             "error": quota_err, "empty_retry_used": False},
            {"type": "worker_done", "dim": "ai_coding", "items_count": 0,
             "error": quota_err, "empty_retry_used": False},
            {"type": "worker_done", "dim": "data_quality", "items_count": 0,
             "error": quota_err, "empty_retry_used": False},
        ])
        monkeypatch.setattr(gs, "ROOT", tmp_path)

        stats = collect_session_stats()
        # quota session 走 if outcome != 'quota_exhausted' 分支跳过 → retry 不累加
        assert stats["empty_retry"]["instrumented_workers"] == 0


class TestGoshawkVerdictAggregation:
    """Round 8: STATUS 聚合 goshawk verdict 分布."""

    def _session_file(self, tmp_path, name, events):
        import json as _j
        p = tmp_path / f"workspace-{name}" / "output" / "sessions"
        p.mkdir(parents=True, exist_ok=True)
        jsonl = p / f"{name}.jsonl"
        with jsonl.open("w", encoding="utf-8") as f:
            for e in events:
                f.write(_j.dumps(e, ensure_ascii=False) + "\n")

    def test_verdict_reviewed(self, tmp_path, monkeypatch):
        from generate_status import collect_session_stats
        import generate_status as gs

        self._session_file(tmp_path, "s1", [
            {"type": "review_started"},
            {"type": "workers_started"},
            {"type": "worker_done", "dim": "structure", "items_count": 5, "error": None},
            {"type": "final_reviewer_done", "verdict": "REVIEWED",
             "false_positive": 1, "additional": 0, "empty_retry_used": False},
        ])
        monkeypatch.setattr(gs, "ROOT", tmp_path)
        stats = collect_session_stats()
        assert stats["goshawk"]["instrumented_sessions"] == 1
        assert stats["goshawk"]["verdict_distribution"] == {"REVIEWED": 1}
        assert stats["goshawk"]["empty_retry_used_count"] == 0

    def test_verdict_empty_approval_with_retry(self, tmp_path, monkeypatch):
        from generate_status import collect_session_stats
        import generate_status as gs

        self._session_file(tmp_path, "s2", [
            {"type": "worker_done", "dim": "structure", "items_count": 5, "error": None},
            {"type": "final_reviewer_done", "verdict": "EMPTY_APPROVAL",
             "empty_retry_used": True, "confidence": 0.85},
        ])
        monkeypatch.setattr(gs, "ROOT", tmp_path)
        stats = collect_session_stats()
        assert stats["goshawk"]["verdict_distribution"] == {"EMPTY_APPROVAL": 1}
        assert stats["goshawk"]["empty_retry_used_count"] == 1

    def test_verdict_silent(self, tmp_path, monkeypatch):
        from generate_status import collect_session_stats
        import generate_status as gs

        self._session_file(tmp_path, "s3", [
            {"type": "worker_done", "dim": "structure", "items_count": 5, "error": None},
            {"type": "final_reviewer_done", "verdict": "SILENT",
             "empty_retry_used": False},
        ])
        monkeypatch.setattr(gs, "ROOT", tmp_path)
        stats = collect_session_stats()
        assert stats["goshawk"]["verdict_distribution"] == {"SILENT": 1}

    def test_multiple_sessions_aggregate(self, tmp_path, monkeypatch):
        from generate_status import collect_session_stats
        import generate_status as gs

        for name, v in [("a", "REVIEWED"), ("b", "REVIEWED"), ("c", "EMPTY_APPROVAL")]:
            self._session_file(tmp_path, name, [
                {"type": "worker_done", "dim": "structure", "items_count": 3, "error": None},
                {"type": "final_reviewer_done", "verdict": v,
                 "empty_retry_used": False},
            ])
        monkeypatch.setattr(gs, "ROOT", tmp_path)
        stats = collect_session_stats()
        assert stats["goshawk"]["instrumented_sessions"] == 3
        assert stats["goshawk"]["verdict_distribution"] == {"REVIEWED": 2, "EMPTY_APPROVAL": 1}

    def test_old_data_without_verdict_not_counted(self, tmp_path, monkeypatch):
        """老 final_reviewer_done 无 verdict 字段 → instrumented_sessions = 0."""
        from generate_status import collect_session_stats
        import generate_status as gs

        self._session_file(tmp_path, "old", [
            {"type": "worker_done", "dim": "structure", "items_count": 3, "error": None},
            {"type": "final_reviewer_done", "false_positive": 0, "additional": 0},
        ])
        monkeypatch.setattr(gs, "ROOT", tmp_path)
        stats = collect_session_stats()
        assert stats["goshawk"]["instrumented_sessions"] == 0



class TestRecentWindow:
    """双口径对照: recent (最近 N) vs all_time (全量) — 防止老数据拖累新指标."""

    def _session_file(self, tmp_path, name: str, events: list):
        import json as _j
        p = tmp_path / "workspace-w" / "output" / "sessions"
        p.mkdir(parents=True, exist_ok=True)
        # 文件名里的 epoch ts 决定排序
        jsonl = p / f"{name}.jsonl"
        with jsonl.open("w", encoding="utf-8") as f:
            for e in events:
                f.write(_j.dumps(e, ensure_ascii=False) + "\n")
        return jsonl

    def test_recent_window_isolates_old_failures(self, tmp_path, monkeypatch):
        """老 session 全 fail,新 session 全 productive → recent 高, all_time 低."""
        from generate_status import collect_session_stats
        import generate_status as gs

        # 25 条老 session (empty_bug) + 5 条新 session (productive)
        # 文件名按 ts 排序,recent 窗口取最后 20 条
        for i in range(25):
            self._session_file(tmp_path, f"rev_170000{i:04d}_old", [
                {"type": "worker_done", "dim": "structure", "items_count": 0, "error": None},
                {"type": "worker_done", "dim": "quality", "items_count": 0, "error": None},
            ])
        for i in range(5):
            self._session_file(tmp_path, f"rev_180000{i:04d}_new", [
                {"type": "worker_done", "dim": "structure", "items_count": 3, "error": None},
                {"type": "worker_done", "dim": "quality", "items_count": 2, "error": None},
            ])
        monkeypatch.setattr(gs, "ROOT", tmp_path)

        stats = collect_session_stats(recent_window=20)

        # recent 窗口 20 条: 最后 5 条 productive + 倒数第 6~20 条 empty_bug
        # → 5 productive / 20 = 25%
        assert stats["sessions"] == 20  # recent 窗口大小
        assert stats["effective_consistency"] == 0.25

        # all_time: 5 productive / 30 total = ~16.7%
        assert stats["all_time"]["sessions"] == 30
        assert abs(stats["all_time"]["effective_consistency"] - 5 / 30) < 0.01

    def test_recent_window_smaller_than_total(self, tmp_path, monkeypatch):
        """窗口 > 总数时, recent == all_time."""
        from generate_status import collect_session_stats
        import generate_status as gs

        self._session_file(tmp_path, "rev_170000_only", [
            {"type": "worker_done", "dim": "structure", "items_count": 3, "error": None},
        ])
        monkeypatch.setattr(gs, "ROOT", tmp_path)

        stats = collect_session_stats(recent_window=20)
        assert stats["sessions"] == 1
        assert stats["all_time"]["sessions"] == 1
        assert stats["effective_consistency"] == stats["all_time"]["effective_consistency"]
