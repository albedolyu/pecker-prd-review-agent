from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import sys
import time
import traceback
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent_config import MODEL_TIERS
from content_loader import load_prd_content, load_wiki_pages
from parallel_review import parallel_review, summarize_verification, verify_evidence


def safe_file_label(label: str | None) -> str:
    raw = (label or "case").strip()
    had_non_ascii = any(ord(ch) > 127 for ch in raw)
    text = raw.lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    if had_non_ascii and text:
        return f"case_{text}"
    return text or "case"


def worker_event(dim: str, result: Dict[str, Any]) -> Dict[str, Any]:
    telemetry = result.get("telemetry", {}) if isinstance(result, dict) else {}
    error = result.get("error") if isinstance(result, dict) else str(result)
    status = result.get("status") if isinstance(result, dict) else "failed"
    if not status:
        status = "failed" if error else "success"
    return {
        "dim": dim,
        "items": len(result.get("items", [])) if isinstance(result, dict) else 0,
        "error": error,
        "status": status,
        "model": telemetry.get("model") or (result.get("model") if isinstance(result, dict) else None),
        "duration_ms": telemetry.get("duration_ms"),
        "wiki_selection": telemetry.get("wiki_selection"),
        "recovery": result.get("recovery") if isinstance(result, dict) else None,
    }


