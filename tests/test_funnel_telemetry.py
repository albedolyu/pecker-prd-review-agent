"""T3: funnel telemetry 纯函数单测 (2026-04-24).

spec: docs/review-funnel-schema.md

覆盖 5 层漏斗的 stage compute + funnel_summary + wiki telemetry 助手.
Emit 失败不阻塞的 resilience 放 e2e / API 调用测试 (T0 的 test_review_api_evidence_verify
已有 pattern, 本文件不重复).
"""
from __future__ import annotations

import pytest

from review.funnel_telemetry import (
    compute_dedup_stage,
    compute_evidence_verify_stage,
    compute_funnel_summary,
    compute_goshawk_stage,
    compute_pm_decision_stage,
    compute_worker_raw_stage,
    get_wiki_telemetry,
)


# ============================================================
# N0: compute_worker_raw_stage
# ============================================================

class TestWorkerRawStage:
    def test_sum_across_dimensions(self):
        workers = [
            {"dimension": "structure", "items": [{"id": "R-001"}, {"id": "R-002"}]},
            {"dimension": "quality", "items": [{"id": "R-003"}]},
            {"dimension": "ai_coding", "items": [{"id": "R-004"}, {"id": "R-005"}, {"id": "R-006"}]},
        ]
        out = compute_worker_raw_stage(workers)
        assert out["count"] == 6
        assert out["by_dimension"] == {"structure": 2, "quality": 1, "ai_coding": 3}
        assert out["empty_retry_dimensions"] == []

    def test_empty_retry_detection(self):
        workers = [
            {"dimension": "a", "items": [], "telemetry": {"empty_retry_used": True}},
            {"dimension": "b", "items": [{"id": "X"}], "telemetry": {"empty_retry_used": False}},
            {"dimension": "c", "items": [], "telemetry": {}},   # 无 empty_retry_used
        ]
        out = compute_worker_raw_stage(workers)
        assert out["empty_retry_dimensions"] == ["a"]

    def test_missing_dimension_fallback(self):
        """Worker 结果缺 dimension → 归到 'unknown'."""
        workers = [{"items": [{"id": "R-1"}]}]
        out = compute_worker_raw_stage(workers)
        assert out["by_dimension"] == {"unknown": 1}

    def test_empty_workers_list(self):
        out = compute_worker_raw_stage([])
        assert out["count"] == 0
        assert out["by_dimension"] == {}


# ============================================================
# N1: compute_dedup_stage
# ============================================================

class TestDedupStage:
    def test_dropped_calc(self):
        out = compute_dedup_stage(worker_raw_count=28, merged_items=[{"id": f"R-{i}"} for i in range(15)])
        assert out["count"] == 15
        assert out["dropped_count"] == 13

    def test_no_dropped(self):
        out = compute_dedup_stage(worker_raw_count=5, merged_items=[{"id": f"R-{i}"} for i in range(5)])
        assert out["dropped_count"] == 0

    def test_negative_safe(self):
        """若 merged 比 raw 还多 (理论上不该) → dropped=0 而非负数."""
        out = compute_dedup_stage(worker_raw_count=3, merged_items=[{"id": "R-1"}, {"id": "R-2"}, {"id": "R-3"}, {"id": "R-4"}])
        assert out["dropped_count"] == 0


# ============================================================
# N2: compute_evidence_verify_stage
# ============================================================

class TestEvidenceVerifyStage:
    def test_extracts_from_summarize_verification(self):
        v_sum = {
            "total": 15,
            "verified": 11,
            "retracted": 2,
            "caveat": 3,
            "downgraded": 3,
            "retracted_by_reason_code": {"B_missing_rule": 1, "A_missing_wiki": 1},
            "downgraded_by_reason_code": {"A_wiki_page_not_found_weak": 3},
            "reliability": 0.73,
        }
        wiki_tele = {"mode": "rich", "authority_distribution": {"canonical": 2, "trusted": 5, "contextual": 3}}
        out = compute_evidence_verify_stage(v_sum, wiki_tele)
        assert out["count"] == 11
        assert out["retracted_count"] == 2
        assert out["downgraded_count"] == 3
        assert out["retracted_by_reason"] == {"B_missing_rule": 1, "A_missing_wiki": 1}
        assert out["downgraded_by_reason"] == {"A_wiki_page_not_found_weak": 3}
        assert out["wiki_mode"] == "rich"
        assert out["authority_distribution"] == {"canonical": 2, "trusted": 5, "contextual": 3}

    def test_empty_verification_defaults(self):
        v_sum = {"total": 0, "verified": 0, "retracted": 0, "caveat": 0}
        wiki_tele = {}
        out = compute_evidence_verify_stage(v_sum, wiki_tele)
        assert out["count"] == 0
        assert out["wiki_mode"] == "unknown"
        assert out["authority_distribution"] == {}


# ============================================================
# N3: compute_goshawk_stage (P0-1 facet 场景)
# ============================================================

