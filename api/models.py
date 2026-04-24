"""Pydantic schemas 共享模块 + Opaque Handle Pattern (借鉴 chenglou/pretext)

核心思想: 后端返回的 `ReviewResult` 是不可变的、带 HMAC signature 的 opaque handle。
前端只能把整个 handle 原样回传给 `POST /api/review/confirm`,不能篡改 items 伪造状态。

防攻击场景:
- PM 前端拿到 20 条改进项,手工改成 2 条"must",18 条删除
- 前端回调 /api/review/confirm 时伪造 status=confirmed
- 后端 verify_signature 失败 → 403

不是终极安全机制(JWT cookie 和审计日志是更外层防线),但堵住"无脑篡改前端"的漏洞。
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field


def _signature_secret() -> bytes:
    """从 env var 读签名密钥,启动时 main.py 已经校验过存在性。"""
    secret = os.environ.get("PECKER_SIGNATURE_SECRET", "")
    if not secret:
        raise HTTPException(status_code=500, detail="PECKER_SIGNATURE_SECRET 未配置")
    return secret.encode("utf-8")


def _canonical_items_bytes(items: List[Dict[str, Any]]) -> bytes:
    """把 items 列表序列化为确定性 JSON 字符串(sorted keys),用于 HMAC。"""
    return json.dumps(items, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


# 签名格式版本。v1 只签 (review_id, items); v2 起把 workspace/reviewer 一起绑入,
# 防止前端把一份 review_result 搬到别人 workspace 或冒充他人 reviewer 去 confirm。
# 未来再扩字段时递增版本号,老 review_result 因版本 prefix 不同直接 verify 失败。
_SIGNATURE_VERSION = b"v2"


def compute_signature(
    review_id: str,
    workspace: str,
    reviewer: str,
    items: List[Dict[str, Any]],
) -> str:
    """对 (version | review_id | workspace | reviewer | items) 计算 HMAC-SHA256 hex digest。

    workspace / reviewer 绑入签名:挡住"同 review_id+items 改 workspace 提交"的伪造。
    """
    h = hmac.new(_signature_secret(), digestmod=hashlib.sha256)
    h.update(_SIGNATURE_VERSION)
    h.update(b"|")
    h.update(review_id.encode("utf-8"))
    h.update(b"|")
    h.update((workspace or "").encode("utf-8"))
    h.update(b"|")
    h.update((reviewer or "").encode("utf-8"))
    h.update(b"|")
    h.update(_canonical_items_bytes(items))
    return h.hexdigest()


def verify_signature(
    review_id: str,
    workspace: str,
    reviewer: str,
    items: List[Dict[str, Any]],
    signature: str,
) -> bool:
    """恒时比较,防定时攻击。"""
    expected = compute_signature(review_id, workspace, reviewer, items)
    return hmac.compare_digest(expected, signature)


# ============================================================
# ReviewResult opaque handle
# ============================================================

class ReviewWorkerInfo(BaseModel):
    """单个 worker 的执行结果摘要"""
    dimension: str
    dimension_name: str
    items_count: int
    error: Optional[str] = None


class ReviewResult(BaseModel):
    """评审结果 opaque handle。

    前端拿到后只读 — TypeScript 类型应声明为 Readonly<ReviewResult>。
    前端改 items 会导致 signature 失败,后端拒绝 /api/review/confirm。
    """
    model_config = ConfigDict(frozen=True)  # pydantic 级别的 immutability

    review_id: str = Field(..., description="review 唯一 ID,格式 rev_<timestamp>_<random>")
    created_at: float = Field(..., description="Unix timestamp")
    reviewer: str
    workspace: str
    prd_name: str
    mode: str
    items: List[Dict[str, Any]] = Field(..., description="合并去重后的改进项列表")
    workers: List[ReviewWorkerInfo] = Field(default_factory=list)
    usage: Dict[str, int] = Field(default_factory=dict)
    goshawk_summary: Optional[Dict[str, Any]] = None
    cost_breakdown: Optional[Dict[str, float]] = Field(default=None, description="各维度成本归因 USD")

    # Opaque handle signature — 前端任何改动都会让 verify 失败
    signature: str = Field(..., description="HMAC-SHA256(secret, review_id + canonical_items)")

    @classmethod
    def create(
        cls,
        reviewer: str,
        workspace: str,
        prd_name: str,
        mode: str,
        merged_items: List[Dict[str, Any]],
        workers: List[Dict[str, Any]],
        usage: Dict[str, int],
        goshawk_summary: Optional[Dict[str, Any]] = None,
        cost_breakdown: Optional[Dict[str, float]] = None,
    ) -> "ReviewResult":
        """后端评审完成后调用,自动生成 review_id + signature。"""
        import uuid
        review_id = f"rev_{int(time.time())}_{uuid.uuid4().hex[:8]}"
        sig = compute_signature(review_id, workspace, reviewer, merged_items)

        worker_infos = [
            ReviewWorkerInfo(
                dimension=w.get("dimension", ""),
                dimension_name=w.get("dimension_name", ""),
                items_count=len(w.get("items", [])),
                error=w.get("error"),
            )
            for w in workers
        ]

        return cls(
            review_id=review_id,
            created_at=time.time(),
            reviewer=reviewer,
            workspace=workspace,
            prd_name=prd_name,
            mode=mode,
            items=merged_items,
            workers=worker_infos,
            usage=usage,
            goshawk_summary=goshawk_summary,
            cost_breakdown=cost_breakdown,
            signature=sig,
        )


class ConfirmRequest(BaseModel):
    """Phase 3 用户确认后提交的 payload,用于生成最终报告。

    必须带原始 review_result(含 signature),后端先验证再处理 decisions。
    """
    review_result: Dict[str, Any]  # 原样回传,含 signature 字段
    decisions: Dict[str, Dict[str, Any]] = Field(
        ...,
        description="{item_id: {action: accept/reject/edit, reason: str}}",
    )


def verify_review_result(rr: Dict[str, Any]) -> None:
    """POST /api/review/confirm 入口调用,验证 signature 正确。

    失败抛 HTTPException 403。
    """
    signature = rr.get("signature", "")
    review_id = rr.get("review_id", "")
    workspace = rr.get("workspace", "")
    reviewer = rr.get("reviewer", "")
    items = rr.get("items", [])
    if not signature or not review_id:
        raise HTTPException(status_code=400, detail="review_result 缺少 signature 或 review_id")

    if not verify_signature(review_id, workspace, reviewer, items, signature):
        raise HTTPException(
            status_code=403,
            detail="review_result signature 验证失败 — items/workspace/reviewer 可能被前端篡改",
        )
