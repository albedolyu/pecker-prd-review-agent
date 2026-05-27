from __future__ import annotations

from pecker.models import Finding, ReviewRequest, ReviewResult, WorkerResult
from pecker.redaction import redact_text
from pecker.tool_registry import default_registry
from pecker.workers import run_worker


WORKER_ORDER = ("structure", "quality", "data", "implementation")


def run_review(request: ReviewRequest) -> ReviewResult:
    trace: list[str] = []
    trace.append("prepare_context")

    safe_request = request.model_copy(update={"content": redact_text(request.content)})
    trace.append("precheck_assets")
    registry = default_registry()
    registry.execute(
        "prd.extract_sections",
        {"content": safe_request.content[:4000]},
        caller="review.precheck",
    )

    trace.append("fan_out_workers")
    workers: list[WorkerResult] = [run_worker(worker, safe_request) for worker in WORKER_ORDER]

    trace.append("merge_findings")
    findings: list[Finding] = []
    seen: set[str] = set()
    for result in workers:
        for finding in result.output:
            if finding.id not in seen:
                findings.append(finding)
                seen.add(finding.id)

    trace.append("advisor_cross_check")
    findings = _advisor_cross_check(findings)

    trace.append("finalize_report")
    status = "ok" if all(worker.status == "ok" for worker in workers) else "partial"
    summary = f"{len(findings)} findings from {len(workers)} workers."
    return ReviewResult(
        title=safe_request.title,
        status=status,
        findings=findings,
        workers=workers,
        trace=trace,
        summary=summary,
    )


def _advisor_cross_check(findings: list[Finding]) -> list[Finding]:
    """Public demo cross-check.

    The private system runs a stronger advisor layer. The public version keeps a
    deterministic guard that only allows findings with explicit adoption fields.
    """
    return [
        finding
        for finding in findings
        if finding.how_to_fix.strip() and finding.acceptance_check.strip()
    ]
