"""T2: reject_reason 7 分类 + delta 分档 + rule_perf 分桶 (2026-04-24).

spec: docs/pm-reject-reason-schema.md

测试矩阵:
- RejectReason enum 7 个 value 稳定
- PMDecision dataclass 从 dict 构造兼容老 reason 字段
- reject_delta_for_reason 7 种 reason 返回预期 delta + 未知 reason 兜底 -0.3
- _update_rule_perf_from_decisions 走完:
  * reject_by_reason 正确分桶
  * impact_score 按 reason 分档变动 (wiki_missing 弱惩罚 vs false_positive 强惩罚)
  * 兼容老 payload (无 reason_category 默认 model_noise)
"""
from __future__ import annotations

import pytest


# ============================================================
# RejectReason 枚举稳定性
# ============================================================

def test_reject_reason_enum_values():
    from models import RejectReason
    expected = {
        "good_issue",
        "false_positive",
        "known_tradeoff",
        "wiki_missing",
        "rule_too_strict",
        "impl_detail",
        "model_noise",
    }
    actual = {r.value for r in RejectReason}
    assert actual == expected


# ============================================================
# reject_delta_for_reason 分档
# ============================================================

class TestRejectDeltaForReason:
    def test_strong_penalty_rule_problems(self):
        """规则精度问题: false_positive / rule_too_strict → -0.5."""
        from models import reject_delta_for_reason
        assert reject_delta_for_reason("false_positive") == -0.5
        assert reject_delta_for_reason("rule_too_strict") == -0.5

    def test_medium_penalty_scope_model(self):
        """scope/模型问题: model_noise / impl_detail → -0.3."""
        from models import reject_delta_for_reason
        assert reject_delta_for_reason("model_noise") == -0.3
        assert reject_delta_for_reason("impl_detail") == -0.3

    def test_weak_penalty_non_rule_issues(self):
        """非规则问题: wiki_missing / known_tradeoff → -0.1 (不让规则背锅)."""
        from models import reject_delta_for_reason
        assert reject_delta_for_reason("wiki_missing") == -0.1
        assert reject_delta_for_reason("known_tradeoff") == -0.1

    def test_good_issue_positive_delta(self):
        """PM 手滑/改主意 → +0.3 正向微调."""
        from models import reject_delta_for_reason
        assert reject_delta_for_reason("good_issue") == 0.3

    def test_unknown_reason_safe_default(self):
        """未知 reason → -0.3 (model_noise 等价, 保守兜底)."""
        from models import reject_delta_for_reason
        assert reject_delta_for_reason("some_new_reason") == -0.3
        assert reject_delta_for_reason("") == -0.3


# ============================================================
# PMDecision dataclass 从 dict 构造 + 兼容老 payload
# ============================================================

class TestPMDecisionFromDict:
    def test_new_payload_with_reason_category(self):
        from models import PMDecision
        d = {
            "action": "reject",
            "reason_category": "false_positive",
            "reason_note": "第 3 节已有说明",
        }
        pm = PMDecision.from_dict("R-001", d)
        assert pm.item_id == "R-001"
        assert pm.action == "reject"
        assert pm.reason_category == "false_positive"
        assert pm.reason_note == "第 3 节已有说明"

    def test_old_payload_reason_maps_to_reason_note(self):
        """旧 payload 只有 reason 自由文本 → 映射到 reason_note, reason_category 为空."""
        from models import PMDecision
        d = {"action": "reject", "reason": "自由文本说明"}
        pm = PMDecision.from_dict("R-001", d)
        assert pm.reason_category == ""
        assert pm.reason_note == "自由文本说明"

    def test_accept_no_reason_fields(self):
        from models import PMDecision
        pm = PMDecision.from_dict("R-001", {"action": "accept"})
        assert pm.action == "accept"
        assert pm.reason_category == ""


# ============================================================
# _update_rule_perf_from_decisions 集成 — reject_by_reason 分桶 + 分档 delta
# ============================================================

