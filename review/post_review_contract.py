"""共享后处理契约。

Web / CLI / 飞书入口都应复用这里的 item 归一化、决策统计和报告片段,
避免各入口各自解释字段。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Iterable, List, Mapping

from api.sanitize import redact_text
from review.implement_convention import annotate_review_items, build_report_notice


REJECT_REASON_LABELS = {
    "good_issue": "实际是好问题(手滑点错)",
    "false_positive": "误报",
    "known_tradeoff": "已知取舍, 不改",
    "wiki_missing": "知识库缺失",
    "rule_too_strict": "规则太严",
    "impl_detail": "实现细节, 不该 PRD 管",
    "model_noise": "模型噪音",
}

CORRECTNESS_REASON_LABELS = {
    "false_positive": "误报",
    "unsupported_evidence": "依据不足",
    "rule_too_strict": "规则过严",
}

BUSINESS_DECISION_LABELS = {
    "not_this_iteration": "本期不修",
    "risk_accepted": "风险接受",
    "handled_elsewhere": "已有安排",
}


def _build_proposed_patch(item: Mapping[str, Any]) -> str:
    """Build paste-ready PRD patch text from an item without reading PRD body."""
    existing = item.get("proposed_patch") or item.get("patch_text")
    if isinstance(existing, str) and existing.strip():
        return existing.strip()

    suggestion = str(item.get("suggestion") or "").strip()
    if not suggestion:
        return ""

    location = str(item.get("location") or "").strip()
    if location:
        return f"在「{location}」补充：{suggestion}"
    return f"补充：{suggestion}"


def normalize_review_items(items: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """保留 Python 原字段,补齐 Web/报告消费的 canonical aliases。"""
    normalized: List[Dict[str, Any]] = []
    for item in annotate_review_items(items):
        out = dict(item)
        issue = out.get("issue") or out.get("problem")
        if issue and not out.get("problem"):
            out["problem"] = issue
        elif out.get("problem") and not out.get("issue"):
            out["issue"] = out["problem"]

        evidence = out.get("evidence") or out.get("evidence_content")
        if evidence and not out.get("evidence"):
            out["evidence"] = evidence
        elif out.get("evidence") and not out.get("evidence_content"):
            out["evidence_content"] = out["evidence"]

        if "confidence" not in out and "confidence_score" in out:
            out["confidence"] = out["confidence_score"]
        elif "confidence_score" not in out and "confidence" in out:
            out["confidence_score"] = out["confidence"]

        proposed_patch = _build_proposed_patch(out)
        if proposed_patch:
            out["proposed_patch"] = proposed_patch

        normalized.append(out)
    return normalized


def summarize_decisions(
    items: Iterable[Mapping[str, Any]],
    decisions: Mapping[str, Mapping[str, Any]],
) -> Dict[str, int]:
    """统计 Phase 3 决策。"""
    item_ids = [str(item.get("id", "")) for item in items if item.get("id")]
    counts = {"accepted": 0, "rejected": 0, "edited": 0}
    for item_id in item_ids:
        action = str((decisions.get(item_id) or {}).get("action") or "").strip().lower()
        if action == "accept":
            counts["accepted"] += 1
        elif action == "reject":
            counts["rejected"] += 1
        elif action == "edit":
            counts["edited"] += 1
    total = len(item_ids)
    return {
        "total": total,
        **counts,
        "pending": max(0, total - counts["accepted"] - counts["rejected"] - counts["edited"]),
    }


def build_confirm_report_markdown(
    review_result: Mapping[str, Any],
    decisions: Mapping[str, Mapping[str, Any]],
) -> str:
    """从 signed ReviewResult + decisions 生成后端同源 Markdown 报告。"""
    items = normalize_review_items(review_result.get("items", []))
    stats = summarize_decisions(items, decisions)
    created_at = review_result.get("created_at")
    if isinstance(created_at, (int, float)):
        generated_at = datetime.fromtimestamp(created_at).strftime("%Y-%m-%d %H:%M:%S")
    else:
        generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    prd_name = redact_text(str(review_result.get("prd_name", "unknown")))
    reviewer = redact_text(str(review_result.get("reviewer", "")))
    workspace = redact_text(str(review_result.get("workspace", "")))
    mode = redact_text(str(review_result.get("mode", "")))
    review_id = redact_text(str(review_result.get("review_id", "")))

    lines = [
        f"# PRD 评审报告 - {prd_name}",
        "",
        f"> **评审人**: {reviewer}",
        f"> **Workspace**: {workspace}",
        f"> **模式**: {mode}",
        f"> **生成时间**: {generated_at}",
        f"> **Review ID**: `{review_id}`",
        "",
        "## 评审概要",
        "",
        f"- **改进项**: {stats['total']} 条",
        f"- **决策**: 接受 {stats['accepted']} · 改写 {stats['edited']} · "
        f"拒绝 {stats['rejected']} · 待决 {stats['pending']}",
        "",
    ]
    lines.extend(build_report_notice().splitlines())
    lines.extend(["", "---", ""])

    if not items:
        lines.extend(["## 改进项", "", "> 本次评审没有发现问题。", ""])
        return "\n".join(lines)

    lines.extend(["## 改进项", ""])
    for idx, item in enumerate(items, 1):
        item_id = item.get("id", f"R-{idx:03d}")
        decision = decisions.get(item_id) or {}
        action = str(decision.get("action", "pending") or "pending").strip().lower()
        action_label = {
            "accept": "已接受",
            "reject": "已拒绝",
            "edit": "已改写",
            "pending": "待决",
        }.get(action, action)
        severity = item.get("severity", "")

        lines.extend([
            f"### {idx}. {redact_text(str(item_id))} [{redact_text(str(severity))}] {action_label}".strip(),
            "",
        ])
        if item.get("location"):
            lines.append(f"- **位置**: {redact_text(str(item['location']))}")

        problem = item.get("problem") or ""
        if action == "edit" and decision.get("edited_problem"):
            lines.append(f"- **问题(改写后)**: {redact_text(str(decision['edited_problem']))}")
            if problem:
                lines.append(f"  - 原始: {redact_text(str(problem))}")
        elif problem:
            lines.append(f"- **问题**: {redact_text(str(problem))}")

        if item.get("evidence"):
            lines.append(f"- **依据**: {redact_text(str(item['evidence']))}")
        if item.get("suggestion"):
            lines.append(f"- **建议**: {redact_text(str(item['suggestion']))}")

        if action == "reject":
            correctness_reason = decision.get("correctness_reason") or ""
            business_decision = decision.get("business_decision") or ""
            if correctness_reason:
                reason_label = CORRECTNESS_REASON_LABELS.get(correctness_reason, correctness_reason)
                lines.append(f"- **判断问题**: {redact_text(str(reason_label))}")
            if business_decision:
                decision_label = BUSINESS_DECISION_LABELS.get(business_decision, business_decision)
                lines.append(f"- **业务处理**: {redact_text(str(decision_label))}")
            if not correctness_reason and not business_decision:
                category = decision.get("reason_category") or "model_noise"
                reason_label = REJECT_REASON_LABELS.get(category, category)
                lines.append(f"- **拒绝原因**: {redact_text(str(reason_label))}")
            note = decision.get("reason_note") or decision.get("reason")
            if note:
                lines.append(f"- **驳回备注**: {redact_text(str(note))}")

        if item.get("implement_convention_version"):
            lines.append(f"- **实现约定**: {redact_text(str(item['implement_convention_version']))}")
        lines.append("")

    return "\n".join(lines)
