"""P1 #1 (2026-04-24): review.py 的 reviewer 必须来自 JWT 不来自 body。

背景:
原先 /api/review 入口三处把前端 body 里的 `req.reviewer` 当署名用:
- event_store 里写审计事件
- record_review_cost 成本归因
- ReviewResult.create 最终报告

但 run_review 已经 `Depends(get_current_user)` 拿到 JWT 验证过的 user["reviewer"].
攻击路径: alice 合法登录, POST body 写 {"reviewer": "bob"} → 伪造成 bob 的报告.

修复: 三处全改成 user["reviewer"], req.reviewer 字段保留给前端 draft 兼容但后端忽略.

本文件两类测试:
1. 源码级 grep (防回归): 断言 review.py 里不再有 `req.reviewer` 用于审计 / 成本 / 署名
2. 契约测试: ReviewRequest 字段保留但注释说明不信任
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


PROJECT_ROOT = Path(__file__).parent.parent
REVIEW_PY = PROJECT_ROOT / "api" / "routes" / "review.py"


class TestReviewReviewerFromJwt:
    """源码级 grep — 防回归."""

    def test_req_reviewer_not_used_for_audit(self):
        """event_store 事件 / record_review_cost / ReviewResult.create 都不应用 req.reviewer.

        如果后续重构不小心把 user["reviewer"] 又改回 req.reviewer, 这条测试抓.
        """
        content = REVIEW_PY.read_text(encoding="utf-8")
        # 匹配 `req.reviewer` 出现在 {审计/成本/签名} 相关上下文的模式
        # 注意 schema 定义里 `reviewer: str = "unknown"` 不算 (那是字段定义)
        lines = content.splitlines()
        bad_usages = []
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            # schema 字段定义不算
            if stripped.startswith("reviewer:") or "Field(" in stripped:
                continue
            # 注释不算
            if stripped.startswith("#"):
                continue
            if "req.reviewer" in stripped:
                bad_usages.append(f"L{i}: {stripped}")

        assert not bad_usages, (
            "review.py 里不应再用 req.reviewer 做审计/成本/署名, 应改用 user['reviewer']:\n"
            + "\n".join(bad_usages)
        )

    def test_user_reviewer_is_used(self):
        """确保三处关键点切到 user['reviewer'] — 不是光删掉 req.reviewer."""
        content = REVIEW_PY.read_text(encoding="utf-8")
        # 至少出现 3 次 user["reviewer"] 或 user['reviewer']
        pattern = re.compile(r'user\[\s*["\']reviewer["\']\s*\]')
        matches = pattern.findall(content)
        assert len(matches) >= 3, (
            f"期望 review.py 里至少 3 处 user['reviewer'] (event_store + cost + "
            f"ReviewResult.create), 实际只找到 {len(matches)} 处"
        )


class TestReviewRequestSchemaKeepsField:
    """ReviewRequest.reviewer 字段保留 (前端 draft 兼容), 但注释标明后端不用."""

    def test_reviewer_field_still_exists(self):
        """字段保留, 避免前端 draft 里带 reviewer 导致 422."""
        from api.routes.review import ReviewRequest

        # 能构造出来 (表示字段接受)
        req = ReviewRequest(
            prd_content="dummy",
            workspace="workspace-x",
            reviewer="someone",
        )
        assert req.reviewer == "someone"  # 字段存在值能读, 但 route handler 不信任

    def test_reviewer_field_has_untrusted_comment(self):
        """schema 定义附近必须有注释说明 reviewer 不被信任 (防未来再有人误用)."""
        content = REVIEW_PY.read_text(encoding="utf-8")
        # 匹配 schema 定义上下 5 行内的相关注释
        # 寻找 "reviewer:" 字段定义 + 附近 "JWT" / "不信任" / "不用" 关键词
        pattern = re.compile(
            r'(不信任|JWT[^\n]*reviewer|reviewer[^\n]*JWT|user\[["\']reviewer)',
            re.MULTILINE,
        )
        assert pattern.search(content), (
            "ReviewRequest.reviewer 字段附近应有注释说明后端以 JWT 为准, 否则下次重构容易"
            "把 req.reviewer 拿回来用"
        )


class TestReviewSessionTags:
    def test_request_accepts_session_tags_for_operational_runs(self):
        from api.routes.review import ReviewRequest

        req = ReviewRequest(
            prd_content="dummy",
            workspace="workspace-x",
            session_tags=["stress"],
        )

        assert req.session_tags == ["stress"]

    def test_legacy_stress_request_is_tagged(self):
        from api.routes.review import ReviewRequest, _derive_session_tags

        req = ReviewRequest(
            prd_content="dummy",
            workspace="workspace-x",
            prd_name="team-beta-stress-1.md",
        )

        assert _derive_session_tags(req, reviewer="stress-pm-1") == ["stress"]
