"""Task B3 — feedback.py scan 模式 + 去重 + pigeon_run 日志测试 (TDD RED)

覆盖:
- _append_rule_history 对 (date, outcome, prd, sha) 去重
- _write_pigeon_run_log 按时间戳落盘
- _cleanup_old_pigeon_runs 清理 30 天前日志
"""
import json
import os
import time
from pathlib import Path
import pytest

import feedback


def test_append_rule_history_dedups_same_entry(tmp_path):
    """同一条 (rule_id, date, outcome, sha) 不应该在 history 里追加两次。

    _extract_rule_id 从 `location` 字段提取 RC-xxx / V-xx / BMAD V-xx 格式。
    """
    workspace = str(tmp_path)
    os.makedirs(os.path.join(workspace, "output"))

    outcomes = [
        {
            "location": "RC-001 字段缺失",
            "outcome": "effective_catch",
            "commit_sha": "sha1abc",
        },
    ]
    feedback._append_rule_history(outcomes, workspace, prd_name="test_prd")
    feedback._append_rule_history(outcomes, workspace, prd_name="test_prd")

    history_path = os.path.join(workspace, "output", "rule_performance_history.json")
    assert os.path.isfile(history_path), "rule_performance_history.json 没生成"
    with open(history_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    # 两次同样的 outcome 应该只追加 1 条 history
    assert len(data["RC-001"]["history"]) == 1, f"去重失败,实际 history: {data['RC-001']['history']}"


def test_append_rule_history_different_sha_not_deduped(tmp_path):
    """不同 commit_sha 应当作为不同信号保留。"""
    workspace = str(tmp_path)
    os.makedirs(os.path.join(workspace, "output"))

    feedback._append_rule_history(
        [{"location": "RC-002", "outcome": "effective_catch", "commit_sha": "sha_a"}],
        workspace, prd_name="p",
    )
    feedback._append_rule_history(
        [{"location": "RC-002", "outcome": "effective_catch", "commit_sha": "sha_b"}],
        workspace, prd_name="p",
    )

    with open(os.path.join(workspace, "output", "rule_performance_history.json"), "r", encoding="utf-8") as f:
        data = json.load(f)
    assert len(data["RC-002"]["history"]) == 2


def test_pigeon_run_log_created(tmp_path):
    """_write_pigeon_run_log 应当按时间戳落盘到 pigeon_runs/"""
    workspace = str(tmp_path)
    feedback._write_pigeon_run_log(
        workspace=workspace,
        run_id="test_run_001",
        triggered_by="manual",
        repos_scanned=["/fake/repo"],
        signals_collected=5,
        signal_types_count={"commit_issue_link": 3, "test_skip_for_prd": 2},
        rule_perf_updated=["R-001"],
        errors=[],
    )
    runs_dir = Path(workspace) / "output" / "pigeon_runs"
    files = list(runs_dir.glob("pigeon_run_*.json"))
    assert len(files) == 1
    with open(files[0], "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data["run_id"] == "test_run_001"
    assert data["triggered_by"] == "manual"
    assert data["signals_collected"] == 5
    assert data["errors"] == []


def test_cleanup_old_pigeon_runs_removes_old_files(tmp_path):
    """_cleanup_old_pigeon_runs 应当清理 30 天前的日志"""
    workspace = str(tmp_path)
    runs_dir = Path(workspace) / "output" / "pigeon_runs"
    runs_dir.mkdir(parents=True)

    # 一个新文件,一个老文件 (mtime 设置为 40 天前)
    new_file = runs_dir / "pigeon_run_20260415_120000.json"
    old_file = runs_dir / "pigeon_run_20260301_120000.json"
    new_file.write_text("{}")
    old_file.write_text("{}")

    old_ts = time.time() - 40 * 86400
    os.utime(old_file, (old_ts, old_ts))

    feedback._cleanup_old_pigeon_runs(workspace, keep_days=30)

    assert new_file.exists(), "新文件被误删"
    assert not old_file.exists(), "老文件没被清理"