class TestUpdateRulePerfFromDecisions:
    def test_reject_by_reason_bucket(self, tmp_path, monkeypatch):
        """两条不同 reason 的 reject → reject_by_reason 分桶各 +1."""
        # 准备 tmp workspace
        ws_name = "test-ws"
        ws_dir = tmp_path / ws_name
        ws_dir.mkdir()
        # mock get_project_root 让 rule_perf_store 写到 tmp
        monkeypatch.setattr("api.routes.review.get_project_root", lambda: tmp_path)

        from api.routes.review import _update_rule_perf_from_decisions

        items = [
            {"id": "R-001", "rule_id": "RC-001", "dimension": "quality"},
            {"id": "R-002", "rule_id": "RC-001", "dimension": "quality"},
        ]
        decisions = {
            "R-001": {"action": "reject", "reason_category": "false_positive"},
            "R-002": {"action": "reject", "reason_category": "wiki_missing"},
        }

        _update_rule_perf_from_decisions(items, decisions, ws_name)

        # 读回 rule_perf_history
        from rule_perf_store import RulePerformanceHistoryStore
        store = RulePerformanceHistoryStore(ws_dir)
        data = store.load()

        rc001 = data["RC-001"]
        assert rc001["stats"]["rejected"] == 2
        bucket = rc001["stats"]["reject_by_reason"]
        assert bucket == {"false_positive": 1, "wiki_missing": 1}

    def test_delta_differentiated_by_reason(self, tmp_path, monkeypatch):
        """同样是 reject, false_positive 把 impact_score 打得比 wiki_missing 更低."""
        ws_name = "test-ws"
        ws_dir = tmp_path / ws_name
        ws_dir.mkdir()
        monkeypatch.setattr("api.routes.review.get_project_root", lambda: tmp_path)

        from api.routes.review import _update_rule_perf_from_decisions

        # RC-A 被 false_positive (强惩罚), RC-B 被 wiki_missing (弱惩罚)
        items = [
            {"id": "R-001", "rule_id": "RC-A", "dimension": "quality"},
            {"id": "R-002", "rule_id": "RC-B", "dimension": "quality"},
        ]
        decisions = {
            "R-001": {"action": "reject", "reason_category": "false_positive"},
            "R-002": {"action": "reject", "reason_category": "wiki_missing"},
        }

        _update_rule_perf_from_decisions(items, decisions, ws_name)

        from rule_perf_store import RulePerformanceHistoryStore
        store = RulePerformanceHistoryStore(ws_dir)
        data = store.load()

        # RC-A (false_positive, -0.5) 应该比 RC-B (wiki_missing, -0.1) impact 更低
        assert data["RC-A"]["impact_score"] < data["RC-B"]["impact_score"], \
            "false_positive 的惩罚应强于 wiki_missing"

    def test_old_payload_without_reason_category_defaults_to_model_noise(self, tmp_path, monkeypatch):
        """没 reason_category 的老 payload 不阻塞, 桶进 model_noise."""
        ws_name = "test-ws"
        ws_dir = tmp_path / ws_name
        ws_dir.mkdir()
        monkeypatch.setattr("api.routes.review.get_project_root", lambda: tmp_path)

        from api.routes.review import _update_rule_perf_from_decisions

        items = [{"id": "R-001", "rule_id": "RC-LEG", "dimension": "quality"}]
        decisions = {
            "R-001": {"action": "reject", "reason": "老字段自由文本"},   # 没 reason_category
        }

        _update_rule_perf_from_decisions(items, decisions, ws_name)

        from rule_perf_store import RulePerformanceHistoryStore
        store = RulePerformanceHistoryStore(ws_dir)
        data = store.load()
        bucket = data["RC-LEG"]["stats"]["reject_by_reason"]
        assert bucket == {"model_noise": 1}

    def test_accept_does_not_touch_reject_bucket(self, tmp_path, monkeypatch):
        """accept 决策不碰 reject_by_reason 桶."""
        ws_name = "test-ws"
        ws_dir = tmp_path / ws_name
        ws_dir.mkdir()
        monkeypatch.setattr("api.routes.review.get_project_root", lambda: tmp_path)

        from api.routes.review import _update_rule_perf_from_decisions

        items = [{"id": "R-001", "rule_id": "RC-X", "dimension": "quality"}]
        decisions = {"R-001": {"action": "accept"}}

        _update_rule_perf_from_decisions(items, decisions, ws_name)

        from rule_perf_store import RulePerformanceHistoryStore
        store = RulePerformanceHistoryStore(ws_dir)
        data = store.load()
        # accept 不写 reject_by_reason
        assert "reject_by_reason" not in data["RC-X"]["stats"]
        assert data["RC-X"]["stats"]["confirmed"] == 1


