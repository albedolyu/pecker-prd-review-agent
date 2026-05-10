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
    # 只有 V-05 被记录 (过滤 __meta__ schema 版本 key, 2026-04-23 #3 加)
    rule_keys = [k for k in data.keys() if k != "__meta__"]
    assert rule_keys == ["V-05"]


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

    _save_eval_ground_truth(
        items,
        decisions,
        ws,
        reviewer="tester",
        prd_name="单测 PRD.md",
        review_id="run-test",
    )

    gt_dir = tmp_path / "eval" / "ground_truth"
    gt_files = list(gt_dir.glob("*.json"))
    assert len(gt_files) == 1, "应生成一个 ground_truth 文件"
    payload = json.loads(gt_files[0].read_text(encoding="utf-8"))
    assert payload["reviewer"] == "tester"
    assert payload["prd_name"] == "单测 PRD.md"
    assert payload["review_id"] == "run-test"
    # rtest 会被去掉 workspace- 前缀
    assert "rtest" in payload["workspace"] or payload["workspace"] == ws
    assert len(payload["items"]) == 3
    tp_map = {it["id"]: it["is_true_positive"] for it in payload["items"]}
    assert tp_map["R-001"] is True
    assert tp_map["R-002"] is False
    assert tp_map["R-003"] is True
    assert all("dimension" in it for it in payload["items"])


def test_ground_truth_empty_decisions_does_nothing(tmp_workspace, tmp_path):
    ws, _ = tmp_workspace
    (tmp_path / "eval" / "ground_truth").mkdir(parents=True, exist_ok=True)
    _save_eval_ground_truth([], {}, ws, reviewer="tester")
    # 没决策不应产生文件
    gt_files = list((tmp_path / "eval" / "ground_truth").glob("*.json"))
    assert len(gt_files) == 0


def test_ground_truth_filename_stays_inside_directory(tmp_workspace, tmp_path):
    """workspace/reviewer 异常时,ground truth 文件名也不能路径穿越。"""
    (tmp_path / "eval" / "ground_truth").mkdir(parents=True, exist_ok=True)
    items = [_make_item("R-001", "V-05")]

    _save_eval_ground_truth(
        items,
        {"R-001": {"action": "accept"}},
        workspace="workspace-..\\outside",
        reviewer="..\\alice/role",
        prd_name="demo",
        review_id="run-test",
    )

    gt_dir = tmp_path / "eval" / "ground_truth"
    gt_files = list(gt_dir.glob("*.json"))
    assert len(gt_files) == 1
    assert gt_dir.resolve() in gt_files[0].resolve().parents


def test_ground_truth_filename_redacts_secrets(tmp_workspace, tmp_path):
    """workspace/reviewer 误带 API key 时,ground truth 文件名不能泄露 secret。"""
    (tmp_path / "eval" / "ground_truth").mkdir(parents=True, exist_ok=True)
    fake_key = "sk-01234567890abcdefABCDEFghij"
    items = [_make_item("R-001", "V-05")]

    _save_eval_ground_truth(
        items,
        {"R-001": {"action": "accept"}},
        workspace=f"workspace-alpha-{fake_key}",
        reviewer=f"alice-{fake_key}",
        prd_name="demo",
        review_id="run-test",
    )

    gt_files = list((tmp_path / "eval" / "ground_truth").glob("*.json"))
    assert len(gt_files) == 1
    assert fake_key not in gt_files[0].name
    assert "REDACTED_SECRET" in gt_files[0].name


def test_confirm_report_markdown_redacts_secret_metadata():
    """Confirm 返回的 Markdown 头部不能回显 PRD 名称/空间/评审人里的密钥。"""
    from review.post_review_contract import build_confirm_report_markdown

    fake_key = "sk-01234567890abcdefABCDEFghij"
    report = build_confirm_report_markdown(
        {
            "prd_name": f"demo-{fake_key}",
            "reviewer": f"alice-{fake_key}",
            "workspace": f"workspace-alpha-{fake_key}",
            "mode": "standard",
            "review_id": "rev_test",
            "items": [],
        },
        {},
    )

    assert fake_key not in report
    assert report.count("[REDACTED_SECRET]") == 3


@pytest.mark.asyncio
async def test_confirm_review_returns_backend_report_markdown(tmp_workspace, monkeypatch):
    """Web confirm 应返回后端生成的报告 markdown,供 Phase4 复用同源报告。"""
    import os as _os
    from api.models import ConfirmRequest, ReviewResult
    from api.routes.review import confirm_review

    _os.environ["PECKER_SIGNATURE_SECRET"] = "unit-test-signature-secret-32-chars"
    ws, _ = tmp_workspace
    rr = ReviewResult.create(
        reviewer="alice",
        workspace=ws,
        prd_name="demo",
        mode="standard",
        merged_items=[{
            "id": "R-001",
            "rule_id": "V-05",
            "dimension": "structure",
            "issue": "缺少验收标准",
            "suggestion": "补充可执行验收标准",
            "severity": "must",
        }],
        workers=[],
        usage={},
    )
    req = ConfirmRequest(
        review_result=rr.model_dump(),
        decisions={"R-001": {"action": "accept"}},
    )

    monkeypatch.setattr(
        "api.routes.review.require_workspace_access", lambda *args, **kwargs: None,
        raising=True,
    )
    monkeypatch.setattr(
        "api.routes.review.get_workspace_dir", lambda name: name,
        raising=True,
    )

    resp = await confirm_review(req, user={"reviewer": "alice"})

    assert resp["status"] == "confirmed"
    assert "report_markdown" in resp
    assert "PRD 评审报告 - demo" in resp["report_markdown"]
    assert "下游实现约定" in resp["report_markdown"]


