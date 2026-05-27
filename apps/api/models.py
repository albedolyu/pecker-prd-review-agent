"""
Pecker核心数据类型定义
所有模块间传递的数据结构集中定义，替代裸 dict

注意：以下类型定义为预留的结构化类型规范，供渐进式迁移使用。
当前各模块仍使用 dict 传递数据，这些 dataclass 尚未被 import，
但保留作为后续替换裸 dict 的目标类型。

# 使用方式（渐进式迁移）
#
# 从 dict 构造：
#   item = ReviewItem(**item_dict)
#
# 转回 dict：
#   import dataclasses
#   item_dict = dataclasses.asdict(item)
#
# 部分字段缺失时用 get 防御：
#   item = ReviewItem(**{k: item_dict.get(k, "") for k in ReviewItem.__dataclass_fields__})
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# ============================================================
# PM 决策反馈 (2026-04-24 T2: reject 7 分类 + delta 分档)
# ============================================================

class RejectReason(str, Enum):
    """PM 驳回原因 7 分类。spec: docs/pm-reject-reason-schema.md"""
    GOOD_ISSUE = "good_issue"             # 实际是好问题 (PM 手滑 / 改主意)
    FALSE_POSITIVE = "false_positive"     # 误报, PRD 确实没这问题
    KNOWN_TRADEOFF = "known_tradeoff"     # 已知取舍, 业务允许
    WIKI_MISSING = "wiki_missing"         # 知识库缺上下文导致误判
    RULE_TOO_STRICT = "rule_too_strict"   # 规则太严, 不适用本 PRD
    IMPL_DETAIL = "impl_detail"           # 实现细节, 不该 PRD 管
    MODEL_NOISE = "model_noise"           # 模型噪音, 无业务意义


class CorrectnessReason(str, Enum):
    """Rule-quality rejection reasons that are allowed to update EMA."""
    FALSE_POSITIVE = "false_positive"
    UNSUPPORTED_EVIDENCE = "unsupported_evidence"
    RULE_TOO_STRICT = "rule_too_strict"


class BusinessDecision(str, Enum):
    """Business decisions that should not punish a valid rule."""
    NOT_THIS_ITERATION = "not_this_iteration"
    RISK_ACCEPTED = "risk_accepted"
    HANDLED_ELSEWHERE = "handled_elsewhere"


# EMA impact_score 的 reject delta — 按 reason 分档, 只惩罚"规则问题"类
# 规则精度问题 (false_positive/rule_too_strict) 强惩罚
# 模型/scope 问题 (model_noise/impl_detail) 中等
# 非规则问题 (wiki_missing/known_tradeoff) 弱惩罚
# PM 手滑 (good_issue) 正向微调
REJECT_DELTA_BY_REASON = {
    RejectReason.FALSE_POSITIVE.value: -0.5,
    RejectReason.RULE_TOO_STRICT.value: -0.5,
    RejectReason.MODEL_NOISE.value: -0.3,
    RejectReason.IMPL_DETAIL.value: -0.3,
    RejectReason.WIKI_MISSING.value: -0.1,
    RejectReason.KNOWN_TRADEOFF.value: -0.1,
    RejectReason.GOOD_ISSUE.value: 0.3,
}

CORRECTNESS_DELTA_BY_REASON = {
    CorrectnessReason.FALSE_POSITIVE.value: -0.5,
    CorrectnessReason.UNSUPPORTED_EVIDENCE.value: -0.1,
    CorrectnessReason.RULE_TOO_STRICT.value: -0.5,
}


def reject_delta_for_reason(reason_category: str) -> float:
    """按 reason 分档返回 reject delta。未知 reason 走 -0.3 保守默认 (model_noise 等价)。"""
    return REJECT_DELTA_BY_REASON.get(reason_category, -0.3)


def rule_quality_reason_for_decision(decision: dict) -> str:
    correctness_reason = str((decision or {}).get("correctness_reason") or "").strip()
    if correctness_reason:
        return correctness_reason
    if (decision or {}).get("business_decision"):
        return ""
    return str((decision or {}).get("reason_category") or "model_noise")


def reject_delta_for_decision(decision: dict) -> float:
    quality_reason = rule_quality_reason_for_decision(decision)
    if not quality_reason:
        return 0.0
    if str((decision or {}).get("correctness_reason") or "").strip():
        return CORRECTNESS_DELTA_BY_REASON.get(quality_reason, -0.3)
    return reject_delta_for_reason(quality_reason)


@dataclass
class PMDecision:
    """PM 单条决策 (渐进迁移, 当前代码仍用 dict, 此 dataclass 为后续替换目标类型)"""
    item_id: str
    action: str                                       # "accept" | "reject" | "edit"
    reason_category: str = ""                         # RejectReason value, 仅 reject 时有效
    reason_note: str = ""                             # 可选自由文本补充
    edited_content: dict = field(default_factory=dict)   # action=edit 时的修改后内容
    correctness_reason: str = ""                      # CorrectnessReason value, updates EMA
    business_decision: str = ""                       # BusinessDecision value, neutral for EMA

    @classmethod
    def from_dict(cls, item_id: str, d: dict) -> PMDecision:
        """从 dict 构造。兼容老字段: 旧 `reason` 自由文本映射到 `reason_note`。"""
        return cls(
            item_id=item_id,
            action=d.get("action", ""),
            reason_category=d.get("reason_category", ""),
            correctness_reason=d.get("correctness_reason", ""),
            business_decision=d.get("business_decision", ""),
            reason_note=d.get("reason_note", d.get("reason", "")),
            edited_content=d.get("edited_content", {}),
        )


# ============================================================
# parallel_review.py
# ============================================================

@dataclass
class ReviewItem:
    """单条评审改进项（worker 输出 / 合并后列表的元素）"""
    id: str
    location: str
    issue: str
    suggestion: str
    severity: str              # "must" | "should" | "could" (could = 苍鹰冲突合并保留的同源 facet)
    evidence_type: str         # "A" | "B" | "C"
    evidence_content: str
    dimension: str = ""        # 评审维度名，如 "结构层"
    status: str = ""           # "VERIFIED" | "RETRACTED" | "REMOVED_BY_ADVISOR" | "MERGED_BY_ADVISOR"
    advisor_note: str = ""
    retract_reason: str = ""
    source: str = ""           # "苍鹰补充" 等
    facet_of: str = ""         # 当 status=MERGED_BY_ADVISOR 时,指向 primary item id (could 级 facet)

    @classmethod
    def from_dict(cls, d: dict) -> ReviewItem:
        fields = {f.name for f in dataclasses.fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in fields})


@dataclass
class WorkerResult:
    """单个评审维度 worker 的输出"""
    dimension: str             # 维度 key，如 "structure"
    dimension_name: str        # 维度中文名，如 "结构层"
    model: str
    items: list[dict]          # ReviewItem dict 列表（保持 dict 便于现有代码兼容）
    usage: dict                # {"input_tokens": int, "output_tokens": int}
    error: Optional[str] = None

    @classmethod
    def from_dict(cls, d: dict) -> WorkerResult:
        return cls(
            dimension=d.get("dimension", ""),
            dimension_name=d.get("dimension_name", ""),
            model=d.get("model", ""),
            items=d.get("items", []),
            usage=d.get("usage", {"input_tokens": 0, "output_tokens": 0}),
            error=d.get("error"),
        )


@dataclass
class ParallelResult:
    """parallel_review() 的完整返回值"""
    workers: list[WorkerResult]
    merged_items: list[dict]   # 合并去重后的 ReviewItem dict 列表
    total_usage: dict          # {"input_tokens": int, "output_tokens": int}

    @classmethod
    def from_dict(cls, d: dict) -> ParallelResult:
        return cls(
            workers=[WorkerResult.from_dict(w) for w in d.get("workers", [])],
            merged_items=d.get("merged_items", []),
            total_usage=d.get("total_usage", {"input_tokens": 0, "output_tokens": 0}),
        )


# ============================================================
# goshawk_advisor.py
# ============================================================

# 2026-04-26 audit wave2 P2-D: 删 4 个 dataclass 死代码 (FalsePositive / AdditionalFinding /
# ConflictResolution / AdvisorResult). 全仓 grep 确认无 .py / .json / .jsonl import,
# 实际 _extract_advisor_result 直接返 dict, 这些 dataclass 从未被使用.
# 同时还和 goshawk_advisor.py 的实际 schema (e.g. AdditionalFinding 4 字段 vs schema 7 字段) drift.
# 保留 dict 是当前 source of truth.


# ============================================================
# cuckoo_eval.py
# ============================================================

@dataclass
class PlantedBug:
    """预埋 bug，用于杜鹃评测"""
    id: str                    # "BUG-001"
    location: str              # PRD 章节号，如 "3.7"
    type: str                  # "笔误" | "不一致" | "字段类型" | "缺失" | "歧义"
    severity: str              # "must" | "should"
    description: str
    keywords: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> PlantedBug:
        return cls(
            id=d["id"],
            location=d.get("location", ""),
            type=d.get("type", "歧义"),
            severity=d.get("severity", "should"),
            description=d.get("description", ""),
            keywords=d.get("keywords", []),
        )


@dataclass
class TestCase:
    """杜鹃测试用例（对应 JSON 文件）"""
    name: str
    prd_file: str
    planted_bugs: list[PlantedBug]
    non_issues: list[dict] = field(default_factory=list)  # [{"location": str, "reason": str}]
    generated_from: str = ""
    generated_at: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> TestCase:
        return cls(
            name=d.get("name", ""),
            prd_file=d.get("prd_file", ""),
            planted_bugs=[PlantedBug.from_dict(b) for b in d.get("planted_bugs", [])],
            non_issues=d.get("non_issues", []),
            generated_from=d.get("generated_from", ""),
            generated_at=d.get("generated_at", ""),
        )


@dataclass
class MatchResult:
    """单条 bug 与改进项的匹配结果"""
    bug: PlantedBug
    item: dict                 # ReviewItem dict
    score: int
    location_match: bool
    keyword_hits: int
    severity_match: bool

    @classmethod
    def from_dict(cls, d: dict) -> MatchResult:
        return cls(
            bug=PlantedBug.from_dict(d["bug"]),
            item=d["item"],
            score=d.get("score", 0),
            location_match=d.get("location_match", False),
            keyword_hits=d.get("keyword_hits", 0),
            severity_match=d.get("severity_match", False),
        )


@dataclass
class EvalScores:
    """calculate_scores() 的完整返回值"""
    recall: float
    precision: float
    location_accuracy: float
    evidence_reliability: float
    severity_accuracy: float
    format_completeness: float
    overall_score: float
    overall_verdict: str       # "PASS" | "PARTIAL" | "FAIL"
    detail: dict               # hit_count, miss_count, false_positive_count 等

    @classmethod
    def from_dict(cls, d: dict) -> EvalScores:
        return cls(
            recall=d.get("recall", 0.0),
            precision=d.get("precision", 0.0),
            location_accuracy=d.get("location_accuracy", 0.0),
            evidence_reliability=d.get("evidence_reliability", 0.0),
            severity_accuracy=d.get("severity_accuracy", 0.0),
            format_completeness=d.get("format_completeness", 0.0),
            overall_score=d.get("overall_score", 0.0),
            overall_verdict=d.get("overall_verdict", "FAIL"),
            detail=d.get("detail", {}),
        )


# ============================================================
# feedback.py
# ============================================================

@dataclass
class Signal:
    """下游信号（从代码目录采集）"""
    type: str                  # "assumption" | "field_inconsistency" | "rework" | "ui_state_gap"
    file: str
    content: str
    line: Optional[int] = None
    keyword: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> Signal:
        return cls(
            type=d.get("type", ""),
            file=d.get("file", ""),
            content=d.get("content", ""),
            line=d.get("line"),
            keyword=d.get("keyword", ""),
        )


@dataclass
class Outcome:
    """评审项结局追踪结果"""
    item_id: str               # 如 "R-001" 或 "MISSED"
    location: str
    severity: str
    status: str                # "confirmed" | "rejected" | "pending" | "unknown" | "none"
    outcome: str               # "effective_catch" | "insufficient_fix" | "wrong_rejection" | "missed" | "no_signal"
    related_signals: list[Signal] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> Outcome:
        return cls(
            item_id=d.get("item_id", ""),
            location=d.get("location", ""),
            severity=d.get("severity", ""),
            status=d.get("status", "unknown"),
            outcome=d.get("outcome", "no_signal"),
            related_signals=[Signal.from_dict(s) for s in d.get("related_signals", [])],
        )


# ============================================================
# shrike_review.py
# ============================================================

@dataclass
class GateResult:
    """单个质量门禁的检查结果"""
    passed: bool
    details: list              # 字符串列表或 dict 列表，因 gate 而异
    rate: Optional[float] = None  # 仅 format_compliance 使用

    @classmethod
    def from_dict(cls, d: dict) -> GateResult:
        return cls(passed=d["passed"], details=d.get("details", []), rate=d.get("rate"))


@dataclass
class ShrikeResult:
    """shrike_review() 的完整返回值"""
    verdict: str               # "PASS" | "FAIL"
    passed: int                # 通过的门禁数
    total: int                 # 总门禁数（固定为 5）
    gates: dict[str, GateResult]

    @classmethod
    def from_dict(cls, d: dict) -> ShrikeResult:
        return cls(
            verdict=d.get("verdict", "FAIL"),
            passed=d.get("passed", 0),
            total=d.get("total", 5),
            gates={k: GateResult.from_dict(v) for k, v in d.get("gates", {}).items()},
        )