# ============================================================
# ground truth 写入 reason_category + reason_note
# ============================================================

class TestGroundTruthReasonFields:
    def test_ground_truth_includes_reason_fields(self, tmp_path, monkeypatch):
        """_save_eval_ground_truth 每条 item 带 reason_category + reason_note (截 200 字)."""
        import json
        monkeypatch.setattr("api.routes.review.get_project_root", lambda: tmp_path)

        from api.routes.review import _save_eval_ground_truth

        items = [
            {"id": "R-001", "rule_id": "RC-A", "location": "第1节", "severity": "must"},
            {"id": "R-002", "rule_id": "RC-B", "location": "第2节", "severity": "should"},
        ]
        decisions = {
            "R-001": {"action": "reject", "reason_category": "false_positive", "reason_note": "PRD 第 3 节已说明"},
            "R-002": {"action": "accept"},
        }

        _save_eval_ground_truth(items, decisions, "test-ws", "albedolyu")

        # 读出 ground_truth 目录找到写出的文件
        gt_dir = tmp_path / "eval" / "ground_truth"
        assert gt_dir.exists()
        files = list(gt_dir.glob("test-ws_albedolyu_*.json"))
        assert len(files) == 1
        payload = json.loads(files[0].read_text(encoding="utf-8"))

        gt_items = {gi["id"]: gi for gi in payload["items"]}
        assert gt_items["R-001"]["reason_category"] == "false_positive"
        assert gt_items["R-001"]["reason_note"] == "PRD 第 3 节已说明"
        assert gt_items["R-002"]["reason_category"] == ""
        assert gt_items["R-002"]["reason_note"] == ""

    def test_reason_note_truncated_at_200_chars(self, tmp_path, monkeypatch):
        import json
        monkeypatch.setattr("api.routes.review.get_project_root", lambda: tmp_path)

        from api.routes.review import _save_eval_ground_truth

        long_note = "x" * 500
        items = [{"id": "R-001", "rule_id": "RC-A", "location": "", "severity": "must"}]
        decisions = {
            "R-001": {"action": "reject", "reason_category": "rule_too_strict", "reason_note": long_note},
        }

        _save_eval_ground_truth(items, decisions, "test-ws", "albedolyu")

        files = list((tmp_path / "eval" / "ground_truth").glob("test-ws_albedolyu_*.json"))
        payload = json.loads(files[0].read_text(encoding="utf-8"))
        assert len(payload["items"][0]["reason_note"]) == 200

    def test_old_reason_field_also_written(self, tmp_path, monkeypatch):
        """老 payload 只有 reason 字段 → 映射到 reason_note, reason_category 为空."""
        import json
        monkeypatch.setattr("api.routes.review.get_project_root", lambda: tmp_path)

        from api.routes.review import _save_eval_ground_truth

        items = [{"id": "R-001", "rule_id": "RC-A", "location": "", "severity": "must"}]
        decisions = {
            "R-001": {"action": "reject", "reason": "老字段自由文本"},
        }

        _save_eval_ground_truth(items, decisions, "test-ws", "albedolyu")

        files = list((tmp_path / "eval" / "ground_truth").glob("test-ws_albedolyu_*.json"))
        payload = json.loads(files[0].read_text(encoding="utf-8"))
        gt = payload["items"][0]
        assert gt["reason_category"] == ""
        assert gt["reason_note"] == "老字段自由文本"
