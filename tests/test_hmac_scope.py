"""P1 #2 (2026-04-24): ReviewResult HMAC signature 覆盖面扩到 workspace + reviewer。

背景:
api/models.py 原先 compute_signature(review_id, items) 只签这俩,workspace/reviewer
不在签名里。攻击路径: 前端拿到 review_result A(workspace=对外投资/reviewer=alice),
原样搬 items+signature,把 review_result 里的 workspace 改成别的,POST /api/review/confirm
仍然 verify 通过。第二道 ACL 能挡跨 workspace 写,但第一道本来就该绑死上下文。

修复: 新增签名版本 v2,把 workspace/reviewer 也绑入 HMAC input。
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# HMAC 需要 secret
os.environ["PECKER_SIGNATURE_SECRET"] = "unit-test-signature-secret-32-chars"

from api.models import (
    ReviewResult,
    compute_signature,
    verify_review_result,
    verify_signature,
)
from fastapi import HTTPException


_ITEMS = [
    {"id": "R-001", "rule_id": "V-05", "severity": "must"},
    {"id": "R-002", "rule_id": "V-07", "severity": "should"},
]


class TestSignatureBindsWorkspaceAndReviewer:
    def test_same_input_same_signature(self):
        """同输入 → 同 signature (deterministic)。"""
        s1 = compute_signature("rev_1", "workspace-a", "alice", _ITEMS)
        s2 = compute_signature("rev_1", "workspace-a", "alice", _ITEMS)
        assert s1 == s2

    def test_different_workspace_different_signature(self):
        """换 workspace → signature 必须变 (核心修复)。"""
        s_a = compute_signature("rev_1", "workspace-a", "alice", _ITEMS)
        s_b = compute_signature("rev_1", "workspace-b", "alice", _ITEMS)
        assert s_a != s_b

    def test_different_reviewer_different_signature(self):
        """换 reviewer → signature 必须变 (核心修复)。"""
        s_alice = compute_signature("rev_1", "workspace-a", "alice", _ITEMS)
        s_bob = compute_signature("rev_1", "workspace-a", "bob", _ITEMS)
        assert s_alice != s_bob

    def test_verify_rejects_workspace_tampering(self):
        """伪造 workspace 后 verify_signature → False。"""
        sig = compute_signature("rev_1", "workspace-a", "alice", _ITEMS)
        # 前端把 workspace 改成 b, items+signature 原样提交
        assert verify_signature("rev_1", "workspace-b", "alice", _ITEMS, sig) is False

    def test_verify_rejects_reviewer_tampering(self):
        """伪造 reviewer 后 verify_signature → False。"""
        sig = compute_signature("rev_1", "workspace-a", "alice", _ITEMS)
        assert verify_signature("rev_1", "workspace-a", "bob", _ITEMS, sig) is False

    def test_verify_accepts_intact(self):
        """原样输入 → verify 通过。"""
        sig = compute_signature("rev_1", "workspace-a", "alice", _ITEMS)
        assert verify_signature("rev_1", "workspace-a", "alice", _ITEMS, sig) is True


class TestReviewResultCreateBindsContext:
    def test_create_normalizes_items_before_signing(self):
        """ReviewResult.create 返回给 Web 的 items 同时带 issue/problem 等别名。"""
        rr = ReviewResult.create(
            reviewer="alice",
            workspace="workspace-a",
            prd_name="test.md",
            mode="standard",
            merged_items=[{
                "id": "R-001",
                "issue": "字段口径不清",
                "evidence_content": "PRD 第 2 节",
                "confidence_score": 0.9,
            }],
            workers=[],
            usage={},
        )

        item = rr.items[0]
        assert item["issue"] == "字段口径不清"
        assert item["problem"] == "字段口径不清"
        assert item["evidence"] == "PRD 第 2 节"
        assert item["confidence"] == 0.9
        verify_review_result(rr.model_dump())  # 签名覆盖归一化后的 items

    def test_create_signature_covers_workspace_reviewer(self):
        """ReviewResult.create 生成的 signature 同时覆盖 workspace + reviewer。"""
        rr = ReviewResult.create(
            reviewer="alice",
            workspace="workspace-a",
            prd_name="test.md",
            mode="standard",
            merged_items=_ITEMS,
            workers=[],
            usage={},
        )

        rr_dict = rr.model_dump()
        # 原样 verify → ok
        verify_review_result(rr_dict)  # 不抛

        # 篡改 workspace 后 verify → 403
        tampered = dict(rr_dict)
        tampered["workspace"] = "workspace-evil"
        with pytest.raises(HTTPException) as ei:
            verify_review_result(tampered)
        assert ei.value.status_code == 403

        # 篡改 reviewer 后 verify → 403
        tampered2 = dict(rr_dict)
        tampered2["reviewer"] = "mallory"
        with pytest.raises(HTTPException) as ei:
            verify_review_result(tampered2)
        assert ei.value.status_code == 403

    def test_create_preserves_telemetry_without_weakening_signature(self):
        """Telemetry is operator-facing context; preserving it must not affect item verification."""
        rr = ReviewResult.create(
            reviewer="alice",
            workspace="workspace-a",
            prd_name="test.md",
            mode="standard",
            merged_items=_ITEMS,
            workers=[],
            usage={},
            telemetry={
                "total_duration_ms": 1234,
                "workers": {"structure": {"duration_ms": 700}},
                "resilience": {"failed_workers": 0},
            },
        )

        rr_dict = rr.model_dump()
        assert rr_dict["telemetry"]["total_duration_ms"] == 1234
        assert rr_dict["telemetry"]["workers"]["structure"]["duration_ms"] == 700
        verify_review_result(rr_dict)

        tampered = dict(rr_dict)
        tampered["telemetry"] = {"total_duration_ms": 9999}
        verify_review_result(tampered)


class TestBackwardIncompatIsIntentional:
    """v2 prefix 确保旧 v1 签名(如果有任何遗留)直接 verify 失败,
    不会被当成有效签名混过去。没有老数据需要迁移,硬切即可。"""

    def test_empty_strings_do_not_collapse(self):
        """空 workspace/reviewer 不应被和别的空 input 匹配成同一 signature。

        具体: (ws=\"\", rev=\"\") 和 (ws=\"a\", rev=\"\") 必须不同。
        """
        s_empty = compute_signature("rev_1", "", "", _ITEMS)
        s_a_empty = compute_signature("rev_1", "a", "", _ITEMS)
        s_empty_a = compute_signature("rev_1", "", "a", _ITEMS)
        assert len({s_empty, s_a_empty, s_empty_a}) == 3
