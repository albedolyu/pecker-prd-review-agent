import asyncio

from backend.pecker.models import Finding, WorkerRun
from backend.pecker.orchestrator import run_review
from backend.pecker.workers import DEFAULT_WORKERS


def _finding(
    finding_id: str,
    worker: str,
    *,
    category: str = "scope",
    evidence: str = "Line one",
) -> Finding:
    return Finding(
        id=finding_id,
        worker=worker,
        category=category,
        severity="medium",
        title="Clarify scope",
        evidence=evidence,
        line=1,
        recommendation="State what is in and out of scope.",
        confidence=0.9,
    )


class WaitingWorker:
    def __init__(self, name: str, started: set[str], all_started: asyncio.Event) -> None:
        self.name = name
        self._started = started
        self._all_started = all_started

    async def run(self, title: str, content: str) -> WorkerRun:
        self._started.add(self.name)
        if len(self._started) == 2:
            self._all_started.set()
        await asyncio.wait_for(self._all_started.wait(), timeout=0.2)
        return WorkerRun(
            status="completed",
            output=[_finding(self.name, self.name, category=self.name)],
            confidence=0.9,
            tokens_used=0,
        )


class FixedWorker:
    def __init__(self, name: str, findings: list[Finding], delay: float = 0.0) -> None:
        self.name = name
        self._findings = findings
        self._delay = delay

    async def run(self, title: str, content: str) -> WorkerRun:
        await asyncio.sleep(self._delay)
        return WorkerRun(
            status="completed",
            output=self._findings,
            confidence=0.8,
            tokens_used=0,
        )


class RaisingWorker:
    name = "broken"

    async def run(self, title: str, content: str) -> WorkerRun:
        raise RuntimeError("synthetic failure")


def test_run_review_dispatches_workers_concurrently() -> None:
    async def exercise():
        started: set[str] = set()
        all_started = asyncio.Event()
        workers = [
            WaitingWorker("first", started, all_started),
            WaitingWorker("second", started, all_started),
        ]
        return await run_review("Title", "Line one", workers)

    result = asyncio.run(exercise())

    assert list(result.worker_runs) == ["first", "second"]
    assert [finding.worker for finding in result.findings] == ["first", "second"]


def test_consolidation_order_is_input_stable_and_duplicate_rules_are_removed() -> None:
    duplicate_from_first = _finding("first-id", "slow")
    duplicate_from_second = _finding("second-id", "fast")
    distinct = _finding(
        "distinct-id",
        "fast",
        category="data_contract",
        evidence="Line two",
    ).model_copy(update={"line": 2, "title": "Define the data contract"})
    workers = [
        FixedWorker("slow", [duplicate_from_first], delay=0.02),
        FixedWorker("fast", [duplicate_from_second, distinct]),
    ]

    result = asyncio.run(run_review("Title", "Line one\nLine two", workers))

    assert [finding.id for finding in result.findings] == ["first-id", "distinct-id"]
    assert list(result.worker_runs) == ["slow", "fast"]


def test_duplicate_rule_is_removed_even_when_evidence_and_line_differ() -> None:
    first = _finding(
        "first-rule-instance",
        "first",
        category="shared_rule",
        evidence="Line one",
    )
    second = _finding(
        "second-rule-instance",
        "second",
        category="shared_rule",
        evidence="Line two",
    ).model_copy(update={"line": 2})

    result = asyncio.run(
        run_review(
            "Title",
            "Line one\nLine two",
            [FixedWorker("first", [first]), FixedWorker("second", [second])],
        )
    )

    assert [finding.id for finding in result.findings] == ["first-rule-instance"]


def test_one_worker_failure_does_not_abort_other_workers() -> None:
    healthy = FixedWorker("healthy", [_finding("kept", "healthy")])

    result = asyncio.run(
        run_review("Title", "Line one", [RaisingWorker(), healthy])
    )

    assert result.worker_runs["broken"].status == "failed"
    assert result.worker_runs["broken"].output == []
    assert result.worker_runs["broken"].tokens_used == 0
    assert result.worker_runs["healthy"].status == "completed"
    assert [finding.id for finding in result.findings] == ["kept"]


def test_advisor_adds_at_most_two_gaps_without_rewriting_evidence() -> None:
    original = _finding("kept", "only-worker", evidence="Exact submitted line")

    result = asyncio.run(
        run_review(
            "Title",
            "Exact submitted line",
            [FixedWorker("only-worker", [original])],
        )
    )

    assert len(result.advisor.gaps) <= 2
    assert result.findings[0].evidence == "Exact submitted line"
    assert result.findings[0] == original


def test_workers_expose_no_worker_to_worker_invocation_surface() -> None:
    for worker in DEFAULT_WORKERS:
        assert not hasattr(worker, "workers")
        assert not hasattr(worker, "dispatch")
        assert set(vars(worker)) <= {"name"}
