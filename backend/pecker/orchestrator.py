"""Concurrent dispatcher and deterministic result consolidation."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence

from .advisor import review_gaps
from .models import Finding, ReviewResult, WorkerRun
from .workers import DEFAULT_WORKERS, ReviewWorker


def _rule_key(finding: Finding) -> str:
    return finding.category


def _consolidate(worker_runs: Sequence[WorkerRun]) -> list[Finding]:
    findings: list[Finding] = []
    seen_rules: set[str] = set()
    for run in worker_runs:
        if run.status != "completed":
            continue
        for finding in run.output:
            key = _rule_key(finding)
            if key in seen_rules:
                continue
            seen_rules.add(key)
            findings.append(finding)
    return findings


async def run_review(
    title: str,
    content: str,
    workers: Sequence[ReviewWorker] | None = None,
) -> ReviewResult:
    """Dispatch isolated workers concurrently, then consolidate and advise."""

    selected_workers = tuple(DEFAULT_WORKERS if workers is None else workers)
    outcomes = await asyncio.gather(
        *(worker.run(title, content) for worker in selected_workers),
        return_exceptions=True,
    )

    ordered_runs: dict[str, WorkerRun] = {}
    for worker, outcome in zip(selected_workers, outcomes, strict=True):
        if isinstance(outcome, BaseException):
            ordered_runs[worker.name] = WorkerRun(
                status="failed",
                output=[],
                confidence=0.0,
                tokens_used=0,
            )
        else:
            ordered_runs[worker.name] = outcome

    findings = _consolidate(tuple(ordered_runs.values()))
    advisor = review_gaps(findings)
    return ReviewResult(
        title=title,
        findings=findings,
        worker_runs=ordered_runs,
        advisor=advisor,
    )


__all__ = ["run_review"]
