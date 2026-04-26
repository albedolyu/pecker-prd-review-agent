"""B: CaRR evidence chain 多跳拆解 (2026-04-26).

来源: GitHub 调研 #2 推荐 (sprint Day3 后追加), arXiv 2601.06021 THUDM/CaRR
    "Chaining the Evidence: Verifiable Multi-Hop Rubric Decomposition"

复杂 finding 加 evidence_chain 字段 (可选), 每跳 = {hop_idx, claim, citation}.
软强制: 部分跳 broken 不 retract, 写 v_details.chain_signal 让 PM 看 completeness.

测试矩阵:
1. _verify_evidence_chain: 空/全通过/部分 broken/全 broken/方法分类 (wiki/prd_section/mixed)
2. verify_evidence 集成: chain 缺失跳过 / chain 通过 / chain broken 不 retract
"""
from __future__ import annotations

import pytest


# ============================================================
# _verify_evidence_chain 单元测试
# ============================================================

class TestVerifyEvidenceChain:
    def test_empty_chain_returns_passed(self):
        from review.evidence_verify import _verify_evidence_chain
        passed, signal = _verify_evidence_chain([])
        assert passed is True
        assert signal["chain_length"] == 0
        assert signal["completeness"] == 1.0
        assert signal["method"] == "no_chain"

    def test_none_chain_returns_passed(self):
        from review.evidence_verify import _verify_evidence_chain
        passed, signal = _verify_evidence_chain(None)
        assert passed is True
        assert signal["method"] == "no_chain"

    def test_wiki_citation_all_found(self, tmp_path):
        from review.evidence_verify import _verify_evidence_chain
        wiki = tmp_path / "wiki"
        wiki.mkdir()
        (wiki / "约束-API契约.md").write_text("---\nsources: 2\n---\n", encoding="utf-8")
        index = {"约束-API契约.md": str(wiki / "约束-API契约.md")}

        chain = [
            {"hop_idx": 1, "claim": "PRD 引用 API 契约", "citation": "[[约束-API契约]]"},
        ]
        passed, signal = _verify_evidence_chain(chain, wiki_dir=str(wiki), wiki_index=index)
        assert passed is True
        assert signal["chain_length"] == 1
        assert signal["completeness"] == 1.0
        assert signal["broken_hops"] == []
        assert signal["method"] == "wiki"

    def test_wiki_citation_partial_broken(self, tmp_path):
        from review.evidence_verify import _verify_evidence_chain
        wiki = tmp_path / "wiki"
        wiki.mkdir()
        (wiki / "约束-X.md").write_text("---\n---\n", encoding="utf-8")
        index = {"约束-X.md": str(wiki / "约束-X.md")}

        chain = [
            {"hop_idx": 1, "claim": "X 存在", "citation": "[[约束-X]]"},     # 通过
            {"hop_idx": 2, "claim": "Y 存在", "citation": "[[约束-Y]]"},     # 失败
        ]
        passed, signal = _verify_evidence_chain(chain, wiki_dir=str(wiki), wiki_index=index)
        assert passed is True   # 软强制不 fail
        assert signal["chain_length"] == 2
        assert signal["completeness"] == 0.5
        assert 2 in signal["broken_hops"]
        assert 1 not in signal["broken_hops"]

    def test_prd_section_citation(self):
        """PRD 章节号 citation, 在 prd_content 找到 → pass."""
        from review.evidence_verify import _verify_evidence_chain
        prd = "第 1 章\n第 2 章\n第 3.2 节 详细描述..."

        chain = [
            {"hop_idx": 1, "claim": "PRD 第 3.2 节定义", "citation": "第 3.2 节"},
            {"hop_idx": 2, "claim": "PRD 第 5.1 节", "citation": "第 5.1 节"},   # 不在 prd
        ]
        passed, signal = _verify_evidence_chain(chain, prd_content=prd)
        assert passed is True
        assert signal["chain_length"] == 2
        # "3.2" 在 prd, "5.1" 不在 → 1/2 通过
        assert signal["completeness"] == 0.5
        assert 2 in signal["broken_hops"]

    def test_mixed_methods(self, tmp_path):
        from review.evidence_verify import _verify_evidence_chain
        wiki = tmp_path / "wiki"
        wiki.mkdir()
        (wiki / "X.md").write_text("---\n---\n", encoding="utf-8")
        index = {"X.md": str(wiki / "X.md")}
        prd = "第 1.1 节 ..."

        chain = [
            {"hop_idx": 1, "claim": "PRD 章节", "citation": "1.1"},
            {"hop_idx": 2, "claim": "wiki 引用", "citation": "[[X]]"},
        ]
        passed, signal = _verify_evidence_chain(chain, wiki_dir=str(wiki), wiki_index=index,
                                                 prd_content=prd)
        assert signal["method"] == "mixed"

    def test_missing_citation_or_claim_broken(self):
        """citation 或 claim 缺失 → 该 hop 标 broken."""
        from review.evidence_verify import _verify_evidence_chain
        chain = [
            {"hop_idx": 1, "claim": "x", "citation": ""},     # citation 空
            {"hop_idx": 2, "claim": "", "citation": "[[X]]"}, # claim 空
            {"hop_idx": 3, "claim": "y", "citation": "[[Y]]"}, # 完整 (但无 wiki, 视为软通过)
        ]
        passed, signal = _verify_evidence_chain(chain)
        assert 1 in signal["broken_hops"]
        assert 2 in signal["broken_hops"]
        assert signal["chain_length"] == 3
        # 第 3 跳 wiki 无 context 视为软通过
        assert signal["completeness"] == round(1/3, 3)

    def test_other_citation_format_skipped(self):
        """非 wiki / 非章节号 (如表名) → method='other', 不验证."""
        from review.evidence_verify import _verify_evidence_chain
        chain = [
            {"hop_idx": 1, "claim": "字段类型", "citation": "ds_xxx.field_y"},
        ]
        passed, signal = _verify_evidence_chain(chain)
        assert signal["method"] == "other"
        assert signal["completeness"] == 1.0  # 不强求验证


