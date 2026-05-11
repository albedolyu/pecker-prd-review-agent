from __future__ import annotations

import json


def _write_session(root, name: str, events: list[dict]):
    path = root / "workspace-alpha" / "output" / "sessions" / f"{name}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(event, ensure_ascii=False) + "\n" for event in events),
        encoding="utf-8",
    )
    return path


def test_classify_goshawk_failure_types():
    from scripts.goshawk_failure_triage import classify_failure_type

    assert classify_failure_type({"error": "TimeoutError: request timed out"}) == "timeout"
    assert classify_failure_type({"error": "JSONDecodeError: unexpected EOF"}) == "json_parse"
    assert classify_failure_type({"error": "API Error 401 authentication_error"}) == "auth_401"
    assert classify_failure_type({"error": "empty output from model"}) == "empty_output"
    assert classify_failure_type({"error": "expected str, bytes or os.PathLike object, not NoneType"}) == "filesystem_path"
    assert classify_failure_type({"error": "[WinError 206] 文件名或扩展名太长。"}) == "filesystem_path"
    assert classify_failure_type({"verdict": "SILENT"}) == "empty_output"
    assert classify_failure_type({"error": "provider exploded"}) == "other"
    assert classify_failure_type({"verdict": "REVIEWED"}) == "success"


def test_triage_recent_sessions_groups_type_model_and_samples(tmp_path):
    from scripts.goshawk_failure_triage import triage_goshawk_failures

    _write_session(
        tmp_path,
        "rev_001",
        [
            {"type": "worker_done", "dim": "structure", "items_count": 2},
            {"type": "final_reviewer_done", "model": "gpt-5.5", "verdict": "REVIEWED"},
        ],
    )
    _write_session(
        tmp_path,
        "rev_002",
        [
            {"type": "worker_done", "dim": "structure", "items_count": 2},
            {
                "type": "final_reviewer_done",
                "model": "gpt-5.5",
                "error": "TimeoutError: request timed out after 10s",
            },
        ],
    )
    _write_session(
        tmp_path,
        "rev_003",
        [
            {"type": "worker_done", "dim": "structure", "items_count": 2},
            {
                "type": "final_reviewer_done",
                "model": "claude-sonnet",
                "error": "JSONDecodeError: unexpected EOF at line 1",
            },
        ],
    )

    report = triage_goshawk_failures(tmp_path, recent=50)

    assert report["total"] == 3
    assert report["failed"] == 2
    assert report["failure_rate"] == 0.6667
    assert report["by_type"]["timeout"]["count"] == 1
    assert report["by_type"]["json_parse"]["count"] == 1
    assert report["by_model"]["gpt-5.5"]["failed"] == 1
    assert report["by_model"]["claude-sonnet"]["failed"] == 1
    assert "request timed out" in report["by_type"]["timeout"]["samples"][0]