def completion_summary(worker_events: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    events = list(worker_events)
    failed = [e["dim"] for e in events if e.get("error") and e.get("status") != "recovered"]
    recovered = [e["dim"] for e in events if e.get("status") == "recovered" or e.get("recovery")]
    return {
        "status": "partial" if failed else "complete",
        "failed_workers": failed,
        "recovered_workers": recovered,
    }


def summarize_item(item: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": item.get("id"),
        "dimension": item.get("dimension"),
        "rule_id": item.get("rule_id"),
        "severity": item.get("severity"),
        "title": item.get("title") or item.get("issue") or item.get("summary"),
        "location": item.get("location"),
        "issue": item.get("issue"),
        "suggestion": item.get("suggestion"),
        "confidence": item.get("confidence") or item.get("confidence_score"),
        "verification_status": item.get("verification_status"),
        "reason_code": (item.get("verification_details") or {}).get("reason_code"),
    }


def find_previous_report(output_dir: Path, file_label: str, current_json: Path | None = None) -> Path | None:
    safe = safe_file_label(file_label)
    candidates = sorted(output_dir.glob(f"gpt_route_{safe}_*.json"))
    if current_json is not None:
        candidates = [p for p in candidates if p.resolve() != current_json.resolve()]
    return candidates[-1] if candidates else None


def performance_delta(current: Dict[str, Any], previous: Dict[str, Any] | None) -> Dict[str, Any] | None:
    if not previous:
        return None
    prev_elapsed = float(previous.get("elapsed_s") or 0)
    cur_elapsed = float(current.get("elapsed_s") or 0)
    if prev_elapsed <= 0:
        return None
    return {
        "previous_elapsed_s": prev_elapsed,
        "current_elapsed_s": cur_elapsed,
        "delta_s": round(cur_elapsed - prev_elapsed, 3),
        "speedup_ratio": round(prev_elapsed / cur_elapsed, 3) if cur_elapsed > 0 else None,
    }


SEVERITY_RANK = {"must": 0, "should": 1, "could": 2}
ENGINEERING_DIMENSIONS = {"AI Coding 友好度"}
FEEDBACK_OPTIONS = ["有用", "误报", "已在别处说明", "表达不清", "优先级过高"]
DIMENSION_IMPACT = {
    "结构层": "会影响研发、测试对范围、流程和边界的共同理解。",
    "质量层": "会影响验收口径，容易在评审后继续返工。",
    "数据质量": "会影响字段口径、数据来源和后续核对成本。",
    "AI Coding 友好度": "会影响研发拆接口、建模型和生成代码时的确定性。",
}
TESTABILITY_BLOCKING_TERMS = (
    "验收",
    "状态",
    "异常",
    "字段",
    "口径",
    "权限",
    "前置",
    "预期",
    "成功",
    "失败",
    "无权限",
    "边界",
    "规则",
    "流程",
    "DDL",
)
CASE_TYPE_TERMS = {
    "验收": "acceptance",
    "成功": "positive",
    "失败": "negative",
    "异常": "exception",
    "权限": "permission",
    "无权限": "permission",
    "字段": "data",
    "口径": "data",
    "边界": "boundary",
    "状态": "state_transition",
    "流程": "workflow",
}


def _source_items(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    items = payload.get("verified_items") or payload.get("items") or []
    return [item for item in items if isinstance(item, dict)]


def _item_title(item: Dict[str, Any]) -> str:
    return str(item.get("title") or item.get("issue") or item.get("summary") or "")


def _item_text(item: Dict[str, Any]) -> str:
    parts = [
        item.get("title"),
        item.get("issue"),
        item.get("suggestion"),
        item.get("location"),
        item.get("rule_id"),
        item.get("dimension"),
    ]
    return " ".join(str(part) for part in parts if part)


def _item_confidence(item: Dict[str, Any]) -> float:
    try:
        return float(item.get("confidence") or item.get("confidence_score") or 0)
    except (TypeError, ValueError):
        return 0.0


def _priority_sort_key(item: Dict[str, Any]) -> tuple:
    return (
        SEVERITY_RANK.get(str(item.get("severity") or "").lower(), 9),
        -_item_confidence(item),
        str(item.get("id") or ""),
    )


def _pm_action_item(item: Dict[str, Any]) -> Dict[str, Any]:
    dimension = str(item.get("dimension") or "未分组")
    location = str(item.get("location") or "未标注位置")
    suggestion = str(item.get("suggestion") or "补充该处缺失的信息，并写清判断口径。")
    return {
        "id": item.get("id"),
        "severity": item.get("severity"),
        "dimension": dimension,
        "rule_id": item.get("rule_id"),
        "location": location,
        "issue": _item_title(item),
        "why_it_matters": DIMENSION_IMPACT.get(dimension, "会影响后续评审、研发或测试对需求的共同理解。"),
        "suggested_change": suggestion,
        "prd_patch_label": "可直接粘贴到 PRD",
        "prd_patch": f"在「{location}」补充：{suggestion}",
        "feedback_options": FEEDBACK_OPTIONS,
    }


def _test_handoff_type(item: Dict[str, Any]) -> str:
    severity = str(item.get("severity") or "").lower()
    dimension = str(item.get("dimension") or "")
    text = _item_text(item)
    if severity == "must" and dimension != "AI Coding 友好度" and any(term in text for term in TESTABILITY_BLOCKING_TERMS):
        return "blocking_test_generation"
    if dimension == "AI Coding 友好度":
        return "engineering_context"
    return "case_quality_risk"


def _case_types_for_item(item: Dict[str, Any]) -> List[str]:
    text = _item_text(item)
    case_types = [case_type for term, case_type in CASE_TYPE_TERMS.items() if term in text]
    if not case_types:
        case_types = ["functional"]
    seen = set()
    ordered = []
    for case_type in case_types:
        if case_type not in seen:
            seen.add(case_type)
            ordered.append(case_type)
    return ordered


def _trace_item(item: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "review_item_id": item.get("id"),
        "rule_id": item.get("rule_id"),
        "dimension": item.get("dimension"),
        "location": item.get("location"),
        "severity": item.get("severity"),
    }


def _testability_gap(item: Dict[str, Any]) -> Dict[str, Any]:
    action = _pm_action_item(item)
    return {
        **action,
        "handoff_type": _test_handoff_type(item),
        "case_types_affected": _case_types_for_item(item),
        "needs_pm_confirmation": str(item.get("severity") or "").lower() == "must",
    }


def build_testability_summary(payload: Dict[str, Any]) -> Dict[str, Any]:
    items = sorted(_source_items(payload), key=_priority_sort_key)
    gaps = [_testability_gap(item) for item in items]
    blocking_gaps = [gap for gap in gaps if gap["handoff_type"] == "blocking_test_generation"]
    quality_risks = [gap for gap in gaps if gap["handoff_type"] == "case_quality_risk"]
    engineering_context = [gap for gap in gaps if gap["handoff_type"] == "engineering_context"]

    if blocking_gaps:
        verdict = "blocked"
        coverage = "低"
    elif quality_risks:
        verdict = "partial"
        coverage = "中"
    else:
        verdict = "ready"
        coverage = "高"

    testable_modules = []
    for item in items:
        location = str(item.get("location") or "未标注位置")
        testable_modules.append({
            "module": location,
            "dimension": item.get("dimension"),
            "source_item_id": item.get("id"),
            "recommended_case_types": _case_types_for_item(item),
        })

    acceptance_criteria = [
        {
            "source_item_id": item.get("id"),
            "location": item.get("location"),
            "criterion": item.get("suggestion") or _item_title(item),
            "status": "missing_or_needs_clarification" if _test_handoff_type(item) == "blocking_test_generation" else "candidate",
        }
        for item in items
        if "验收" in _item_text(item) or str(item.get("severity") or "").lower() == "must"
    ]

    return {
        "testability_verdict": verdict,
        "estimated_case_coverage": coverage,
        "blocking_gap_count": len(blocking_gaps),
        "quality_risk_count": len(quality_risks),
        "engineering_context_count": len(engineering_context),
        "testable_modules": testable_modules,
        "untestable_gaps": blocking_gaps,
        "case_quality_risks": quality_risks,
        "engineering_context": engineering_context,
        "acceptance_criteria": acceptance_criteria,
    }


def _scenario_from_item(item: Dict[str, Any]) -> Dict[str, Any]:
    action = _pm_action_item(item)
    return {
        "source_item_id": item.get("id"),
        "module": action.get("location"),
        "scenario": action.get("issue"),
        "case_types": _case_types_for_item(item),
        "preconditions_needed": "补齐前置条件" if "前置" in _item_text(item) else "",
        "expected_result_needed": "补齐预期结果/验收标准" if any(term in _item_text(item) for term in ("验收", "预期", "成功", "失败")) else "",
        "blocked": _test_handoff_type(item) == "blocking_test_generation",
        "suggested_pm_input": action.get("suggested_change"),
    }


def build_zhiqu_handoff(payload: Dict[str, Any]) -> Dict[str, Any]:
    testability = build_testability_summary(payload)
    items = sorted(_source_items(payload), key=_priority_sort_key)
    scenario_matrix = [_scenario_from_item(item) for item in items]
    edge_cases = [row for row in scenario_matrix if "boundary" in row["case_types"]]
    negative_cases = [
        row for row in scenario_matrix
        if any(case_type in row["case_types"] for case_type in ("negative", "exception", "permission"))
    ]
    data_requirements = [
        row for row in scenario_matrix
        if any(case_type in row["case_types"] for case_type in ("data", "state_transition"))
    ]

    return {
        "schema_version": "pecker_to_zhiqu.v1",
        "source_system": "pecker",
        "target_agent": "zhiqu_test_case_agent",
        "requirement_id": payload.get("requirement_id") or payload.get("case_label"),
        "prd_id": payload.get("prd_id") or payload.get("case_label"),
        "prd_version": payload.get("prd_version") or payload.get("prd_files") or [],
        "review_id": payload.get("review_id") or payload.get("case_label"),
        "review_mode": payload.get("review_mode") or "deep",
        "pm_verdict": (payload.get("pm_summary") or build_pm_summary(payload)).get("verdict"),
        "testability_verdict": testability["testability_verdict"],
        "estimated_case_coverage": testability["estimated_case_coverage"],
        "testable_modules": testability["testable_modules"],
        "untestable_gaps": testability["untestable_gaps"],
        "acceptance_criteria": testability["acceptance_criteria"],
        "scenario_matrix": scenario_matrix,
        "edge_cases": edge_cases,
        "negative_cases": negative_cases,
        "data_requirements": data_requirements,
        "traceability": [_trace_item(item) for item in items],
        "source_trace": {
            "workspace": payload.get("workspace"),
            "prd_files": payload.get("prd_files") or [],
            "prd_hash": payload.get("prd_hash"),
            "previous_report": payload.get("previous_report"),
            "report_paths": payload.get("report_paths") or {},
        },
        "pm_controls": {
            "do_not_invent_missing_requirements": True,
            "blocked_items_require_pm_input": [gap.get("id") for gap in testability["untestable_gaps"]],
            "feedback_options": FEEDBACK_OPTIONS,
        },
    }


def build_pm_summary(payload: Dict[str, Any]) -> Dict[str, Any]:
    items = _source_items(payload)
    completion = payload.get("completion") or {}
    failed_workers = completion.get("failed_workers") or []
    blocking_items = [item for item in items if str(item.get("severity") or "").lower() == "must"]
    priority_items = [_pm_action_item(item) for item in sorted(items, key=_priority_sort_key)[:5]]
    dimension_counts = Counter(str(item.get("dimension") or "未分组") for item in items)

    if completion.get("status") == "partial" or failed_workers or len(blocking_items) >= 6:
        verdict = "暂不建议进入开发"
        rework_risk = "高"
    elif blocking_items or len(items) >= 10:
        verdict = "建议补充后再评审"
        rework_risk = "中"
    else:
        verdict = "可进入评审"
        rework_risk = "低"

    return {
        "verdict": verdict,
        "rework_risk": rework_risk,
        "blocking_count": len(blocking_items),
        "total_items": len(items),
        "top_risk_dimensions": [
            {"dimension": dim, "count": count}
            for dim, count in dimension_counts.most_common(3)
        ],
        "priority_items": priority_items,
        "feedback_options": FEEDBACK_OPTIONS,
        "review_mode": payload.get("review_mode") or "deep",
    }


def build_pm_view(payload: Dict[str, Any]) -> Dict[str, Any]:
    items = sorted(_source_items(payload), key=_priority_sort_key)
    pm_items = [_pm_action_item(item) for item in items if item.get("dimension") not in ENGINEERING_DIMENSIONS]
    engineering_items = [_pm_action_item(item) for item in items if item.get("dimension") in ENGINEERING_DIMENSIONS]
    return {
        "pm_count": len(pm_items),
        "engineering_count": len(engineering_items),
        "pm_items": pm_items,
        "engineering_items": engineering_items,
        "default_view": "pm",
    }


def _rule_ids(payload: Dict[str, Any]) -> set[str]:
    return {str(item.get("rule_id")) for item in _source_items(payload) if item.get("rule_id")}


def output_change_summary(current: Dict[str, Any], previous: Dict[str, Any] | None) -> Dict[str, Any] | None:
    if not previous:
        return None
    current_count = int(current.get("merged_count") or len(_source_items(current)))
    previous_count = int(previous.get("merged_count") or len(_source_items(previous)))
    item_delta = current_count - previous_count
    item_ratio = round(current_count / previous_count, 4) if previous_count else 1.0
    current_rules = _rule_ids(current)
    previous_rules = _rule_ids(previous)
    rule_ratio = round(len(current_rules) / len(previous_rules), 4) if previous_rules else 1.0
    cur_dims = Counter(str(item.get("dimension") or "未分组") for item in _source_items(current))
    prev_dims = Counter(str(item.get("dimension") or "未分组") for item in _source_items(previous))
    dimension_delta = {
        dim: cur_dims.get(dim, 0) - prev_dims.get(dim, 0)
        for dim in sorted(set(cur_dims) | set(prev_dims))
    }

    if item_ratio < 0.8:
        status = "drop_risk"
        explanation = f"本次输出明显变少：{previous_count} -> {current_count}，低于 80% 守门线，建议复查预算、规则或 worker 状态。"
    elif item_delta < 0:
        status = "slight_drop"
        explanation = f"本次输出小幅减少：{previous_count} -> {current_count}，仍在守门线内，可抽查减少维度。"
    elif item_delta > 0:
        status = "increased"
        explanation = f"本次输出增加：{previous_count} -> {current_count}，需要关注是否引入重复或过宽规则。"
    else:
        status = "stable"
        explanation = f"本次输出数量稳定：{current_count} 条。"

    return {
        "status": status,
        "previous_count": previous_count,
        "current_count": current_count,
        "item_delta": item_delta,
        "item_ratio": item_ratio,
        "previous_rule_count": len(previous_rules),
        "current_rule_count": len(current_rules),
        "rule_ratio": rule_ratio,
        "dimension_delta": dimension_delta,
        "pm_explanation": explanation,
    }


def enrich_pm_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    if "pm_summary" not in payload:
        payload["pm_summary"] = build_pm_summary(payload)
    if "pm_view" not in payload:
        payload["pm_view"] = build_pm_view(payload)
    if "testability_summary" not in payload:
        payload["testability_summary"] = build_testability_summary(payload)
    if "zhiqu_handoff" not in payload:
        payload["zhiqu_handoff"] = build_zhiqu_handoff(payload)
    return payload


def _cell(value: Any, limit: int = 240) -> str:
    text = "" if value is None else str(value)
    return text.replace("\r", " ").replace("\n", " ").replace("|", "\\|")[:limit]


def render_markdown(payload: Dict[str, Any]) -> str:
    payload = enrich_pm_payload(payload)
    completion = payload.get("completion") or {}
    pm_summary = payload.get("pm_summary") or {}
    pm_view = payload.get("pm_view") or {}
    testability = payload.get("testability_summary") or {}
    output_change = payload.get("output_change")
    lines = [
        f"# GPT Route Run - {payload.get('case_label')}",
        "",
        "## PM 结论卡",
        "",
        f"- 评审模式: `{pm_summary.get('review_mode', 'deep')}`",
        f"- 准入结论: **{pm_summary.get('verdict', '-')}**",
        f"- 返工风险: **{pm_summary.get('rework_risk', '-')}**",
        f"- 阻塞项: {pm_summary.get('blocking_count', 0)} / 总问题 {pm_summary.get('total_items', 0)}",
        "- 重点风险维度: "
        + (
            "、".join(f"{d['dimension']}({d['count']})" for d in pm_summary.get("top_risk_dimensions") or [])
            or "-"
        ),
        "",
        "## PM 优先修改清单",
        "",
        "| # | 必改 | 位置 | 问题 | 为什么影响协作 | 建议改法 | 可粘贴修订 |",
        "| ---: | --- | --- | --- | --- | --- | --- |",
    ]
    for idx, item in enumerate(pm_summary.get("priority_items") or [], 1):
        must = "是" if str(item.get("severity") or "").lower() == "must" else "否"
        lines.append(
            f"| {idx} | {must} | {_cell(item.get('location'))} | {_cell(item.get('issue'))} | "
            f"{_cell(item.get('why_it_matters'))} | {_cell(item.get('suggested_change'))} | "
            f"{_cell(item.get('prd_patch'))} |"
        )

    lines += [
        "",
        "## 织雀测试用例交接",
        "",
        f"- 可测性结论: **{testability.get('testability_verdict', '-')}**",
        f"- 预计用例覆盖度: **{testability.get('estimated_case_coverage', '-')}**",
        f"- 阻塞测试生成缺口: {testability.get('blocking_gap_count', 0)}",
        f"- 影响用例质量问题: {testability.get('quality_risk_count', 0)}",
        f"- 工程上下文提示: {testability.get('engineering_context_count', 0)}",
        "- 给织雀的约束: 不要脑补缺失需求；阻塞项需要 PM 补充后再生成对应用例。",
    ]
    handoff_path = ((payload.get("report_paths") or {}).get("zhiqu_handoff"))
    if handoff_path:
        lines.append(f"- 交接包: `{handoff_path}`")

    if output_change:
        lines += [
            "",
            "## 输出变化解释",
            "",
            f"- 状态: `{output_change.get('status')}`",
            f"- 数量变化: {output_change.get('previous_count')} -> {output_change.get('current_count')} "
            f"({output_change.get('item_delta'):+})",
            f"- 规则覆盖率: {output_change.get('rule_ratio')}",
            f"- PM 解释: {output_change.get('pm_explanation')}",
        ]

    lines += [
        "",
        "## 角色视图",
        "",
        f"- PM 默认视图: {pm_view.get('pm_count', 0)} 条",
        f"- 工程展开视图: {pm_view.get('engineering_count', 0)} 条",
        "",
        "## PM 反馈标签",
        "",
        "每条问题建议标记一个反馈标签：`有用` / `误报` / `已在别处说明` / `表达不清` / `优先级过高`。",
        "可进入 `scripts/feedback_v2.py` 做规则学习，避免把一次性判断写死进规则。",
        "",
        "## Run Metadata",
        "",
        f"- Workspace: `{payload.get('workspace')}`",
        f"- PRD files: `{', '.join(payload.get('prd_files') or [])}`",
        f"- Elapsed: {float(payload.get('elapsed_s') or 0):.1f}s",
        f"- Merged items: {payload.get('merged_count')}",
        f"- Completion: `{completion.get('status', 'unknown')}`",
        f"- Recovered workers: `{', '.join(completion.get('recovered_workers') or []) or '-'}`",
        f"- Failed workers: `{', '.join(completion.get('failed_workers') or []) or '-'}`",
        f"- Verification: `{payload.get('verification_summary')}`",
    ]
    if payload.get("performance_delta"):
        delta = payload["performance_delta"]
        lines.append(
            f"- Previous baseline: {delta['previous_elapsed_s']:.1f}s; "
            f"delta {delta['delta_s']:+.1f}s; speedup {delta.get('speedup_ratio')}"
        )

    lines += [
        "",
        "## Workers",
        "",
        "| Dim | Status | Model | Items | Duration ms | Error | Wiki chars |",
        "| --- | --- | --- | ---: | ---: | --- | ---: |",
    ]
    for event in payload.get("worker_events") or []:
        ws = event.get("wiki_selection") or {}
        lines.append(
            f"| {_cell(event.get('dim'))} | {_cell(event.get('status') or 'success')} | "
            f"{_cell(event.get('model'))} | {event.get('items')} | {event.get('duration_ms')} | "
            f"{_cell(event.get('error'))} | {ws.get('total_chars_after') or ''} |"
        )

    lines += ["", "## Items", "", "| # | Severity | Dimension | Rule | Title | Verification |", "| ---: | --- | --- | --- | --- | --- |"]
    for idx, item in enumerate(payload.get("items") or [], 1):
        lines.append(
            f"| {idx} | {_cell(item.get('severity'))} | {_cell(item.get('dimension'))} | "
            f"{_cell(item.get('rule_id'))} | {_cell(item.get('title'))} | "
            f"{_cell(item.get('verification_status') or item.get('reason_code'))} |"
        )
    return "\n".join(lines) + "\n"


def render_pm_revision_markdown(payload: Dict[str, Any]) -> str:
    payload = enrich_pm_payload(payload)
    items = sorted(_source_items(payload), key=_priority_sort_key)
    lines = [
        f"# PM 建议修订版 - {payload.get('case_label')}",
        "",
        "此文件不覆盖原 PRD，只给出建议补充或替换文本，方便 PM 逐条复制回源文档。",
        "",
    ]
    for idx, item in enumerate(items, 1):
        action = _pm_action_item(item)
        lines += [
            f"## {idx}. {action.get('location')}",
            "",
            f"- 问题: {action.get('issue')}",
            f"- 建议: {action.get('suggested_change')}",
            "",
            "```markdown",
            action.get("prd_patch") or "",
            "```",
            "",
            f"- 反馈标签: {' / '.join(FEEDBACK_OPTIONS)}",
            "",
        ]
    if not items:
        lines.append("本次没有需要生成修订建议的问题。")
    return "\n".join(lines).rstrip() + "\n"


def write_reports(payload: Dict[str, Any], output_dir: Path, *, timestamp: str | None = None) -> Dict[str, Path]:
    payload = enrich_pm_payload(payload)
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = timestamp or time.strftime("%Y%m%d_%H%M%S")
    safe = safe_file_label(payload.get("file_label") or payload.get("case_label"))
    json_path = output_dir / f"gpt_route_{safe}_{ts}.json"
    md_path = output_dir / f"gpt_route_{safe}_{ts}.md"
    pm_revision_path = output_dir / f"gpt_route_{safe}_{ts}_pm_revision.md"
    zhiqu_handoff_path = output_dir / f"gpt_route_{safe}_{ts}_zhiqu_handoff.json"
    paths = {
        "json": json_path,
        "md": md_path,
        "pm_revision": pm_revision_path,
        "zhiqu_handoff": zhiqu_handoff_path,
    }
    payload["report_paths"] = {k: str(v) for k, v in paths.items()}
    payload["zhiqu_handoff"] = build_zhiqu_handoff(payload)
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    md_path.write_text(render_markdown(payload), encoding="utf-8")
    pm_revision_path.write_text(render_pm_revision_markdown(payload), encoding="utf-8")
    zhiqu_handoff_path.write_text(json.dumps(payload["zhiqu_handoff"], ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    return paths


async def run_case(
    workspace: Path,
    *,
    label: str | None = None,
    output_dir: Path | None = None,
    verify: bool = True,
    mode: str = "deep",
) -> Dict[str, Any]:
    output_dir = output_dir or (ROOT / "eval_reports")
    display_label = label or workspace.name
    file_label = safe_file_label(label or workspace.name)
    os.environ["WORKSPACE"] = str(workspace)
    os.environ.pop("PECKER_MODEL_OVERRIDE", None)
    previous_mode = os.environ.get("PECKER_REVIEW_MODE")
    os.environ["PECKER_REVIEW_MODE"] = mode
    worker_events: List[Dict[str, Any]] = []

    def on_worker_done(dim: str, result: Dict[str, Any]) -> None:
        event = worker_event(dim, result)
        worker_events.append(event)
        print(
            f"[worker_done] {dim} status={event['status']} items={event['items']} "
            f"model={event['model']} duration_ms={event['duration_ms']} error={event['error']}",
            flush=True,
        )

    try:
        t0 = time.time()
        prd_content, prd_files = load_prd_content(str(workspace))
        if prd_content is None:
            raise RuntimeError(f"No PRD content loaded from {workspace}")
        wiki_path = workspace / "wiki"
        wiki_pages = load_wiki_pages(str(wiki_path)) if wiki_path.exists() else {}
        print(f"[start] {file_label} workspace={workspace}", flush=True)
        print(f"[input] prd_files={prd_files} prd_chars={len(prd_content)} wiki_pages={len(wiki_pages)} mode={mode}", flush=True)
        result = await parallel_review(
            None,
            prd_content,
            wiki_pages,
            MODEL_TIERS,
            wiki_path=str(wiki_path),
            workspace=str(workspace),
            on_worker_done=on_worker_done,
        )
        elapsed = time.time() - t0
        merged_items = result.get("merged_items", [])
        verified_items = (
            verify_evidence(merged_items, str(workspace), client=None, wiki_pages=wiki_pages, prd_content=prd_content)
            if verify
            else merged_items
        )
        payload: Dict[str, Any] = {
            "case_label": display_label,
            "file_label": file_label,
            "workspace": str(workspace),
            "prd_files": prd_files,
            "prd_hash": hashlib.sha256(prd_content.encode("utf-8")).hexdigest(),
            "prd_chars": len(prd_content),
            "wiki_pages": len(wiki_pages),
            "review_mode": mode,
            "elapsed_s": elapsed,
            "worker_events": worker_events,
            "completion": completion_summary(worker_events),
            "total_usage": result.get("total_usage"),
            "merged_count": len(merged_items),
            "verification_summary": summarize_verification(verified_items) if verify else None,
            "items": [summarize_item(item) for item in verified_items],
            "verified_items": verified_items,
        }
        previous_path = find_previous_report(output_dir, file_label)
        if previous_path:
            try:
                previous = json.loads(previous_path.read_text(encoding="utf-8"))
                payload["performance_delta"] = performance_delta(payload, previous)
                payload["output_change"] = output_change_summary(payload, previous)
                payload["previous_report"] = str(previous_path)
            except Exception:
                pass
        paths = write_reports(payload, output_dir)
        payload["report_paths"] = {k: str(v) for k, v in paths.items()}
        print(
            f"[done] {file_label} elapsed={elapsed:.1f}s merged={len(merged_items)} "
            f"md={paths['md']} json={paths['json']} pm_revision={paths['pm_revision']} "
            f"zhiqu_handoff={paths['zhiqu_handoff']}",
            flush=True,
        )
        return payload
    finally:
        if previous_mode is None:
            os.environ.pop("PECKER_REVIEW_MODE", None)
        else:
            os.environ["PECKER_REVIEW_MODE"] = previous_mode


def parse_args(argv: List[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a GPT-routed PRD review case and save JSON/MD reports.")
    parser.add_argument("--workspace", required=True, help="Workspace directory containing prd/ and wiki/.")
    parser.add_argument("--label", default=None, help="Human-readable case label.")
    parser.add_argument("--output-dir", default=str(ROOT / "eval_reports"), help="Report output directory.")
    parser.add_argument("--no-verify", action="store_true", help="Skip evidence verification.")
    parser.add_argument("--mode", choices=["deep", "light"], default="deep", help="Review mode. light uses a smaller wiki budget.")
    return parser.parse_args(argv)


def main(argv: List[str] | None = None) -> int:
    args = parse_args(argv)
    workspace = Path(args.workspace).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    try:
        asyncio.run(run_case(workspace, label=args.label, output_dir=output_dir, verify=not args.no_verify, mode=args.mode))
        return 0
    except Exception as exc:
        output_dir.mkdir(parents=True, exist_ok=True)
        safe = safe_file_label(args.label or workspace.name)
        fail_path = output_dir / f"gpt_route_{safe}_{time.strftime('%Y%m%d_%H%M%S')}_failed.json"
        fail_path.write_text(
            json.dumps(
                {
                    "case_label": args.label or workspace.name,
                    "workspace": str(workspace),
                    "error": str(exc),
                    "traceback": traceback.format_exc(),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"[failed] {safe} error={exc} fail_json={fail_path}", flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
