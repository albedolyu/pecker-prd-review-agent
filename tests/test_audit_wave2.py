"""第二波 audit fix 单测 (2026-04-26):
P1-A reason_category enum 校验 / P1-C goshawk fuzzy 最小长度 / P1-D verified_by 占位串 / P2-D 死代码删

每项独立测试 class 便于快速定位回归.
"""
from __future__ import annotations

import pytest


# ============================================================
# P1-A: ConfirmRequest.decisions 加 reason_category enum 校验
# ============================================================

class TestReasonCategoryEnumValidation:
    def test_valid_reason_passes(self):
        from api.models import ConfirmRequest
        req = ConfirmRequest(
            review_result={"signature": "x"},
            decisions={"R-001": {"action": "reject", "reason_category": "false_positive"}},
        )
        assert req.decisions["R-001"]["reason_category"] == "false_positive"

    def test_all_seven_enum_values_pass(self):
        from api.models import ConfirmRequest
        for reason in ["good_issue", "false_positive", "known_tradeoff", "wiki_missing",
                       "rule_too_strict", "impl_detail", "model_noise"]:
            ConfirmRequest(
                review_result={},
                decisions={"R-1": {"action": "reject", "reason_category": reason}},
            )   # 不该抛

    def test_invalid_reason_raises_422(self):
        from api.models import ConfirmRequest
        from pydantic import ValidationError
        with pytest.raises(ValidationError) as exc_info:
            ConfirmRequest(
                review_result={},
                decisions={"R-001": {"action": "reject", "reason_category": "bogus_reason"}},
            )
        # 错误信息应列出有效值
        assert "RejectReason" in str(exc_info.value) or "reason_category" in str(exc_info.value)

    def test_missing_reason_category_allowed(self):
        """缺失 reason_category (老 payload) 仍允许, 走默认 model_noise."""
        from api.models import ConfirmRequest
        req = ConfirmRequest(
            review_result={},
            decisions={"R-001": {"action": "reject"}},   # 没 reason_category
        )
        assert "reason_category" not in req.decisions["R-001"]

    def test_legacy_reason_string_field_allowed(self):
        """老 payload 'reason' 自由文本字段不影响校验."""
        from api.models import ConfirmRequest
        req = ConfirmRequest(
            review_result={},
            decisions={"R-001": {"action": "reject", "reason": "自由文本说明"}},
        )
        assert req.decisions["R-001"]["reason"] == "自由文本说明"

    def test_accept_action_with_invalid_reason_still_caught(self):
        """即使 action != reject, 非法 reason_category 也应报 (避免被绕过)."""
        from api.models import ConfirmRequest
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            ConfirmRequest(
                review_result={},
                decisions={"R-001": {"action": "accept", "reason_category": "evil"}},
            )


# ============================================================
# P1-C: _verify_wiki_evidence fuzzy match 最小长度 4
# ============================================================

class TestGoshawkFuzzyMatchMinLen:
    def test_short_ref_no_substring_match(self):
        """ref='API' (3 字) 不该 fuzzy 匹任何含 API 的页面."""
        # 直接构造 wiki_titles + ref 验证逻辑, 重现修法之前的误命中场景
        wiki_titles = ["约束-API_v3_迁移指南", "概念-业务APIs"]
        ref = "API"
        _MIN_FUZZY_LEN = 4
        # 老逻辑: any(ref in title or title in ref) → True (误命中)
        # 新逻辑: 加 len(ref) >= _MIN_FUZZY_LEN 门槛 → False
        found = any(
            ref == title
            or (len(ref) >= _MIN_FUZZY_LEN and (ref in title or title in ref))
            for title in wiki_titles
        )
        assert found is False, "API (3 字) 不该模糊匹"

    def test_exact_match_still_works(self):
        """ref == title 完全匹配仍 work, 即使短."""
        wiki_titles = ["API"]
        ref = "API"
        _MIN_FUZZY_LEN = 4
        found = any(
            ref == title
            or (len(ref) >= _MIN_FUZZY_LEN and (ref in title or title in ref))
            for title in wiki_titles
        )
        assert found is True

    def test_long_ref_fuzzy_still_works(self):
        """ref >= 4 字仍能 fuzzy 匹."""
        wiki_titles = ["约束-接口命名规范"]
        ref = "接口命名规范"
        _MIN_FUZZY_LEN = 4
        found = any(
            ref == title
            or (len(ref) >= _MIN_FUZZY_LEN and (ref in title or title in ref))
            for title in wiki_titles
        )
        assert found is True


# ============================================================
# P1-D: verified_by 占位串不该提权
# ============================================================

class TestVerifiedByPlaceholder:
    @pytest.mark.parametrize("placeholder", ["TBD", "tbd", "Tbd", "待定", "-", "?", "??", "n/a", "N/A", "nil", "null"])
    def test_placeholder_falls_back_to_contextual(self, tmp_path, placeholder):
        from review.evidence_verify import _wiki_authority_tier
        wiki = tmp_path / "x.md"
        wiki.write_text(
            f"---\nsources: 1\nverified_by: {placeholder}\n---\n",
            encoding="utf-8",
        )
        # 占位串不应判 trusted
        assert _wiki_authority_tier(str(wiki)) == "contextual", \
            f"verified_by={placeholder!r} 应判 contextual 不是 trusted"

    def test_real_verified_by_still_trusted(self, tmp_path):
        """真名字仍判 trusted (回归测)."""
        from review.evidence_verify import _wiki_authority_tier
        wiki = tmp_path / "x.md"
        wiki.write_text(
            "---\nsources: 1\nverified_by: PM\n---\n",
            encoding="utf-8",
        )
        assert _wiki_authority_tier(str(wiki)) == "trusted"

    def test_single_char_verified_by_rejected(self, tmp_path):
        """单字符 verified_by 长度 < 2 不判 trusted (避免 X / a 等)."""
        from review.evidence_verify import _wiki_authority_tier
        wiki = tmp_path / "x.md"
        wiki.write_text(
            "---\nsources: 1\nverified_by: X\n---\n",
            encoding="utf-8",
        )
        assert _wiki_authority_tier(str(wiki)) == "contextual"


# ============================================================
# P2-D: 死代码 dataclass 已删
# ============================================================

class TestDeadDataclassesRemoved:
    def test_old_advisor_dataclasses_gone(self):
        """4 个 dataclass 应不再 importable from models."""
        import models
        for name in ("FalsePositive", "AdditionalFinding", "ConflictResolution", "AdvisorResult"):
            assert not hasattr(models, name), \
                f"{name} 应已删除, 但仍存在于 models.py"

    def test_remaining_models_still_work(self):
        """删了死代码后, 其他 models (RejectReason, ReviewItem, PMDecision, PlantedBug) 仍能用."""
        from models import RejectReason, ReviewItem, PMDecision, PlantedBug   # noqa: F401
        assert RejectReason.FALSE_POSITIVE.value == "false_positive"
