import asyncio

from backend.pecker.workers import DEFAULT_WORKERS


SAMPLE_PRD = """# Export Center
## Goal
Improve the export experience.
## Scope
TBD before implementation.
## Metrics
Success should be better than today.
## Data
Store user email in the export record.
"""


def test_default_workers_have_the_four_specialist_names() -> None:
    assert [worker.name for worker in DEFAULT_WORKERS] == [
        "structure",
        "product_quality",
        "ai_coding_readiness",
        "data_quality",
    ]


def test_each_worker_returns_bounded_deterministic_grounded_findings() -> None:
    first_runs = [
        asyncio.run(worker.run("Export Center", SAMPLE_PRD))
        for worker in DEFAULT_WORKERS
    ]
    second_runs = [
        asyncio.run(worker.run("Export Center", SAMPLE_PRD))
        for worker in DEFAULT_WORKERS
    ]
    lines = SAMPLE_PRD.splitlines()

    assert [run.model_dump() for run in first_runs] == [
        run.model_dump() for run in second_runs
    ]
    assert all(run.status == "completed" for run in first_runs)
    assert all(run.tokens_used == 0 for run in first_runs)
    assert all(len(run.output) <= 3 for run in first_runs)
    assert any(run.output for run in first_runs)

    all_findings = [finding for run in first_runs for finding in run.output]
    assert len({finding.id for finding in all_findings}) == len(all_findings)
    for finding in all_findings:
        assert 0.0 <= finding.confidence <= 1.0
        assert 1 <= finding.line <= len(lines)
        assert finding.evidence == lines[finding.line - 1]
        assert finding.evidence in SAMPLE_PRD


def test_worker_run_has_only_the_standard_public_result_fields() -> None:
    result = asyncio.run(DEFAULT_WORKERS[0].run("Short note", "One line only."))

    assert set(result.model_dump()) == {
        "status",
        "output",
        "confidence",
        "tokens_used",
    }


def test_chinese_input_literals_drive_rules_without_encoding_loss() -> None:
    workers = {worker.name: worker for worker in DEFAULT_WORKERS}

    structure = asyncio.run(workers["structure"].run("需求", "# 需求\n范围：待定"))
    assert structure.output[0].category == "structure_placeholder"
    assert structure.output[0].evidence == "范围：待定"
    assert structure.output[0].line == 2
    assert "scope_section" not in {finding.category for finding in structure.output}

    product = asyncio.run(
        workers["product_quality"].run("需求", "# 需求\n目标用户：普通用户\n目标：提升效率")
    )
    assert "measurable_outcome" in {finding.category for finding in product.output}
    assert "target_user" not in {finding.category for finding in product.output}

    data = asyncio.run(workers["data_quality"].run("需求", "# 需求\n存储用户邮箱"))
    assert data.output[0].category == "personal_data_handling"
    assert data.output[0].evidence == "存储用户邮箱"
