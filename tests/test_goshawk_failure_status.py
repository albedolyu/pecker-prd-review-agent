from __future__ import annotations

import json


def _session_file(tmp_path, name, events):
    path = tmp_path / f"workspace-{name}" / "output" / "sessions" / f"{name}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(event, ensure_ascii=False) + "\n" for event in events),
        encoding="utf-8",
    )


def test_generate_status_exposes_goshawk_failure_type_distribution(tmp_path, monkeypatch):
    import scripts.generate_status as gs

    _session_file(tmp_path, "timeout", [
        {"type": "worker_done", "dim": "structure", "items_count": 3, "error": None},
        {"type": "final_reviewer_done", "error": "TimeoutError: request timed out"},
    ])
    _session_file(tmp_path, "parse", [
        {"type": "worker_done", "dim": "structure", "items_count": 3, "error": None},
        {"type": "final_reviewer_done", "error": "JSONDecodeError: unexpected EOF"},
    ])
    _session_file(tmp_path, "ok", [
        {"type": "worker_done", "dim": "structure", "items_count": 3, "error": None},
        {"type": "final_reviewer_done", "verdict": "REVIEWED"},
    ])
    monkeypatch.setattr(gs, "ROOT", tmp_path)

    stats = gs.collect_session_stats()

    assert stats["goshawk_failure_types"] == {
        "timeout": 1,
        "json_parse": 1,
    }


def test_generate_status_renders_goshawk_failure_gate():
    import scripts.generate_status as gs

    report = gs.format_report(
        git_info={"days": 14, "commit_count": 0, "recent_commits": []},
        test_info={"collected": 1},
        code_info={"file_count": 1, "total_lines": 1},
        session_info={
            "sessions": 3,
            "outcomes": {"productive": 3},
            "effective_consistency": 1.0,
            "quota_hit_rate": 0,
            "auth_expired_rate": 0,
            "items_median": 2,
            "completion_rate": 1.0,
            "checkpoint_rate": 1.0,
            "final_reviewer_failure_rate": 0.2,
            "worker_silent_rate": {},
            "worker_confirmed_empty": {},
            "goshawk": {},
            "goshawk_failure_types": {"timeout": 1},
        },
    )

    assert "[FAIL] 苍鹰失败率 20.0% > 15%" in report
    assert "### 苍鹰失败类型分布" in report
