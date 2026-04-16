"""R14: 单测 Phase 3 确认路径的反馈回流逻辑

覆盖 `api/routes/review.py:_update_rule_perf_from_decisions` — 这是 Web
决策 → rule_performance_history.json EMA 更新 的核心链路，属于 2026-04-15
commit 596d121 的回流改动，原先完全没有回归保护。

不跑 FastAPI 全链路，只测纯函数逻辑（构造 items + decisions + workspace 后
直接调用，读 output/rule_performance_history.json 验证写入）。
"""
import json
import os
import shutil
import tempfile
from pathlib import Path

import pytest

from api.routes.review import (
    _update_rule_perf_from_decisions,
    _save_eval_ground_truth,
)


@pytest.fixture
def tmp_workspace(monkeypatch, tmp_path):
    """临时 workspace 目录 + 把 get_project_root 重定向过去"""
    ws_name = "workspace-rtest"
    ws_dir = tmp_path / ws_name
    (ws_dir / "output").mkdir(parents=True, exist_ok=True)

    def _fake_root():
        return tmp_path

    # 打补丁到 api.routes.review.get_project_root
    monkeypatch.setattr(
        "api.routes.review.get_project_root", _fake_root, raising=True
    )
    return ws_name, ws_dir


# ==========================================================
# _update_rule_perf_from_decisions
# ==========================================================

def _make_item(item_id: str, rule_id: str, dimension: str = "结构层"):
    return {
        "id": item_id,
        "rule_id": rule_id,
        "dimension": dimension,
        "severity": "must",
        "location": "§3.1",
    }


def test_accept_updates_confirmed_count(tmp_workspace):
    ws, ws_dir = tmp_workspace
    items = [_make_item("R-001", "V-05")]
    decisions = {"R-001": {"action": "accept"}}

    _update_rule_perf_from_decisions(items, decisions, ws)

    hist_path = ws_dir / "output" / "rule_performance_history.json"
    assert hist_path.exists(), "history 文件应被创建"
    data = json.loads(hist_path.read_text(encoding="utf-8"))
    assert "V-05" in data
    entry = data["V-05"]
    assert entry["stats"]["confirmed"] == 1
    assert entry["stats"]["rejected"] == 0
    assert entry["stats"]["total"] == 1
    # EMA: accept delta=+1.0, alpha=0.15, old=0.5 -> 0.575
    assert abs(entry["impact_score"] - 0.575) < 0.01
    assert entry["rejection_rate"] == 0.0
    assert entry["is_noisy"] is False


def test_reject_updates_rejected_count_and_rate(tmp_workspace):
    ws, _ = tmp_workspace
    items = [_make_item("R-001", "V-07"), _make_item("R-002", "V-07")]
    decisions = {
        "R-001": {"action": "reject"},
        "R-002": {"action": "reject"},
    }

    _update_rule_perf_from_decisions(items, decisions, ws)

    ws_dir = Path(os.environ.get("_TEST_TMP", "")) or None  # fallback
    hist_path = Path("api").parent / ws / "output" / "rule_performance_history.json"
    # 通过 fixture 的 tmp_path 定位
    # 更健壮的方式: 重读文件
    from api.routes.review import get_project_root
    hist = Path(get_project_root()) / ws / "output" / "rule_performance_history.json"
    data = json.loads(hist.read_text(encoding="utf-8"))
    entry = data["V-07"]
    assert entry["stats"]["rejected"] == 2
    assert entry["stats"]["confirmed"] == 0
    assert entry["rejection_rate"] == 1.0
    # EMA: 两次 reject delta=-0.5,应降 impact_score
    assert entry["impact_score"] < 0.5


def test_edit_counts_as_confirmed(tmp_workspace):
    ws, _ = tmp_workspace
    items = [_make_item("R-001", "RC-009")]
    decisions = {"R-001": {"action": "edit"}}

    _update_rule_perf_from_decisions(items, decisions, ws)

    from api.routes.review import get_project_root
    hist = Path(get_project_root()) / ws / "output" / "rule_performance_history.json"
    data = json.loads(hist.read_text(encoding="utf-8"))
    entry = data["RC-009"]
    assert entry["stats"]["confirmed"] == 1, "edit 视为认可问题,算 confirmed"
    assert entry["stats"]["rejected"] == 0
    # edit delta=+0.7,小于 accept 的 +1.0
    assert entry["impact_score"] > 0.5
    assert entry["impact_score"] < 0.575  # 比 accept 低