class TestGoshawkStage:
    def test_facet_preservation_breakdown(self):
        """P0-1 场景: 3 条 facet 被保留, 2 条 meta 补充, 0 条 removed."""
        post_items = [
            {"id": "R-001", "status": "", "severity": "must"},
            {"id": "R-002", "status": "", "severity": "must"},
            {"id": "R-003", "status": "MERGED_BY_ADVISOR", "facet_of": "R-001", "severity": "could"},
            {"id": "R-004", "status": "MERGED_BY_ADVISOR", "facet_of": "R-001", "severity": "could"},
            {"id": "R-005", "status": "", "severity": "should"},
            {"id": "R-006", "status": "MERGED_BY_ADVISOR", "facet_of": "R-005", "severity": "could"},
            {"id": "R-007", "provenance": "meta_added", "source": "苍鹰补充", "severity": "should"},
            {"id": "R-008", "source": "苍鹰补充", "severity": "should"},
        ]
        goshawk_result = {
            "flagged_as_false_positive": [],
            "additional_findings": [{}, {}],
        }
        out = compute_goshawk_stage(post_items, goshawk_result)
        assert out["count"] == 8
        dr = out["delta_breakdown"]
        assert dr["merged_to_facet"] == 3   # R-003/R-004/R-006
        assert dr["added"] == 2             # R-007 + R-008
        assert dr["removed"] == 0
        assert dr["false_positive_restored"] == 0
        assert dr["kept_intact"] == 3       # R-001 R-002 R-005
        # facet_links
        links = {(f["facet"], f["primary"]) for f in out["facet_links"]}
        assert links == {("R-003", "R-001"), ("R-004", "R-001"), ("R-006", "R-005")}

    def test_removed_counted_from_fp_recommendation(self):
        """REMOVED_BY_ADVISOR 已被 apply_advisor_result 过滤, 从 fp 建议里反查."""
        post_items = [{"id": "R-001", "severity": "must"}]
        goshawk_result = {
            "flagged_as_false_positive": [
                {"item_id": "R-002", "reason": "...", "recommendation": "移除"},
                {"item_id": "R-003", "reason": "...", "recommendation": "降级为 should"},
                {"item_id": "R-004", "reason": "...", "recommendation": "移除"},
            ],
            "additional_findings": [],
        }
        out = compute_goshawk_stage(post_items, goshawk_result)
        assert out["delta_breakdown"]["removed"] == 2
        assert out["delta_breakdown"]["kept_intact"] == 1

    def test_sanity_check_restored(self):
        post_items = [
            {"id": "R-001", "status": "RESTORED_BY_SANITY_CHECK", "severity": "must"},
            {"id": "R-002", "severity": "should"},
        ]
        out = compute_goshawk_stage(post_items, {"flagged_as_false_positive": [], "additional_findings": []})
        assert out["delta_breakdown"]["false_positive_restored"] == 1
        assert out["delta_breakdown"]["kept_intact"] == 1


# ============================================================
# N4: compute_pm_decision_stage
# ============================================================

class TestPmDecisionStage:
    def test_split_by_action_and_reason(self):
        decisions = {
            "R-001": {"action": "accept"},
            "R-002": {"action": "edit"},
            "R-003": {"action": "reject", "reason_category": "false_positive"},
            "R-004": {"action": "reject", "reason_category": "wiki_missing"},
            "R-005": {"action": "reject", "reason_category": "false_positive"},
        }
        out = compute_pm_decision_stage(decisions)
        assert out["total_items"] == 5
        assert out["accepted"] == 1
        assert out["edited"] == 1
        assert out["rejected"] == 3
        assert out["pending"] == 0
        assert out["rejected_by_reason"] == {"false_positive": 2, "wiki_missing": 1}

    def test_missing_reason_defaults_to_model_noise(self):
        """reject 但没 reason_category → 兜底进 model_noise 桶."""
        decisions = {
            "R-001": {"action": "reject"},   # 老 payload, 无 reason_category
        }
        out = compute_pm_decision_stage(decisions)
        assert out["rejected_by_reason"] == {"model_noise": 1}

    def test_pending_items(self):
        decisions = {
            "R-001": {"action": "accept"},
            "R-002": {"action": ""},   # pending
            "R-003": {},               # pending (action 缺失)
        }
        out = compute_pm_decision_stage(decisions)
        assert out["pending"] == 2


# ============================================================
# funnel_summary — retention + suspicious_flags
# ============================================================

