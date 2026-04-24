"""funnel_report 聚合器单测 (2026-04-24 T3 闭环).

目的: 断言对新老 jsonl 都能正确提取 N0-N4, 趋势计算, markdown 输出结构.
"""
from __future__ import annotations

import json
import os
import sys

import pytest


_SCRIPTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "scripts"))
sys.path.insert(0, _SCRIPTS_DIR)


def _write_jsonl(tmp_path, events, name="rev_test_0001.jsonl"):
    """把 events list dump 成 jsonl 文件."""
    ws = tmp_path / "workspace-test"
    sessions_dir = ws / "output" / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    p = sessions_dir / name
    p.write_text(
        "\n".join(json.dumps(e, ensure_ascii=False) for e in events),
        encoding="utf-8",
    )
    return p, str(ws)


# ============================================================
# extract_funnel_from_session — T3 native 事件
# ============================================================

class TestExtractT3Native:
    def test_full_funnel_5_stages(self, tmp_path):
        from funnel_report import extract_funnel_from_session
        events = [
            {"type": "review_started", "ts": "2026-04-24T16:00", "prd_files": ["foo.md"], "mode": "cli"},
            {"type": "funnel_stage_worker_raw", "count": 28, "by_dimension": {"structure": 8}},
            {"type": "funnel_stage_after_dedup", "count": 15},
            {"type": "funnel_stage_after_evidence_verify", "count": 11, "retracted_count": 2,
             "downgraded_count": 3, "wiki_mode": "rich",
             "authority_distribution": {"canonical": 2, "trusted": 5}},
            {"type": "funnel_stage_after_goshawk", "count": 10,
             "delta_breakdown": {"merged_to_facet": 3, "added": 2}},
            {"type": "funnel_stage_after_pm_decision", "total_items": 10,
             "accepted": 5, "rejected": 3, "rejected_by_reason": {"false_positive": 2, "wiki_missing": 1}},
            {"type": "funnel_summary", "suspicious_flags": ["dedup_retention_low_0.536"]},
            {"type": "review_completed", "items_count": 10},
        ]
        path, _ws = _write_jsonl(tmp_path, events)
        info = extract_funnel_from_session(str(path))

        assert info["N0"] == 28
        assert info["N1"] == 15
        assert info["N2"] == 11
        assert info["N3"] == 10
        assert info["N4"] == 10
        assert info["retracted"] == 2
        assert info["downgraded"] == 3
        assert info["wiki_mode"] == "rich"
        assert info["authority_distribution"] == {"canonical": 2, "trusted": 5}
        assert info["delta_breakdown"] == {"merged_to_facet": 3, "added": 2}
        assert info["rejected_by_reason"] == {"false_positive": 2, "wiki_missing": 1}
        assert "dedup_retention_low_0.536" in info["suspicious_flags"]
        # source events 标明是 T3 原生
        assert any(ev.startswith("T3_") for ev in info["source_events"])


# ============================================================
# extract_funnel_from_session — 老 session 降级
# ============================================================

class TestExtractLegacy:
    def test_legacy_session_uses_worker_done_sum(self, tmp_path):
        """老 session 没 funnel_stage_*, 从 worker_done 累加出 N0, checkpoint 出 N1, review_completed 出 N3."""
        from funnel_report import extract_funnel_from_session
        events = [
            {"type": "review_started", "ts": "2026-04-23T09:00", "prd_name": "old.md", "mode": "cli"},
            {"type": "workers_started"},
            {"type": "worker_done", "dim": "a", "items_count": 3},
            {"type": "worker_done", "dim": "b", "items_count": 5},
            {"type": "worker_done", "dim": "c", "items_count": 4},
            {"type": "checkpoint", "items_count": 10},  # merge 后
            {"type": "final_reviewer_done", "false_positive": 0, "additional": 1},
            {"type": "review_completed", "items_count": 9},  # 最终 (N3)
        ]
        path, _ = _write_jsonl(tmp_path, events)
        info = extract_funnel_from_session(str(path))

        assert info["N0"] == 12   # 3+5+4
        assert info["N1"] == 10
        assert info["N2"] is None   # 老 session 没这个
        assert info["N3"] == 9
        assert info["N4"] is None
        assert info["review_completed"] is True
        # source_events 不含 T3_ 标记
        assert not any(ev.startswith("T3_") for ev in info["source_events"])

    def test_partial_t3(self, tmp_path):
        """部分 T3 event (如只发了 N0/N1, N2/N3/N4 缺) — 不 crash."""
        from funnel_report import extract_funnel_from_session
        events = [
            {"type": "review_started", "ts": "2026-04-24", "prd_files": ["a.md"]},
            {"type": "funnel_stage_worker_raw", "count": 20},
            {"type": "funnel_stage_after_dedup", "count": 15},
            # 缺后续 stage
            {"type": "review_completed", "items_count": 8},
        ]
        path, _ = _write_jsonl(tmp_path, events)
        info = extract_funnel_from_session(str(path))
        assert info["N0"] == 20
        assert info["N1"] == 15
        assert info["N3"] == 8   # fallback to review_completed
        assert info["N2"] is None
        assert info["N4"] is None


# ============================================================
# collect_sessions / compute_trend
# ============================================================

class TestCollectSessions:
    def test_sort_by_mtime_desc(self, tmp_path):
        """多个 session jsonl, 按 mtime 新到旧返回, 取最后 N 个."""
        import time
        from funnel_report import collect_sessions
        ws = tmp_path / "workspace-x"
        sessions_dir = ws / "output" / "sessions"
        sessions_dir.mkdir(parents=True)

        older = sessions_dir / "rev_old.jsonl"
        older.write_text('{"type": "review_started"}\n', encoding="utf-8")
        time.sleep(0.02)
        newer = sessions_dir / "rev_new.jsonl"
        newer.write_text('{"type": "review_started"}\n', encoding="utf-8")

        ss = collect_sessions(str(ws), last_n=10)
        ids = [s["session_id"] for s in ss]
        assert ids[0] == "rev_new"   # 最新在前
        assert ids[1] == "rev_old"