def test_items_without_rule_id_are_skipped(tmp_workspace):
    ws, _ = tmp_workspace
    items = [
        {"id": "R-001", "rule_id": "", "dimension": "结构层"},  # 空 rule_id
        {"id": "R-002", "dimension": "结构层"},  # 无 rule_id 字段
        _make_item("R-003", "V-05"),
    ]
    decisions = {
        "R-001": {"action": "accept"},
        "R-002": {"action": "accept"},
        "R-003": {"action": "accept"},
    }

    _update_rule_perf_from_decisions(items, decisions, ws)

    from api.routes.review import get_project_root
    hist = Path(get_project_root()) / ws / "output" / "rule_performance_history.json"
    data = json.loads(hist.read_text(encoding="utf-8"))
    # 只有 V-05 被记录
    assert list(data.keys()) == ["V-05"]


def test_noisy_flag_set_when_rejection_rate_exceeds_threshold(tmp_workspace):
    ws, _ = tmp_workspace
    # 5 次决策，4 次 reject 1 次 accept -> rejection_rate = 0.8 > 0.4
    items = [_make_item(f"R-{i:03d}", "V-99") for i in range(5)]
    decisions = {}
    for i in range(4):
        decisions[f"R-{i:03d}"] = {"action": "reject"}
    decisions["R-004"] = {"action": "accept"}

    _update_rule_perf_from_decisions(items, decisions, ws)

    from api.routes.review import get_project_root
    hist = Path(get_project_root()) / ws / "output" / "rule_performance_history.json"
    data = json.loads(hist.read_text(encoding="utf-8"))
    entry = data["V-99"]
    assert entry["rejection_rate"] == 0.8
    assert entry["is_noisy"] is True


def test_incremental_updates_across_multiple_calls(tmp_workspace):
    """后续调用应累加到已有 history,不覆盖"""
    ws, _ = tmp_workspace
    items = [_make_item("R-001", "V-05")]

    # 第一次 accept
    _update_rule_perf_from_decisions(items, {"R-001": {"action": "accept"}}, ws)
    # 第二次 reject (同一 rule_id)
    items2 = [_make_item("R-010", "V-05")]
    _update_rule_perf_from_decisions(items2, {"R-010": {"action": "reject"}}, ws)

    from api.routes.review import get_project_root
    hist = Path(get_project_root()) / ws / "output" / "rule_performance_history.json"
    data = json.loads(hist.read_text(encoding="utf-8"))
    entry = data["V-05"]
    assert entry["stats"]["total"] == 2
    assert entry["stats"]["confirmed"] == 1
    assert entry["stats"]["rejected"] == 1
    assert entry["rejection_rate"] == 0.5


def test_empty_decisions_does_nothing(tmp_workspace):
    ws, ws_dir = tmp_workspace
    items = [_make_item("R-001", "V-05")]

    _update_rule_perf_from_decisions(items, {}, ws)

    hist_path = ws_dir / "output" / "rule_performance_history.json"
    # 没 decision 就不写文件（函数会跳过写入）
    assert not hist_path.exists()


# ==========================================================
# _save_eval_ground_truth
# ==========================================================

def test_ground_truth_saves_true_positive_flag(tmp_workspace, monkeypatch, tmp_path):
    ws, _ = tmp_workspace
    # ground_truth 写到 project_root/eval/ground_truth/
    (tmp_path / "eval" / "ground_truth").mkdir(parents=True, exist_ok=True)

    items = [
        _make_item("R-001", "V-05"),
        _make_item("R-002", "V-07"),
        _make_item("R-003", "V-09"),
    ]
    decisions = {
        "R-001": {"action": "accept"},  # true positive
        "R-002": {"action": "reject"},  # false positive
        "R-003": {"action": "edit"},    # true positive (edit 也算)
    }

    _save_eval_ground_truth(items, decisions, ws, reviewer="tester")

    gt_dir = tmp_path / "eval" / "ground_truth"
    gt_files = list(gt_dir.glob("*.json"))
    assert len(gt_files) == 1, "应生成一个 ground_truth 文件"
    payload = json.loads(gt_files[0].read_text(encoding="utf-8"))
    assert payload["reviewer"] == "tester"
    # rtest 会被去掉 workspace- 前缀
    assert "rtest" in payload["workspace"] or payload["workspace"] == ws
    assert len(payload["items"]) == 3
    tp_map = {it["id"]: it["is_true_positive"] for it in payload["items"]}
    assert tp_map["R-001"] is True
    assert tp_map["R-002"] is False
    assert tp_map["R-003"] is True


def test_ground_truth_empty_decisions_does_nothing(tmp_workspace, tmp_path):
    ws, _ = tmp_workspace
    (tmp_path / "eval" / "ground_truth").mkdir(parents=True, exist_ok=True)
    _save_eval_ground_truth([], {}, ws, reviewer="tester")
    # 没决策不应产生文件
    gt_files = list((tmp_path / "eval" / "ground_truth").glob("*.json"))
    assert len(gt_files) == 0
