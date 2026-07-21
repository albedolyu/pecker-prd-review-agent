"""Bounded deterministic specialist workers for the public demo."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Protocol

from .models import Finding, WorkerRun


class ReviewWorker(Protocol):
    """Narrow worker surface: workers can review input but cannot dispatch peers."""

    name: str

    async def run(self, title: str, content: str) -> WorkerRun: ...


@dataclass(frozen=True)
class _Rule:
    category: str
    severity: str
    title: str
    recommendation: str
    pattern: re.Pattern[str] | None = None
    missing_terms: tuple[str, ...] = ()
    confidence: float = 0.85


def _source_lines(content: str) -> list[str]:
    return content.splitlines()


def _first_evidence(lines: list[str]) -> tuple[int, str] | None:
    for number, line in enumerate(lines, start=1):
        if line.strip():
            return number, line
    return None


def _matching_evidence(
    lines: list[str], pattern: re.Pattern[str]
) -> tuple[int, str] | None:
    for number, line in enumerate(lines, start=1):
        if pattern.search(line):
            return number, line
    return None


def _finding_id(worker: str, rule: _Rule, line: int, evidence: str) -> str:
    rule_key = "\x1f".join((worker, rule.category, rule.title, str(line), evidence))
    digest = hashlib.sha256(rule_key.encode("utf-8")).hexdigest()[:16]
    return f"finding-{digest}"


def _run_rules(worker: str, content: str, rules: tuple[_Rule, ...]) -> WorkerRun:
    lines = _source_lines(content)
    fallback = _first_evidence(lines)
    lowered = content.casefold()
    findings: list[Finding] = []

    for rule in rules:
        evidence = (
            _matching_evidence(lines, rule.pattern)
            if rule.pattern is not None
            else fallback
        )
        if rule.pattern is None and any(term.casefold() in lowered for term in rule.missing_terms):
            evidence = None
        if evidence is None:
            continue

        line_number, exact_line = evidence
        findings.append(
            Finding(
                id=_finding_id(worker, rule, line_number, exact_line),
                worker=worker,
                category=rule.category,
                severity=rule.severity,
                title=rule.title,
                evidence=exact_line,
                line=line_number,
                recommendation=rule.recommendation,
                confidence=rule.confidence,
            )
        )
        if len(findings) == 3:
            break

    confidence = min((finding.confidence for finding in findings), default=1.0)
    return WorkerRun(
        status="completed",
        output=findings,
        confidence=confidence,
        tokens_used=0,
    )


_PLACEHOLDER = re.compile(r"\b(?:TBD|TBC|TODO)\b|待定|稍后补充", re.IGNORECASE)
_VAGUE_OUTCOME = re.compile(
    r"\b(?:better|improve|optimi[sz]e|user[- ]friendly)\b|提升|优化|更好",
    re.IGNORECASE,
)
_PERSONAL_DATA = re.compile(
    r"\b(?:email|phone|address|personal data)\b|邮箱|手机号|个人信息",
    re.IGNORECASE,
)


class StructureWorker:
    name = "structure"

    async def run(self, title: str, content: str) -> WorkerRun:
        rules = (
            _Rule(
                "structure_placeholder",
                "high",
                "Replace structural placeholders",
                "Replace the placeholder with a concrete, reviewable statement.",
                pattern=_PLACEHOLDER,
                confidence=0.99,
            ),
            _Rule(
                "scope_section",
                "medium",
                "Add an explicit scope section",
                "State included and excluded behavior in a dedicated scope section.",
                missing_terms=("scope", "范围"),
            ),
            _Rule(
                "acceptance_section",
                "medium",
                "Add acceptance criteria",
                "Add observable acceptance criteria for the proposed behavior.",
                missing_terms=("acceptance", "验收"),
            ),
        )
        return _run_rules(self.name, content, rules)


class ProductQualityWorker:
    name = "product_quality"

    async def run(self, title: str, content: str) -> WorkerRun:
        rules = (
            _Rule(
                "measurable_outcome",
                "medium",
                "Make the outcome measurable",
                "Replace the qualitative outcome with a metric and target.",
                pattern=_VAGUE_OUTCOME,
                confidence=0.95,
            ),
            _Rule(
                "target_user",
                "medium",
                "Identify the target user",
                "Name the user segment and the job they need to complete.",
                missing_terms=("user", "用户", "persona"),
            ),
            _Rule(
                "failure_experience",
                "low",
                "Define the failure experience",
                "Describe what the user sees and can do when the flow fails.",
                missing_terms=("error", "failure", "失败", "异常"),
                confidence=0.8,
            ),
        )
        return _run_rules(self.name, content, rules)


class AICodingReadinessWorker:
    name = "ai_coding_readiness"

    async def run(self, title: str, content: str) -> WorkerRun:
        rules = (
            _Rule(
                "implementation_placeholder",
                "high",
                "Resolve implementation placeholders",
                "Replace the placeholder with an explicit implementation constraint.",
                pattern=_PLACEHOLDER,
                confidence=0.99,
            ),
            _Rule(
                "interface_contract",
                "high",
                "Define the interface contract",
                "Specify inputs, outputs, validation, and failure responses.",
                missing_terms=("api", "input", "output", "接口", "输入", "输出"),
                confidence=0.9,
            ),
            _Rule(
                "test_examples",
                "medium",
                "Add executable examples",
                "Provide concrete examples that can become deterministic tests.",
                missing_terms=("example", "test", "示例", "测试"),
            ),
        )
        return _run_rules(self.name, content, rules)


class DataQualityWorker:
    name = "data_quality"

    async def run(self, title: str, content: str) -> WorkerRun:
        rules = (
            _Rule(
                "personal_data_handling",
                "high",
                "Define personal-data handling",
                "Specify minimization, masking, access, retention, and deletion rules.",
                pattern=_PERSONAL_DATA,
                confidence=0.98,
            ),
            _Rule(
                "data_source",
                "medium",
                "Name the source of truth",
                "Identify the authoritative source and refresh behavior.",
                missing_terms=("source", "来源", "source of truth"),
            ),
            _Rule(
                "data_validation",
                "medium",
                "Define data validation",
                "State required fields, formats, and invalid-record handling.",
                missing_terms=("validation", "validate", "校验", "验证"),
            ),
        )
        return _run_rules(self.name, content, rules)


DEFAULT_WORKERS: tuple[ReviewWorker, ...] = (
    StructureWorker(),
    ProductQualityWorker(),
    AICodingReadinessWorker(),
    DataQualityWorker(),
)


__all__ = [
    "AICodingReadinessWorker",
    "DEFAULT_WORKERS",
    "DataQualityWorker",
    "ProductQualityWorker",
    "ReviewWorker",
    "StructureWorker",
]
