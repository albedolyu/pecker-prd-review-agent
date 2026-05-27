"""POST /api/feedback/* — PM 对 finding 的接受/驳回/改写信号 → finding_outcomes_store.

CodeRabbit "online F1 acceptance" 实现:
  - report_builder 渲染时给每条 finding 加 [接受/误报/改写] 链接
  - PM 点击 → 后端写到 sqlite, 聚合算 rule-level accept_rate
  - high reject rule 自动加 learning record 反哺信鸽 v2

Endpoints:
  POST /api/feedback/accept       body={finding_id, rule_id, pm_name?, prd_name?, ...}
  POST /api/feedback/reject       body={finding_id, rule_id, pm_name?, reason?, ...}
  POST /api/feedback/edit         body={finding_id, rule_id, pm_name?, reason: 改写文本, ...}
  GET  /api/feedback/metrics      ?days=30 → all rules accept_rate 聚合
  GET  /api/feedback/rule/{rid}   ?days=30 → 单 rule 详细 metrics + trend
  GET  /api/feedback/recent       ?limit=50 → 最新反馈流
  GET  /api/feedback/low_accept   ?threshold=0.3&days=30 → 待优化规则
  GET  /api/feedback/high_accept  ?threshold=0.95 → 可固化规则

GET 不限权 (所有评审都能看), POST 必须登录但允许只读用户提反馈
(只读用户也是 PRD 审阅人, 反馈是他们核心动作).
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from api.deps import get_current_user, get_project_root
from review.finding_outcomes_store import (
    get_all_rules_metrics,
    get_high_accept_rules,
    get_low_accept_rules,
    get_pm_accept_history,
    get_pm_accept_summary,
    get_recent_outcomes,
    get_rule_accept_rate,
    record_outcome,
    trend_buckets,
)

# Metrics 埋点 — 失败 silent skip, 不阻 feedback 写库
try:
    from review.metrics_store import record_event as _record_event
except Exception:
    def _record_event(*args, **kwargs):  # noqa: ARG001
        return False

router = APIRouter(tags=["feedback"], prefix="/feedback")


class FeedbackBody(BaseModel):
    finding_id: str = Field(..., min_length=1, max_length=64)
    rule_id: Optional[str] = Field(None, max_length=64)
    pm_name: Optional[str] = Field(None, max_length=64)
    reason: Optional[str] = Field(None, max_length=2000)
    workspace: Optional[str] = Field(None, max_length=128)
    prd_name: Optional[str] = Field(None, max_length=128)
    severity: Optional[str] = Field(None, max_length=16)


class MissingFeedbackBody(BaseModel):
    problem: str = Field(..., min_length=1, max_length=2000)
    location: str = Field("", max_length=500)
    responsible_bird_id: Optional[int] = Field(None, ge=1, le=10)
    workspace: Optional[str] = Field(None, max_length=128)
    prd_name: Optional[str] = Field(None, max_length=128)
    pm_name: Optional[str] = Field(None, max_length=64)


class ReworkAvoidanceBody(BaseModel):
    categories: list[str] = Field(..., min_length=1, max_length=4)
    note: str = Field("", max_length=100)
    workspace: Optional[str] = Field(None, max_length=128)
    prd_name: Optional[str] = Field(None, max_length=128)
    pm_name: Optional[str] = Field(None, max_length=64)


def _record(outcome: str, body: FeedbackBody, user: dict) -> dict:
    """统一写库逻辑. pm_name 优先 body, 没传时用当前用户."""
    pm = body.pm_name or user.get("reviewer", "anonymous")
    new_id = record_outcome(
        finding_id=body.finding_id,
        outcome=outcome,
        rule_id=body.rule_id,
        pm_name=pm,
        reason=body.reason,
        workspace=body.workspace,
        prd_name=body.prd_name,
        severity=body.severity,
    )
    # Metrics 埋点: feedback.received (outcome=accept/reject/edit, rule_id, pm_name)
    try:
        _record_event(
            "feedback.received",
            workspace=body.workspace,
            reviewer=pm,
            status=outcome,
            details={
                "outcome": outcome,
                "rule_id": body.rule_id,
                "finding_id": body.finding_id,
                "severity": body.severity,
                "prd_name": body.prd_name,
            },
        )
    except Exception:
        pass
    # high-reject 阈值: 累计 reject >= 3 次 → 反哺信鸽 v2 加 learning
    # (只对 reject 触发, edit 不触发, accept 当然也不触发)
    if outcome == "reject" and body.rule_id:
        _maybe_emit_learning(body, pm)
    return {"status": "ok", "outcome_id": new_id, "outcome": outcome}


def _missing_feedback_path(project_root: Path) -> Path:
    return project_root / "logs" / "missing_feedback.jsonl"


def _short(value: Optional[str], limit: int) -> str:
    text = (value or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def record_missing_feedback(
    body: MissingFeedbackBody,
    *,
    user: dict,
    project_root: Path,
) -> dict:
    """Persist a PM-reported missed issue without storing PRD body."""
    reviewer = body.pm_name or user.get("reviewer") or "anonymous"
    ts = datetime.now().isoformat(timespec="seconds")
    fingerprint = hashlib.sha1(
        "|".join(
            [
                reviewer,
                body.workspace or "",
                body.prd_name or "",
                body.problem,
                body.location or "",
                ts,
            ]
        ).encode("utf-8"),
    ).hexdigest()[:16]
    feedback_id = f"missing_{fingerprint}"
    row = {
        "feedback_id": feedback_id,
        "timestamp": ts,
        "reviewer": reviewer,
        "workspace": body.workspace or "",
        "prd_name": body.prd_name or "",
        "problem": _short(body.problem, 500),
        "location": _short(body.location, 240),
        "responsible_bird_id": body.responsible_bird_id,
        "source": "missing_report",
    }
    path = _missing_feedback_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    try:
        _record_event(
            "feedback.missing_report",
            workspace=body.workspace,
            reviewer=reviewer,
            status="missing_report",
            details={
                "feedback_id": feedback_id,
                "prd_name": body.prd_name,
                "responsible_bird_id": body.responsible_bird_id,
            },
        )
    except Exception:
        pass
    return {"status": "ok", "feedback_id": feedback_id}


def record_rework_avoidance_feedback(
    body: ReworkAvoidanceBody,
    *,
    user: dict,
    project_root: Path,
) -> dict:
    """Persist optional PM rework-avoidance feedback from Phase 4."""
    from review.feedback_store import record_rework_avoidance

    reviewer = body.pm_name or user.get("reviewer") or "anonymous"
    db_path = project_root / "review" / "feedback.db"
    feedback_id = record_rework_avoidance(
        categories=body.categories,
        note=body.note,
        reviewer=reviewer,
        workspace=body.workspace or "",
        prd_name=body.prd_name or "",
        db_path=db_path,
    )
    try:
        _record_event(
            "feedback.rework_avoidance",
            workspace=body.workspace,
            reviewer=reviewer,
            status="ok",
            details={
                "feedback_id": feedback_id,
                "prd_name": body.prd_name,
                "categories": body.categories,
            },
        )
    except Exception:
        pass
    return {"status": "ok", "feedback_id": feedback_id}


def _maybe_emit_learning(body: FeedbackBody, pm: str) -> None:
    """累计 reject >= 3 自动生成 learning. 容错失败不影响主流程."""
    try:
        from review.finding_outcomes_store import get_rule_accept_rate
        m = get_rule_accept_rate(body.rule_id, days=30)
        if m["reject"] < 3 or m["accept_rate"] >= 0.5:
            return  # 还没到自动告警阈值
        # 已经到 high-reject, 写一条 learning record
        if not body.workspace:
            return  # 没 workspace 路径, 写不进 learnings_store
        from review.learnings_store import LearningsStore
        store = LearningsStore(body.workspace)
        existing = store.list_all(rule_id=body.rule_id, scope="team_local") or []
        # 同 rule 已经有 auto-learning 不重复加
        for ln in existing:
            if (ln.notes or "").startswith("[auto-from-feedback]"):
                return
        instruction = (
            f"该规则 30 天 accept_rate={m['accept_rate']:.0%}, reject={m['reject']} 次. "
            f"PM 最新理由: {(body.reason or '')[:200]}"
        )
        store.add(
            rule_id=body.rule_id,
            trigger_pattern=f"{body.rule_id} 类似场景",
            instruction=instruction,
            reviewer=pm,
            scope="team_local",
            notes=f"[auto-from-feedback] reject_count={m['reject']}",
        )
    except Exception:
        # 反哺失败不影响 outcome 写库
        pass


@router.post("/accept")
def feedback_accept(body: FeedbackBody, user: dict = Depends(get_current_user)):
    """PM 接受这条 finding."""
    return _record("accept", body, user)


@router.post("/reject")
def feedback_reject(body: FeedbackBody, user: dict = Depends(get_current_user)):
    """PM 标这条为误报."""
    return _record("reject", body, user)


@router.post("/edit")
def feedback_edit(body: FeedbackBody, user: dict = Depends(get_current_user)):
    """PM 改写这条 finding (reason 必填)."""
    if not body.reason:
        raise HTTPException(status_code=400, detail="edit 必须填 reason (PM 改写后的描述)")
    return _record("edit", body, user)


@router.post("/missing")
def feedback_missing(
    body: MissingFeedbackBody,
    user: dict = Depends(get_current_user),
    project_root: Path = Depends(get_project_root),
):
    """PM 补充模型漏掉的问题,供后台看板和规则优化使用。"""
    return record_missing_feedback(body, user=user, project_root=project_root)


@router.post("/rework-avoidance")
def feedback_rework_avoidance(
    body: ReworkAvoidanceBody,
    user: dict = Depends(get_current_user),
    project_root: Path = Depends(get_project_root),
):
    """PM feedback about what rework the review helped avoid."""
    return record_rework_avoidance_feedback(body, user=user, project_root=project_root)


# ============================================================
# GET endpoints (聚合 metrics)
# ============================================================


@router.get("/metrics")
def metrics_all(days: int = Query(30, ge=1, le=365)):
    """全部规则 accept_rate."""
    metrics = get_all_rules_metrics(days=days)
    pm_summary = get_pm_accept_summary(days=days)
    return {
        "window_days": days,
        "rules": metrics,
        "pms": pm_summary,
        "rule_count": len(metrics),
    }


@router.get("/rule/{rule_id}")
def metrics_rule(rule_id: str, days: int = Query(30, ge=1, le=365)):
    """单条规则的 metrics + trend buckets."""
    m = get_rule_accept_rate(rule_id, days=days)
    trend = trend_buckets(rule_id=rule_id, days=days, bucket_days=7)
    return {"rule_id": rule_id, "metrics": m, "trend": trend}


@router.get("/recent")
def recent_outcomes(limit: int = Query(50, ge=1, le=500)):
    """最近 N 条反馈."""
    return {"outcomes": get_recent_outcomes(limit=limit)}


@router.get("/low_accept")
def low_accept(
    threshold: float = Query(0.3, ge=0.0, le=1.0),
    min_count: int = Query(5, ge=1, le=100),
    days: int = Query(30, ge=1, le=365),
):
    """accept_rate < threshold 的规则 (待优化)."""
    return {
        "threshold": threshold,
        "min_count": min_count,
        "rules": get_low_accept_rules(threshold=threshold, min_count=min_count, days=days),
    }


@router.get("/high_accept")
def high_accept(
    threshold: float = Query(0.95, ge=0.0, le=1.0),
    min_count: int = Query(5, ge=1, le=100),
    days: int = Query(30, ge=1, le=365),
):
    """accept_rate > threshold 的规则 (可固化)."""
    return {
        "threshold": threshold,
        "min_count": min_count,
        "rules": get_high_accept_rules(threshold=threshold, min_count=min_count, days=days),
    }


@router.get("/pm/{pm_name}")
def pm_history(pm_name: str, days: int = Query(30, ge=1, le=365)):
    """单个 PM 的反馈历史."""
    return {
        "pm_name": pm_name,
        "history": get_pm_accept_history(pm_name, days=days),
    }
