import asyncio
from pathlib import Path

import pytest

from backend.pecker.repository import ReviewRepository
from backend.pecker.service import (
    InvalidDecisionError,
    ReviewNotFoundError,
    ReviewService,
)


REVIEW_TEXT = """# Synthetic Export Desk
## Goal
Improve the export experience.
## Scope
TBD before implementation.
## Metrics
Success should be better than today.
## Data
Store user email in the export record.
"""


def _service(tmp_path: Path) -> ReviewService:
    return ReviewService(
        ReviewRepository(tmp_path / "reviews.db"),
        samples_directory=Path(__file__).parents[1] / "samples",
    )


def test_samples_are_explicitly_labelled_synthetic_demo_data(tmp_path: Path) -> None:
    samples = _service(tmp_path).list_samples()

    assert [sample["id"] for sample in samples] == [
        "export-center",
        "team-notes-search",
    ]
    assert all(sample["synthetic"] is True for sample in samples)
    assert all(sample["content"].startswith("> **Synthetic demo data:**") for sample in samples)
    assert all("Synthetic" in sample["label"] for sample in samples)


def test_create_review_persists_completed_demo_snapshot_and_worker_statuses(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)

    review = asyncio.run(service.create_review("Synthetic Export Desk", REVIEW_TEXT))

    assert review["status"] == "completed"
    assert review["mode"] == "deterministic-demo"
    assert set(review["worker_runs"]) == {
        "structure",
        "product_quality",
        "ai_coding_readiness",
        "data_quality",
    }
    assert all(
        run["tokens_used"] == 0 for run in review["worker_runs"].values()
    )
    assert service.get_review(review["review_id"]) == review


def test_unknown_review_ids_raise_a_specific_not_found_error(tmp_path: Path) -> None:
    service = _service(tmp_path)

    with pytest.raises(ReviewNotFoundError):
        service.get_review("review-missing")
    with pytest.raises(ReviewNotFoundError):
        service.apply_decisions("review-missing", [])
    with pytest.raises(ReviewNotFoundError):
        service.generate_report("review-missing")


def test_invalid_decision_finding_is_rejected_without_partial_updates(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    review = asyncio.run(service.create_review("Synthetic Export Desk", REVIEW_TEXT))
    valid_id = review["findings"][0]["id"]

    with pytest.raises(InvalidDecisionError):
        service.apply_decisions(
            review["review_id"],
            [
                {"finding_id": valid_id, "action": "accept"},
                {"finding_id": "finding-missing", "action": "reject"},
            ],
        )

    unchanged = service.get_review(review["review_id"])
    assert all(finding["decision"] is None for finding in unchanged["findings"])


def test_report_contains_only_accepted_or_edited_findings(tmp_path: Path) -> None:
    service = _service(tmp_path)
    review = asyncio.run(service.create_review("Synthetic Export Desk", REVIEW_TEXT))
    accepted, rejected, edited, unconfirmed = review["findings"][:4]

    service.apply_decisions(
        review["review_id"],
        [
            {"finding_id": accepted["id"], "action": "accept"},
            {"finding_id": rejected["id"], "action": "reject"},
            {
                "finding_id": edited["id"],
                "action": "edit",
                "edited_title": "Use the approved synthetic title",
                "edited_recommendation": "Use the approved synthetic recommendation.",
            },
        ],
    )

    markdown = service.generate_report(review["review_id"])

    assert accepted["title"] in markdown
    assert accepted["recommendation"] in markdown
    assert rejected["title"] not in markdown
    assert "Use the approved synthetic title" in markdown
    assert "Use the approved synthetic recommendation." in markdown
    assert unconfirmed["title"] not in markdown
    assert service.repository.get_report(review["review_id"]) == markdown


@pytest.mark.parametrize(
    "decisions",
    [
        [
            {
                "finding_id": "finding-one",
                "action": "edit",
                "edited_title": "",
                "edited_recommendation": None,
            }
        ],
        [
            {
                "finding_id": "finding-one",
                "action": "edit",
                "edited_title": "   ",
                "edited_recommendation": "A valid edited recommendation.",
            }
        ],
        [
            {
                "finding_id": "finding-one",
                "action": "accept",
                "edited_title": "Unexpected edit",
            }
        ],
        [
            {"finding_id": "finding-one", "action": "accept"},
            {"finding_id": "finding-one", "action": "reject"},
        ],
    ],
)
def test_service_rejects_malformed_or_duplicate_decisions(
    tmp_path: Path, decisions: list[dict]
) -> None:
    service = _service(tmp_path)

    with pytest.raises(InvalidDecisionError):
        service.validate_decisions(decisions)