class TestFunnelSummary:
    def test_healthy_pipeline_no_flags(self):
        """P0-1 实测数据: 28 → 15 → 11 → 10 → 6, retention 健康 (dedup 低但好在 PM 没低).

        dedup_retention = 15/28 = 0.536 < 0.6 → 会触发 flag (吞 facet 嫌疑)
        evidence_verify_retention = 11/15 = 0.733 ≥ 0.6 OK
        goshawk_retention = 10/11 = 0.909 ≥ 0.7 OK
        pm_retention = 6/10 = 0.6 ≥ 0.3 OK
        → 只有 dedup flag
        """
        stages = {
            "N0_worker_raw": 28, "N1_after_dedup": 15, "N2_after_evidence_verify": 11,
            "N3_after_goshawk": 10, "N4_after_pm_decision": 6,
        }
        out = compute_funnel_summary(stages)
        assert out["stages"] == stages
        assert out["stage_retention"]["dedup_retention"] == 0.536
        assert out["stage_retention"]["pm_retention"] == 0.6
        # 只有 dedup 一项低
        assert len(out["suspicious_flags"]) == 1
        assert out["suspicious_flags"][0].startswith("dedup_retention_low_")

    def test_multiple_flags(self):
        """多层都低: 全部被抓."""
        stages = {
            "N0_worker_raw": 30, "N1_after_dedup": 10,   # 0.33, low
            "N2_after_evidence_verify": 5,                 # 0.5, low
            "N3_after_goshawk": 3,                         # 0.6, low (<0.7 goshawk)
            "N4_after_pm_decision": 0,                     # 0.0, low
        }
        out = compute_funnel_summary(stages)
        assert len(out["suspicious_flags"]) == 4

    def test_cli_path_no_pm_stage(self):
        """CLI flow: N4 为 None, funnel_summary 不应含 pm_retention key, 也不该触发 pm flag."""
        stages = {
            "N0_worker_raw": 28, "N1_after_dedup": 20, "N2_after_evidence_verify": 15,
            "N3_after_goshawk": 12, "N4_after_pm_decision": None,
        }
        out = compute_funnel_summary(stages)
        assert "pm_retention" not in out["stage_retention"]
        # suspicious flags 只可能来自 dedup/ev/goshawk, 不会来自 pm
        for f in out["suspicious_flags"]:
            assert "pm" not in f

    def test_zero_division_safe(self):
        """各 stage 都 0 → 不崩, retention 默认 1.0."""
        stages = {
            "N0_worker_raw": 0, "N1_after_dedup": 0, "N2_after_evidence_verify": 0,
            "N3_after_goshawk": 0, "N4_after_pm_decision": 0,
        }
        out = compute_funnel_summary(stages)
        # 零样本不应判可疑
        assert out["suspicious_flags"] == []


# ============================================================
# get_wiki_telemetry — workspace I/O
# ============================================================

class TestGetWikiTelemetry:
    def test_missing_workspace(self, tmp_path):
        """wiki 目录不存在 → mode=sparse, distribution={}."""
        out = get_wiki_telemetry(str(tmp_path))
        assert out["mode"] == "sparse"
        assert out["authority_distribution"] == {}

    def test_sparse_all_generated(self, tmp_path):
        """5 个 wiki 全 sources:0 → 全 generated → sparse 模式."""
        wiki = tmp_path / "wiki"
        wiki.mkdir()
        for i in range(5):
            (wiki / f"page-{i}.md").write_text(
                "---\nsources: 0\n---\n\n# P\n", encoding="utf-8",
            )
        out = get_wiki_telemetry(str(tmp_path))
        assert out["mode"] == "sparse"
        assert out["authority_distribution"] == {"generated": 5}

    def test_rich_mixed_tiers(self, tmp_path):
        """混合 tier → rich 模式 (有 3+ 业务 md)."""
        wiki = tmp_path / "wiki"
        wiki.mkdir()
        # 1 canonical
        (wiki / "canonical.md").write_text(
            "---\nsources: 2\nauthority: canonical\nverified_by: 数据\n---\n",
            encoding="utf-8",
        )
        # 2 trusted (sources>=1 + verified_by)
        for i in range(2):
            (wiki / f"trusted-{i}.md").write_text(
                f"---\nsources: 1\nverified_by: PM\n---\n", encoding="utf-8",
            )
        # 1 contextual (sources>=1 无 verified_by)
        (wiki / "ctx.md").write_text("---\nsources: 1\n---\n", encoding="utf-8")
        # 1 generated (sources:0)
        (wiki / "gen.md").write_text("---\nsources: 0\n---\n", encoding="utf-8")

        out = get_wiki_telemetry(str(tmp_path))
        assert out["mode"] == "rich"
        dist = out["authority_distribution"]
        assert dist["canonical"] == 1
        assert dist["trusted"] == 2
        assert dist["contextual"] == 1
        assert dist["generated"] == 1

    def test_meta_files_skipped(self, tmp_path):
        """log.md / index.md / README.md / TOC.md 不计入 distribution."""
        wiki = tmp_path / "wiki"
        wiki.mkdir()
        for meta in ("log.md", "index.md", "README.md", "TOC.md"):
            (wiki / meta).write_text("---\nsources: 0\n---\n", encoding="utf-8")
        out = get_wiki_telemetry(str(tmp_path))
        assert out["authority_distribution"] == {}
