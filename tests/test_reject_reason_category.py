"""P0 step 2 (2026-04-28): 7 类 reject reason_category 端到端守护

题目要求 3 个核心场景:
- test_reject_with_category: API 接 reason_category 写到 jsonl (rule_perf + ground truth 都有)
- test_reject_no_category_defaults: 没传 category 默认 "model_noise"
- test_rule_perf_ema_uses_category: rule_perf 调权用 category 而非自由文本

补 2 条:
- Pydantic ConfirmRequest 422 — 非 7 种枚举值在 schema 层就拦掉, 不让坏数据写到 jsonl
- 7 类枚举与前端 REJECT_CATEGORIES 字面值同步 — 防前后端 enum drift

不跑 FastAPI 全链路, 直接调内部函数 + Pydantic 校验 (与 tests/test_review_confirm.py 同模式)
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.fixture
def tmp_workspace(monkeypatch, tmp_path):
    """临时 workspace + 把 get_project_root 重定向"""
    ws_name = "workspace-rcat"
    ws_dir = tmp_path / ws_name
    (ws_dir / "output").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        "api.routes.review.get_project_root", lambda: tmp_path, raising=True
    )
    return ws_name, ws_dir, tmp_path


def _make_item(item_id: str, rule_id: str, dimension: str = "结构层"):
    return {
        "id": item_id,
        "rule_id": rule_id,
        "dimension": dimension,
        "severity": "must",
        "location": "§3.1",
    }


# ============================================================
# 1. test_reject_with_category — API 接 reason_category 写到 jsonl
# ============================================================

def test_reject_with_category_writes_to_rule_perf_and_ground_truth(tmp_workspace):
    """端到端: 7 类 reject_with_category 都同时写到 rule_perf reject_by_reason +
    ground_truth jsonl. 这是 EMA feedback 闭环 + calibration 切片的核心写入路径."""
    from api.routes.review import (
        _update_rule_perf_from_decisions,
        _save_eval_ground_truth,
    )

    ws, ws_dir, tmp_path = tmp_workspace
    # 7 类各发 1 条 reject
    items = [
        _make_item(f"R-00{i+1}", f"RC-CAT-{i+1}") for i in range(7)
    ]
    categories = [
        "good_issue", "false_positive", "known_tradeoff", "wiki_missing",
        "rule_too_strict", "impl_detail", "model_noise",
    ]
    decisions = {
        f"R-00{i+1}": {
            "action": "reject",
            "reason_category": categories[i],
            "reason_note": f"PM 选了 {categories[i]} 的备注",
        }
        for i in range(7)
    }

    # 1. rule_perf reject_by_reason 桶: 7 个 rule 各自的桶都有 1 条对应 reason
    _update_rule_perf_from_decisions(items, decisions, ws)
    hist_path = ws_dir / "output" / "rule_performance_history.json"
    data = json.loads(hist_path.read_text(encoding="utf-8"))
    for i, cat in enumerate(categories):
        rule_id = f"RC-CAT-{i+1}"
        entry = data[rule_id]
        assert entry["stats"]["rejected"] == 1
        assert entry["stats"]["reject_by_reason"] == {cat: 1}, \
            f"{rule_id} 的 reject_by_reason 桶应只有 {cat}=1"

    # 2. ground_truth jsonl: 每条 item 带 reason_category + reason_note
    _save_eval_ground_truth(items, decisions, ws, "albedolyu")
    gt_dir = tmp_path / "eval" / "ground_truth"
    files = list(gt_dir.glob(f"rcat_albedolyu_*.json"))
    assert len(files) == 1
    payload = json.loads(files[0].read_text(encoding="utf-8"))
    gt_map = {gi["id"]: gi for gi in payload["items"]}
    for i, cat in enumerate(categories):
        gt = gt_map[f"R-00{i+1}"]
        assert gt["reason_category"] == cat
        assert gt["reason_note"] == f"PM 选了 {cat} 的备注"


# ============================================================
# 2. test_reject_no_category_defaults — 缺失 default model_noise
# ============================================================

def test_reject_no_category_defaults_to_model_noise(tmp_workspace):
    """老 payload (action 是 reject 但没 reason_category): 后端默认按 model_noise 记账,
    不阻塞流程, 只是会让周报上看到大量 model_noise 提示前端升级"""
    from api.routes.review import _update_rule_perf_from_decisions

    ws, ws_dir, _ = tmp_workspace
    items = [_make_item("R-001", "RC-LEG")]
    # 老 payload: 没 reason_category, 也没 reason 自由文本
    decisions = {"R-001": {"action": "reject"}}

    _update_rule_perf_from_decisions(items, decisions, ws)
    data = json.loads(
        (ws_dir / "output" / "rule_performance_history.json").read_text(encoding="utf-8")
    )
    bucket = data["RC-LEG"]["stats"]["reject_by_reason"]
    assert bucket == {"model_noise": 1}, "无 reason_category 默认走 model_noise 兜底"


# ============================================================
# 3. test_rule_perf_ema_uses_category — EMA 用 category 而非自由文本
# ============================================================

def test_rule_perf_ema_uses_category_not_free_text(tmp_workspace):
    """EMA impact_score 调权: 同样 reject 但 reason_category 不同 → delta 不同 → 分数不同.
    防回归: 老 payload 写自由文本 reason 会被 EMA 当 -0.3 兜底, 不会影响 reason_category 分档."""
    from api.routes.review import _update_rule_perf_from_decisions

    ws, ws_dir, _ = tmp_workspace
    # 三个 rule, 同 1 条 reject:
    # - RC-FP: false_positive (-0.5 强)
    # - RC-WM: wiki_missing (-0.1 弱)
    # - RC-OLD: 老 payload, 自由文本 reason="规则太严" (走 model_noise -0.3)
    items = [
        _make_item("R-FP", "RC-FP"),
        _make_item("R-WM", "RC-WM"),
        _make_item("R-OLD", "RC-OLD"),
    ]
    decisions = {
        "R-FP": {"action": "reject", "reason_category": "false_positive"},
        "R-WM": {"action": "reject", "reason_category": "wiki_missing"},
        "R-OLD": {"action": "reject", "reason": "规则太严"},  # 自由文本不会被 EMA 解读为 rule_too_strict
    }

    _update_rule_perf_from_decisions(items, decisions, ws)
    data = json.loads(
        (ws_dir / "output" / "rule_performance_history.json").read_text(encoding="utf-8")
    )
    fp_score = data["RC-FP"]["impact_score"]
    wm_score = data["RC-WM"]["impact_score"]
    old_score = data["RC-OLD"]["impact_score"]

    # false_positive (-0.5) 应该比 wiki_missing (-0.1) 更狠
    assert fp_score < wm_score, "false_positive EMA 应低于 wiki_missing"
    # 自由文本 reason 不被 EMA 当成 rule_too_strict (-0.5), 走 model_noise 默认 (-0.3)
    # 即 RC-OLD 的分数应该介于 RC-FP (-0.5) 和 RC-WM (-0.1) 之间
    assert fp_score < old_score < wm_score, (
        "老 payload 自由文本 reason 不应被解读为 rule_too_strict 强惩罚, "
        "而是走 model_noise 兜底 → score 介于强/弱惩罚之间"
    )


# ============================================================
# 4. Pydantic 422: 非 7 种枚举值 schema 层拦掉
# ============================================================

def test_confirm_request_rejects_unknown_reason_category():
    """ConfirmRequest validator: reason_category 必须是 7 种枚举之一,
    防前端传 'too_strict' 这种相近但拼错的值默默被忽略写到 jsonl 污染数据."""
    from pydantic import ValidationError
    from api.models import ConfirmRequest

    bad_payload = {
        "review_result": {"items": [], "signature": "fake"},  # signature 校验在 endpoint 里, 不影响 schema 校验
        "decisions": {
            "R-001": {"action": "reject", "reason_category": "too_strict"},  # 拼错
        },
    }
    with pytest.raises(ValidationError) as exc_info:
        ConfirmRequest(**bad_payload)
    msg = str(exc_info.value)
    assert "reason_category" in msg
    assert "too_strict" in msg


def test_confirm_request_accepts_all_seven_valid_reasons():
    """7 种合法值都能过 Pydantic 校验, 防 enum drift."""
    from api.models import ConfirmRequest

    for cat in [
        "good_issue", "false_positive", "known_tradeoff", "wiki_missing",
        "rule_too_strict", "impl_detail", "model_noise",
    ]:
        ConfirmRequest(
            review_result={"items": [], "signature": "fake"},
            decisions={"R-001": {"action": "reject", "reason_category": cat}},
        )


def test_confirm_request_allows_missing_reason_category():
    """老 payload 没 reason_category 字段: 通过 schema 校验 (后端 _update 函数走 model_noise 默认)."""
    from api.models import ConfirmRequest

    # 三种历史 payload 形态都应过 schema:
    ConfirmRequest(
        review_result={"items": [], "signature": "fake"},
        decisions={"R-001": {"action": "reject"}},  # 纯老
    )
    ConfirmRequest(
        review_result={"items": [], "signature": "fake"},
        decisions={"R-001": {"action": "reject", "reason": "自由文本"}},  # v0 自由文本
    )
    ConfirmRequest(
        review_result={"items": [], "signature": "fake"},
        decisions={"R-001": {"action": "accept"}},  # accept 无 reason
    )


# ============================================================
# 5. enum drift 守护 — 后端 7 种 == 前端 web/components/phases/Phase3ConfirmV8.tsx
#    REJECT_CATEGORIES 的 value 列表
# ============================================================

def test_reject_categories_synced_with_frontend(tmp_path):
    """前后端 reject 7 类 enum 必须一致. 防只改一边导致前端选了某 reason 后端 422.

    如果改了 7 类, 这个测试会失败提示双边一起改.
    """
    import re

    from models import RejectReason

    backend_values = sorted({r.value for r in RejectReason})

    project_root = Path(__file__).resolve().parent.parent
    tsx_path = project_root / "web" / "components" / "phases" / "Phase3ConfirmV8.tsx"
    if not tsx_path.is_file():
        pytest.skip(f"Phase3ConfirmV8.tsx 不存在: {tsx_path}")

    tsx_text = tsx_path.read_text(encoding="utf-8")
    # 抓 REJECT_CATEGORIES (可带 TS 类型注解) = [...] 块里的 value: "..." 字段
    m = re.search(
        r"REJECT_CATEGORIES\b[^=]*=\s*\[(.*?)\];", tsx_text, re.DOTALL
    )
    assert m, "Phase3ConfirmV8.tsx 应定义 REJECT_CATEGORIES 数组 (P0 step 2 需求)"
    block = m.group(1)
    frontend_values = sorted(re.findall(r'value:\s*"([^"]+)"', block))

    assert frontend_values == backend_values, (
        f"前端 REJECT_CATEGORIES value 列表必须与后端 RejectReason 7 种一致.\n"
        f"  backend: {backend_values}\n"
        f"  frontend: {frontend_values}\n"
        f"  diff backend - frontend: {set(backend_values) - set(frontend_values)}\n"
        f"  diff frontend - backend: {set(frontend_values) - set(backend_values)}"
    )