# ============================================================
# verify_evidence 主入口集成测试 — chain 字段透传
# ============================================================

class TestVerifyEvidenceWithChain:
    def test_no_chain_field_no_signal(self, tmp_path):
        """老 item 没 evidence_chain → v_details 不写 chain_signal."""
        from review.evidence_verify import verify_evidence
        wiki = tmp_path / "wiki"
        wiki.mkdir()
        for i in range(3):
            (wiki / f"page-{i}.md").write_text(
                "---\nsources: 1\nverified_by: PM\n---\n", encoding="utf-8",
            )
        items = [{"id": "R-1", "evidence_type": "B", "evidence_content": "RC-001",
                  "issue": "x", "confidence_score": 0.8}]
        out = verify_evidence(items, str(tmp_path))
        assert "chain_signal" not in out[0].get("verification_details", {})

    def test_chain_field_writes_signal(self, tmp_path):
        from review.evidence_verify import verify_evidence
        wiki = tmp_path / "wiki"
        wiki.mkdir()
        (wiki / "page-A.md").write_text(
            "---\nsources: 1\nverified_by: PM\n---\n", encoding="utf-8",
        )
        # 3 个业务 wiki 让 sparse=False
        for i in range(3):
            (wiki / f"page-{i}.md").write_text(
                "---\nsources: 1\nverified_by: PM\n---\n", encoding="utf-8",
            )
        items = [{
            "id": "R-1", "evidence_type": "B", "evidence_content": "RC-001",
            "issue": "x", "confidence_score": 0.8,
            "evidence_chain": [
                {"hop_idx": 1, "claim": "step 1", "citation": "[[page-A]]"},
                {"hop_idx": 2, "claim": "step 2", "citation": "[[不存在的页]]"},
            ],
        }]
        out = verify_evidence(items, str(tmp_path))
        cs = out[0]["verification_details"].get("chain_signal", {})
        assert cs.get("chain_length") == 2
        assert cs.get("completeness") == 0.5
        assert 2 in cs.get("broken_hops", [])

    def test_low_completeness_appends_reason_no_retract(self, tmp_path):
        """chain completeness < 0.5 时 v_reason 加注但不 retract."""
        from review.evidence_verify import verify_evidence
        wiki = tmp_path / "wiki"
        wiki.mkdir()
        for i in range(3):
            (wiki / f"page-{i}.md").write_text(
                "---\nsources: 1\nverified_by: PM\n---\n", encoding="utf-8",
            )
        items = [{
            "id": "R-1", "rule_id": "RC-001", "evidence_type": "B", "evidence_content": "RC-001",
            "issue": "x", "confidence_score": 0.8,
            "evidence_chain": [
                {"hop_idx": 1, "claim": "step 1", "citation": "[[不存在 1]]"},
                {"hop_idx": 2, "claim": "step 2", "citation": "[[不存在 2]]"},
                {"hop_idx": 3, "claim": "step 3", "citation": "[[不存在 3]]"},
            ],
        }]
        # 模拟 review-rules 不存在 → B 类会 retract, 但我们要测 chain 不影响
        # 改 evidence_type 为 C 类避开 B 类 retract 路径
        items[0]["evidence_type"] = "C"
        items[0]["evidence_content"] = "待确定⚠️ 这是 C 类自由文本"
        out = verify_evidence(items, str(tmp_path))
        # chain completeness=0 → reason 加注
        assert "CaRR chain completeness" in (out[0].get("verification_reason", "") or "")
        # 但 status 不是 RETRACTED (软强制)
        assert out[0]["status"] != "RETRACTED"

    def test_chain_check_failure_does_not_break(self, tmp_path, monkeypatch):
        """_verify_evidence_chain 抛异常 → log warning + skip, 主流程不崩."""
        from review.evidence_verify import verify_evidence
        # mock _verify_evidence_chain 让它抛
        import review.evidence_verify as ev_mod
        original = ev_mod._verify_evidence_chain
        def _raise(*args, **kwargs):
            raise RuntimeError("chain crash")
        monkeypatch.setattr(ev_mod, "_verify_evidence_chain", _raise)

        items = [{
            "id": "R-1", "evidence_type": "C", "evidence_content": "待确定⚠️ x",
            "issue": "x", "confidence_score": 0.8,
            "evidence_chain": [{"hop_idx": 1, "claim": "y", "citation": "[[X]]"}],
        }]
        out = verify_evidence(items, str(tmp_path))
        # 没崩 + chain_signal 没写
        assert out[0]["status"] in ("VERIFIED", "RETRACTED")  # 走完了, 没异常
        assert "chain_signal" not in out[0]["verification_details"]

        monkeypatch.setattr(ev_mod, "_verify_evidence_chain", original)


# ============================================================
# Tool schema 兼容性 — 确保 evidence_chain 字段已加到 SUBMIT_REVIEW_ITEMS_TOOL
# ============================================================

def test_worker_tool_schema_has_evidence_chain():
    """guardrail: SUBMIT_REVIEW_ITEMS_TOOL 应含 evidence_chain (CaRR 字段)."""
    from review.worker import SUBMIT_REVIEW_ITEMS_TOOL
    item_schema = SUBMIT_REVIEW_ITEMS_TOOL["input_schema"]["properties"]["items"]["items"]
    assert "evidence_chain" in item_schema["properties"]
    assert item_schema["properties"]["evidence_chain"]["type"] == "array"
    # evidence_chain 不是必填字段 (可选)
    assert "evidence_chain" not in item_schema["required"]