@pytest.mark.asyncio
async def test_confirm_review_ignores_stale_decisions_in_response_counts(tmp_workspace, monkeypatch):
    """前端草稿残留旧 item_id 时,确认结果计数不能出现负待决或误计数。"""
    import os as _os
    from api.models import ConfirmRequest, ReviewResult
    from api.routes.review import confirm_review

    _os.environ["PECKER_SIGNATURE_SECRET"] = "unit-test-signature-secret-32-chars"
    ws, _ = tmp_workspace
    rr = ReviewResult.create(
        reviewer="alice",
        workspace=ws,
        prd_name="demo",
        mode="standard",
        merged_items=[{
            "id": "R-001",
            "rule_id": "V-05",
            "dimension": "structure",
            "issue": "缺少验收标准",
            "suggestion": "补充可执行验收标准",
            "severity": "must",
        }],
        workers=[],
        usage={},
    )
    req = ConfirmRequest(
        review_result=rr.model_dump(),
        decisions={
            "R-001": {"action": "accept"},
            "R-STALE": {"action": "reject", "reason_category": "model_noise"},
        },
    )

    monkeypatch.setattr(
        "api.routes.review.require_workspace_access", lambda *args, **kwargs: None,
        raising=True,
    )
    monkeypatch.setattr(
        "api.routes.review.get_workspace_dir", lambda name: name,
        raising=True,
    )

    resp = await confirm_review(req, user={"reviewer": "alice"})

    assert resp["accepted"] == 1
    assert resp["rejected"] == 0
    assert resp["edited"] == 0
    assert resp["pending"] == 0
    assert resp["total"] == 1


@pytest.mark.asyncio
async def test_confirm_review_recovers_authoritative_result_from_job_store(tmp_workspace, monkeypatch):
    """If a reconnect draft carries a stale handle, trust the server job result."""
    import os as _os
    from api.models import ConfirmRequest, ReviewResult
    from api.routes.review import confirm_review

    _os.environ["PECKER_SIGNATURE_SECRET"] = "unit-test-signature-secret-32-chars"
    ws, _ = tmp_workspace
    rr = ReviewResult.create(
        reviewer="alice",
        workspace=ws,
        prd_name="demo",
        mode="standard",
        merged_items=[{
            "id": "R-001",
            "rule_id": "V-06",
            "dimension": "structure",
            "issue": "缺少空态处理",
            "suggestion": "补充空态",
            "severity": "must",
        }],
        workers=[],
        usage={},
    )
    trusted_result = rr.model_dump()
    trusted_result["items"][0]["issue"] = "服务端 job 里的权威问题描述"
    trusted_result["items"][0]["problem"] = "服务端 job 里的权威问题描述"
    stale_handle = json.loads(json.dumps(trusted_result, ensure_ascii=False))
    stale_handle["items"][0]["issue"] = "browser-side stale copy"
    stale_handle["items"][0]["problem"] = "browser-side stale copy"

    class FakeJobStore:
        def list_jobs(self, *, owner: str = "", admin: bool = False, limit: int = 50):
            return [{
                "job_id": "rjob_test",
                "owner": "alice",
                "status": "done",
                "result": trusted_result,
            }]

    monkeypatch.setattr(
        "api.review_jobs.review_job_store",
        FakeJobStore(),
        raising=False,
    )
    monkeypatch.setattr(
        "api.routes.review.is_admin",
        lambda user: False,
        raising=False,
    )
    monkeypatch.setattr(
        "api.routes.review.require_workspace_access", lambda *args, **kwargs: None,
        raising=True,
    )
    monkeypatch.setattr(
        "api.routes.review.get_workspace_dir", lambda name: name,
        raising=True,
    )

    req = ConfirmRequest(
        review_result=stale_handle,
        decisions={"R-001": {"action": "reject", "reason_category": "model_noise"}},
    )

    resp = await confirm_review(req, user={"reviewer": "alice"})

    assert resp["status"] == "confirmed"
    assert resp["review_id"] == trusted_result["review_id"]
    assert resp["rejected"] == 1
    assert "服务端 job 里的权威问题描述" in resp["report_markdown"]
    assert "缺少空态处理" not in resp["report_markdown"]
    assert "browser-side stale copy" not in resp["report_markdown"]
