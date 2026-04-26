"""Sprint #6 EvidenceRL 第一步: _llm_nli_score + verify_evidence client 注入 (2026-04-26).

spec: docs/sprint-real-prd-calibration-evidence-governance.md (后续追加 Sprint 1 章节)
来源: 用户 GitHub 借鉴清单 #6 EvidenceRL + AI Engineer feasibility 报告

Anthropic API 不暴露 logprobs, 用 Monte Carlo N=4 重采样近似. 拒 hedging,
非 entail 必须给 ≥30 字理由. 失败采样静默 skip.

测试:
1. client=None 完全跳过 NLI 调用 (老 caller 行为 100% 等价)
2. mock LLM 返 4 次 entail → entail_score=1.0
3. mock LLM mixed (2 entail + 1 contradict + 1 neutral) → 比例正确
4. mock LLM 全部 hedging → succeeded=0, default 返回不影响主流程
5. _find_wiki_page_with_signal: ref_exact / ref_substring / keyword / no_match 4 method
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest


# ============================================================
# 1. _find_wiki_page_with_signal — 4 method 分支
# ============================================================

class TestFindWikiPageSignal:
    def test_ref_exact_match(self, tmp_path):
        from review.evidence_verify import _find_wiki_page_with_signal
        wiki = tmp_path / "wiki"
        wiki.mkdir()
        (wiki / "概念-API契约.md").write_text("---\nsources: 1\n---\n", encoding="utf-8")
        index = {"概念-API契约.md": str(wiki / "概念-API契约.md")}
        # ref 完全等于 basename (不含 .md) → ref_exact
        found, signal = _find_wiki_page_with_signal("[[概念-API契约]]", str(wiki), index)
        assert found is True
        assert signal["method"] == "ref_exact"
        assert signal["ref_count"] == 1

    def test_ref_substring_match(self, tmp_path):
        from review.evidence_verify import _find_wiki_page_with_signal
        wiki = tmp_path / "wiki"
        wiki.mkdir()
        (wiki / "约束-接口命名规范-v3.md").write_text("---\n---\n", encoding="utf-8")
        index = {"约束-接口命名规范-v3.md": str(wiki / "约束-接口命名规范-v3.md")}
        # ref="接口命名规范" 是 basename 的子串
        found, signal = _find_wiki_page_with_signal("[[接口命名规范]]", str(wiki), index)
        assert found is True
        assert signal["method"] == "ref_substring"

    def test_keyword_fallback(self, tmp_path):
        from review.evidence_verify import _find_wiki_page_with_signal
        wiki = tmp_path / "wiki"
        wiki.mkdir()
        (wiki / "概念-用户中心.md").write_text("---\n---\n", encoding="utf-8")
        index = {"概念-用户中心.md": str(wiki / "概念-用户中心.md")}
        # 无 [[ref]], 关键词 "用户中心" 命中 basename
        found, signal = _find_wiki_page_with_signal("用户中心的设计需要重新审视", str(wiki), index)
        assert found is True
        assert signal["method"] == "keyword"
        assert signal["keyword_count"] >= 1

    def test_no_match(self, tmp_path):
        from review.evidence_verify import _find_wiki_page_with_signal
        wiki = tmp_path / "wiki"
        wiki.mkdir()
        (wiki / "概念-X.md").write_text("---\n---\n", encoding="utf-8")
        index = {"概念-X.md": str(wiki / "概念-X.md")}
        found, signal = _find_wiki_page_with_signal("[[不存在的页面Y]]", str(wiki), index)
        assert found is False
        assert signal["method"] == "no_match"
        assert signal["ref_count"] == 1


# ============================================================
# 2. _llm_nli_score — N=4 重采样 + hedging 拒 + 失败兜底
# ============================================================

def _mock_response(text):
    """构造 client.create() 返回值, 单 text block."""
    block = MagicMock()
    block.type = "text"
    block.text = text
    resp = MagicMock()
    resp.content = [block]
    return resp


class TestLlmNliScore:
    def test_client_none_returns_default(self):
        from review.evidence_verify import _llm_nli_score
        out = _llm_nli_score(client=None, item={"issue": "x", "evidence_content": "[[页]]"},
                             wiki_pages={"页": "内容"})
        assert out["entail_score"] == 0.0
        assert out["n_samples_succeeded"] == 0
        assert out["neutral_score"] == 1.0   # default

    def test_empty_wiki_pages_returns_default(self):
        from review.evidence_verify import _llm_nli_score
        out = _llm_nli_score(client=MagicMock(), item={"issue": "x", "evidence_content": "[[页]]"},
                             wiki_pages={})
        assert out["n_samples_succeeded"] == 0

    def test_no_ref_in_evidence_returns_default(self):
        """evidence_content 没 [[ref]] → relevant_pages 空 → default."""
        from review.evidence_verify import _llm_nli_score
        client = MagicMock()
        out = _llm_nli_score(client, item={"issue": "x", "evidence_content": "无 ref 引用"},
                             wiki_pages={"页1": "内容"})
        assert out["n_samples_succeeded"] == 0
        client.create.assert_not_called()

    def test_all_entail_returns_full_score(self):
        from review.evidence_verify import _llm_nli_score
        client = MagicMock()
        # 4 次都返 entail
        client.create.return_value = _mock_response('{"verdict": "entail", "reason": "wiki 明确支持"}')
        out = _llm_nli_score(
            client,
            item={"issue": "API 契约缺失", "evidence_content": "[[页1]]"},
            wiki_pages={"页1": "API 契约定义在第 3 节"},
            n_samples=4,
        )
        assert out["entail_score"] == 1.0
        assert out["contradict_score"] == 0.0
        assert out["n_samples_succeeded"] == 4
        assert out["max_signal"] == 1.0

    def test_mixed_verdict_proportion_correct(self):
        from review.evidence_verify import _llm_nli_score
        client = MagicMock()
        # 2 entail + 1 contradict (含 35 字理由) + 1 neutral (含 35 字理由)
        client.create.side_effect = [
            _mock_response('{"verdict": "entail", "reason": "支持"}'),
            _mock_response('{"verdict": "entail", "reason": "支持2"}'),
            _mock_response('{"verdict": "contradict", "reason": "wiki 第 2 节明确说 X 字段不存在但改进项要求添加 X"}'),
            _mock_response('{"verdict": "neutral", "reason": "wiki 没涉及该字段, 无法判断改进项的对错请 PM 进一步确认"}'),
        ]
        out = _llm_nli_score(
            client,
            item={"issue": "X 字段缺失", "evidence_content": "[[页1]]"},
            wiki_pages={"页1": "wiki 内容"},
            n_samples=4,
        )
        assert out["n_samples_succeeded"] == 4
        assert out["entail_score"] == 0.5
        assert out["contradict_score"] == 0.25
        assert out["neutral_score"] == 0.25

    def test_hedging_rejected(self):
        """全部含 hedging 词 ('可能/也许/不确定') → succeeded=0, default 回."""
        from review.evidence_verify import _llm_nli_score
        client = MagicMock()
        client.create.return_value = _mock_response(
            '{"verdict": "contradict", "reason": "可能 wiki 不够全面也许有遗漏"}'
        )
        out = _llm_nli_score(
            client,
            item={"issue": "x", "evidence_content": "[[页1]]"},
            wiki_pages={"页1": "wiki"},
            n_samples=4,
        )
        assert out["n_samples_succeeded"] == 0   # 全 hedging 拒
        assert out["entail_score"] == 0.0

    def test_short_reason_for_non_entail_rejected(self):
        """非 entail 但 reason 不足 30 字 → 拒采样."""
        from review.evidence_verify import _llm_nli_score
        client = MagicMock()
        client.create.return_value = _mock_response(
            '{"verdict": "contradict", "reason": "短"}'
        )
        out = _llm_nli_score(
            client,
            item={"issue": "x", "evidence_content": "[[页1]]"},
            wiki_pages={"页1": "wiki"},
            n_samples=4,
        )
        assert out["n_samples_succeeded"] == 0

    def test_llm_call_raises_does_not_crash(self):
        """LLM client.create 抛异常 → 静默 skip, 默认回, 不破调用方."""
        from review.evidence_verify import _llm_nli_score
        client = MagicMock()
        client.create.side_effect = RuntimeError("network fail")
        out = _llm_nli_score(
            client,
            item={"issue": "x", "evidence_content": "[[页1]]"},
            wiki_pages={"页1": "wiki"},
            n_samples=4,
        )
        assert out["n_samples_succeeded"] == 0
        assert out["entail_score"] == 0.0


# ============================================================
# 3. verify_evidence client+wiki_pages 注入 — A 类成功分支调 NLI
# ============================================================

class TestVerifyEvidenceWithClient:
    def test_old_caller_no_client_skips_nli(self, tmp_path):
        """老 caller 不传 client → NLI 完全跳过, item 无 nli_score 字段."""
        from review.evidence_verify import verify_evidence
        wiki = tmp_path / "wiki"
        wiki.mkdir()
        # 3 个业务 wiki 让 sparse=False
        for i in range(3):
            (wiki / f"page-{i}.md").write_text(
                "---\nsources: 1\nverified_by: PM\n---\n内容", encoding="utf-8",
            )
        items = [{"id": "R-1", "evidence_type": "A", "evidence_content": "[[page-0]]",
                  "issue": "issue x", "confidence_score": 0.8}]
        out = verify_evidence(items, str(tmp_path))   # 不传 client
        assert "nli_score" not in out[0].get("verification_details", {})

    def test_with_client_wiki_pages_calls_nli(self, tmp_path):
        from review.evidence_verify import verify_evidence
        wiki = tmp_path / "wiki"
        wiki.mkdir()
        for i in range(3):
            (wiki / f"page-{i}.md").write_text(
                "---\nsources: 1\nverified_by: PM\n---\n", encoding="utf-8",
            )
        client = MagicMock()
        client.create.return_value = _mock_response('{"verdict": "entail", "reason": "支持"}')
        items = [{"id": "R-1", "evidence_type": "A", "evidence_content": "[[page-0]]",
                  "issue": "issue x", "confidence_score": 0.8}]
        out = verify_evidence(items, str(tmp_path), client=client,
                              wiki_pages={"page-0": "wiki content"})
        nli = out[0].get("verification_details", {}).get("nli_score")
        assert nli is not None
        assert nli["entail_score"] == 1.0

    def test_contradict_signal_downgrades_confidence(self, tmp_path):
        from review.evidence_verify import verify_evidence
        wiki = tmp_path / "wiki"
        wiki.mkdir()
        for i in range(3):
            (wiki / f"page-{i}.md").write_text(
                "---\nsources: 1\nverified_by: PM\n---\n", encoding="utf-8",
            )
        client = MagicMock()
        client.create.return_value = _mock_response(
            '{"verdict": "contradict", "reason": "wiki 第二节明确定义 X 字段为只读不可改, 改进项要求 X 字段允许编辑, 与 wiki 直接矛盾必须修正"}'
        )
        items = [{"id": "R-1", "evidence_type": "A", "evidence_content": "[[page-0]]",
                  "issue": "issue x", "confidence_score": 0.85}]
        out = verify_evidence(items, str(tmp_path), client=client,
                              wiki_pages={"page-0": "wiki content"})
        # contradict 占主 → confidence × 0.7
        assert out[0]["confidence_score"] == round(0.85 * 0.7, 2)
        assert out[0]["verification_details"]["reason_code"] == "A_nli_contradict_signal"

    def test_nli_failure_does_not_break_main_flow(self, tmp_path):
        """NLI 抛异常 / client 坏 → log warning 但 verify_evidence 主流程仍正常."""
        from review.evidence_verify import verify_evidence
        wiki = tmp_path / "wiki"
        wiki.mkdir()
        for i in range(3):
            (wiki / f"page-{i}.md").write_text(
                "---\nsources: 1\nverified_by: PM\n---\n", encoding="utf-8",
            )
        client = MagicMock()
        client.create.side_effect = RuntimeError("LLM down")
        items = [{"id": "R-1", "evidence_type": "A", "evidence_content": "[[page-0]]",
                  "issue": "issue x", "confidence_score": 0.85}]
        out = verify_evidence(items, str(tmp_path), client=client,
                              wiki_pages={"page-0": "wiki content"})
        # _llm_nli_score 内部 try/except 已 catch, 返默认 → 走 nli_score=default 路径
        # 默认 entail=0 contradict=0 neutral=1, 不触发 contradict 降权
        assert out[0]["confidence_score"] == 0.85   # 不变
        # nli_score 是 default
        nli = out[0]["verification_details"].get("nli_score", {})
        assert nli.get("n_samples_succeeded", -1) == 0