class TestComputeTrend:
    def test_trend_min_mean_max(self):
        from funnel_report import compute_trend
        sessions = [
            {"N0": 30, "N1": 15, "N2": 12, "N3": 10, "N4": 7},
            {"N0": 28, "N1": 18, "N2": 13, "N3": 11, "N4": 6},
            {"N0": 32, "N1": 20, "N2": 14, "N3": 12, "N4": 5},
        ]
        trend = compute_trend(sessions)
        # dedup = 15/30, 18/28, 20/32 = 0.5, 0.643, 0.625
        assert trend["dedup"]["samples"] == 3
        assert 0.5 <= trend["dedup"]["min"] <= trend["dedup"]["mean"] <= trend["dedup"]["max"] <= 1.0

    def test_trend_handles_missing_stages(self):
        """部分 session 缺 N2 / N4, 只用有的计算."""
        from funnel_report import compute_trend
        sessions = [
            {"N0": 20, "N1": 10, "N2": None, "N3": 8, "N4": None},   # 老 session
            {"N0": 25, "N1": 15, "N2": 12, "N3": 10, "N4": 6},
        ]
        trend = compute_trend(sessions)
        # dedup 用 2 个样本, evidence_verify / pm 只用第二个
        assert trend["dedup"]["samples"] == 2
        assert trend["evidence_verify"]["samples"] == 1
        assert trend["pm"]["samples"] == 1


# ============================================================
# build_markdown — 结构完整性
# ============================================================

class TestBuildMarkdown:
    def test_contains_required_sections(self):
        from funnel_report import build_markdown
        sessions = [{
            "session_id": "rev_abc", "ts_start": "2026-04-24",
            "prd_files": ["未准入境需求.md"], "mode": "cli",
            "N0": 28, "N1": 15, "N2": 11, "N3": 10, "N4": 6,
            "retracted": 2, "downgraded": 3,
            "wiki_mode": "sparse", "authority_distribution": {"generated": 11},
            "delta_breakdown": {"merged_to_facet": 3},
            "rejected_by_reason": {"false_positive": 2},
            "suspicious_flags": ["dedup_retention_low_0.536"],
            "review_completed": True,
            "source_events": ["T3_N0", "T3_N1", "T3_N2", "T3_N3", "T3_N4", "T3_summary"],
        }]
        trend = {
            "dedup": {"min": 0.536, "mean": 0.536, "max": 0.536, "samples": 1},
            "evidence_verify": {"min": 0.733, "mean": 0.733, "max": 0.733, "samples": 1},
            "goshawk": {"min": 0.909, "mean": 0.909, "max": 0.909, "samples": 1},
            "pm": {"min": 0.6, "mean": 0.6, "max": 0.6, "samples": 1},
        }
        md = build_markdown("workspace-侵权软件", sessions, trend)
        assert "# Pecker 评审漏斗 · workspace-侵权软件" in md
        assert "stage count" in md
        assert "趋势" in md
        assert "数据源" in md
        # dedup retention 均值 < 0.6 → 应触发自动观察
        assert "dedup retention 均值" in md

    def test_auto_observations_fire_on_low_retention(self):
        """低 retention 自动观察触发."""
        from funnel_report import build_markdown
        sessions = [{
            "session_id": "rev_x", "prd_files": [], "mode": "",
            "N0": None, "N1": None, "N2": None, "N3": None, "N4": None,
            "retracted": None, "downgraded": None, "wiki_mode": None,
            "authority_distribution": {}, "delta_breakdown": None,
            "rejected_by_reason": {}, "suspicious_flags": [],
            "review_completed": False, "source_events": [],
        }]
        trend = {
            "goshawk": {"min": 0.5, "mean": 0.5, "max": 0.5, "samples": 1},   # < 0.7
        }
        md = build_markdown("ws-x", sessions, trend)
        assert "goshawk retention 均值 0.5" in md

    def test_reject_reason_aggregation(self):
        """多次 PM decision 的 reject reason 汇总跨 session."""
        from funnel_report import build_markdown
        sessions = [
            {"session_id": "s1", "prd_files": [], "mode": "", "N0": 0, "N1": 0,
             "N2": 0, "N3": 0, "N4": 0,
             "retracted": 0, "downgraded": 0, "wiki_mode": "rich",
             "authority_distribution": {}, "delta_breakdown": None,
             "rejected_by_reason": {"false_positive": 2, "wiki_missing": 1},
             "suspicious_flags": [], "review_completed": True, "source_events": ["T3_N4"]},
            {"session_id": "s2", "prd_files": [], "mode": "", "N0": 0, "N1": 0,
             "N2": 0, "N3": 0, "N4": 0,
             "retracted": 0, "downgraded": 0, "wiki_mode": "rich",
             "authority_distribution": {}, "delta_breakdown": None,
             "rejected_by_reason": {"false_positive": 1, "rule_too_strict": 3},
             "suspicious_flags": [], "review_completed": True, "source_events": ["T3_N4"]},
        ]
        md = build_markdown("ws", sessions, {})
        # 汇总: false_positive=3, wiki_missing=1, rule_too_strict=3
        assert "汇总 Reject 原因分布" in md
        assert "false_positive" in md
        assert "rule_too_strict" in md
