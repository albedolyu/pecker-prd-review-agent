"""Task A1 — feedback_cmd 模块测试 (TDD RED 阶段)

覆盖:
- scope 从 workspace 名推断 (workspace-对外投资 -> 对外投资)
- 最新 PRD 文件选择 (按 mtime)
- 完整 command block 生成
"""
import os
import tempfile
from pathlib import Path
import pytest
from feedback_cmd import build_feedback_command_block, _infer_scope, _latest_prd_file


def test_infer_scope_from_workspace():
    assert _infer_scope("workspace-对外投资") == "对外投资"
    assert _infer_scope("/abs/path/workspace-劳动仲裁") == "劳动仲裁"
    assert _infer_scope("workspace-foo") == "foo"
    assert _infer_scope("not-a-workspace") == ""


def test_latest_prd_file_picks_newest(tmp_path):
    prd_dir = tmp_path / "prd"
    prd_dir.mkdir()
    old = prd_dir / "old.md"
    new = prd_dir / "new.md"
    old.write_text("old")
    new.write_text("new")
    os.utime(old, (1000, 1000))
    os.utime(new, (2000, 2000))
    assert _latest_prd_file(str(tmp_path)).endswith("new.md")


def test_latest_prd_file_missing_dir_returns_none(tmp_path):
    assert _latest_prd_file(str(tmp_path)) is None


def test_build_feedback_command_block_contains_all_args(tmp_path):
    # 约定用一个假的 workspace 名
    ws_dir = tmp_path / "workspace-对外投资"
    ws_dir.mkdir()
    (ws_dir / "prd").mkdir()
    (ws_dir / "prd" / "投资.md").write_text("x")
    (ws_dir / "output").mkdir()
    report_path = ws_dir / "output" / "PRD_开发任务_20260415.md"
    block = build_feedback_command_block(
        workspace=str(ws_dir),
        prd_name="投资",
        report_path=str(report_path),
    )
    assert "## 🐦 下一步" in block
    assert "python feedback.py" in block
    assert "--code-dir" in block
    assert "--scope 对外投资" in block
    assert "PRD_开发任务_20260415.md" in block
    assert "投资.md" in block
