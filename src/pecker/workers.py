from __future__ import annotations

from collections.abc import Callable

from pecker.models import Finding, ReviewRequest, WorkerName, WorkerResult


WorkerFn = Callable[[ReviewRequest], WorkerResult]


def run_worker(worker: WorkerName, request: ReviewRequest) -> WorkerResult:
    return WORKERS[worker](request)


def structure_worker(request: ReviewRequest) -> WorkerResult:
    findings: list[Finding] = []
    content = request.content.lower()
    if "goal" not in content and "objective" not in content:
        findings.append(_finding("structure", "S-001", "Missing goal", "Add a short product goal section."))
    if "user stor" not in content and "scenario" not in content:
        findings.append(_finding("structure", "S-002", "Missing user scenario", "Add user stories or scenarios."))
    if "open question" not in content and "risk" not in content:
        findings.append(_finding("structure", "S-003", "No uncertainty section", "Add open questions and product risks."))
    return _result("structure", findings, request)


def quality_worker(request: ReviewRequest) -> WorkerResult:
    findings: list[Finding] = []
    content = request.content.lower()
    if "acceptance" not in content and "done when" not in content:
        findings.append(_finding("quality", "Q-001", "No acceptance criteria", "Add testable acceptance criteria."))
    if any(word in content for word in ("fast", "simple", "friendly")) and "metric" not in content:
        findings.append(_finding("quality", "Q-002", "Qualitative terms lack metrics", "Define measurable thresholds."))
    return _result("quality", findings, request)


def data_worker(request: ReviewRequest) -> WorkerResult:
    findings: list[Finding] = []
    content = request.content.lower()
    if "store" in content and "retention" not in content:
        findings.append(_finding("data", "D-001", "Data retention is unclear", "State retention and deletion rules."))
    if "email" in content and "unsubscribe" not in content:
        findings.append(_finding("data", "D-002", "Notification preference is incomplete", "Add unsubscribe and preference handling."))
    return _result("data", findings, request)


def implementation_worker(request: ReviewRequest) -> WorkerResult:
    findings: list[Finding] = []
    content = request.content.lower()
    if "fail" not in content and "error" not in content:
        findings.append(_finding("implementation", "I-001", "Failure behavior is missing", "Define error states and retry behavior."))
    if "api" not in content and "event" not in content:
        findings.append(_finding("implementation", "I-002", "Integration contract is unclear", "Add API or event contract details."))
    return _result("implementation", findings, request)


def _finding(worker: WorkerName, finding_id: str, title: str, action: str) -> Finding:
    return Finding(
        id=finding_id,
        worker=worker,
        title=title,
        severity="medium",
        issue=title,
        evidence="Heuristic public demo finding.",
        recommendation=action,
        how_to_fix=f"{action} Include owner, trigger, edge cases, and a concrete example.",
        acceptance_check="A reviewer can verify the behavior without asking for hidden context.",
    )


def _result(worker: WorkerName, findings: list[Finding], request: ReviewRequest) -> WorkerResult:
    return WorkerResult(
        status="ok",
        worker=worker,
        output=findings[: request.max_findings_per_worker],
        confidence=0.75 if findings else 0.9,
        tokens_used=max(1, len(request.content) // 4),
    )


WORKERS: dict[WorkerName, WorkerFn] = {
    "structure": structure_worker,
    "quality": quality_worker,
    "data": data_worker,
    "implementation": implementation_worker,
}
