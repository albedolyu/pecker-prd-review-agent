"""
啄木鸟核心数据类型定义
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
from typing import Optional


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
    severity: str              # "must" | "should"
    evidence_type: str         # "A" | "B" | "C"
    evidence_content: str
    dimension: str = ""        # 评审维度名，如 "结构层"
    status: str = ""           # "VERIFIED" | "RETRACTED" | "REMOVED_BY_ADVISOR" | "MERGED_BY_ADVISOR"
    advisor_note: str = ""
    retract_reason: str = ""
    source: str = ""           # "苍鹰补充" 等

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

@dataclass
class FalsePositive:
    """苍鹰标记的误报条目"""
    item_id: str               # 如 "R-003"
    reason: str
    recommendation: str        # "降级为 should" | "移除"

    @classmethod
    def from_dict(cls, d: dict) -> FalsePositive:
        return cls(item_id=d["item_id"], reason=d["reason"], recommendation=d["recommendation"])


@dataclass
class AdditionalFinding:
    """苍鹰补充的漏报条目（最多 3 条）"""
    location: str
    issue: str
    severity: str              # "must" | "should"
    evidence: str

    @classmethod
    def from_dict(cls, d: dict) -> AdditionalFinding:
        return cls(
            location=d.get("location", ""),
            issue=d.get("issue", ""),
            severity=d.get("severity", "should"),
            evidence=d.get("evidence", ""),
        )


@dataclass
class ConflictResolution:
    """苍鹰的冲突调解结果"""
    items: list[str]           # 冲突的改进项编号列表，如 ["R-005", "R-007"]
    resolution: str
    reason: str

    @classmethod
    def from_dict(cls, d: dict) -> ConflictResolution:
        return cls(items=d.get("items", []), resolution=d["resolution"], reason=d["reason"])


@dataclass
class AdvisorResult:
    """advisor_review() 的完整返回值"""
    flagged_as_false_positive: list[FalsePositive]
    additional_findings: list[AdditionalFinding]
    conflict_resolutions: list[ConflictResolution]
    confidence: float          # 0.0 ~ 1.0
    verdict: str = "REVIEWED"
    model_used: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> AdvisorResult:
        return cls(
            flagged_as_false_positive=[FalsePositive.from_dict(x) for x in d.get("flagged_as_false_positive", [])],
            additional_findings=[AdditionalFinding.from_dict(x) for x in d.get("additional_findings", [])],
            conflict_resolutions=[ConflictResolution.from_dict(x) for x in d.get("conflict_resolutions", [])],
            confidence=d.get("confidence", 0.0),
            verdict=d.get("verdict", "REVIEWED"),
            model_used=d.get("model_used", ""),
        )


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
