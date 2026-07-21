import sqlite3
from pathlib import Path

import pytest

from backend.pecker.repository import ReviewRepository, UnknownFindingError


def _snapshot(review_id: str, *, finding_id: str = "finding-shared") -> dict:
    return {
        "review_id": review_id,
        "title": "Synthetic review",
        "content": "# Synthetic input\nOne exact source line.",
        "status": "completed",
        "mode": "deterministic-demo",
        "created_at": "2026-07-21T00:00:00+00:00",
        "findings": [
            {
                "id": finding_id,
                "worker": "structure",
                "category": "scope_section",
                "severity": "medium",
                "title": "Add an explicit scope section",
                "evidence": "One exact source line.",
                "line": 2,
                "recommendation": "State included and excluded behavior.",
                "confidence": 0.9,
                "decision": None,
            }
        ],
        "worker_runs": {
            "structure": {
                "status": "completed",
                "output": [],
                "confidence": 0.9,
                "tokens_used": 0,
            }
        },
        "advisor": {"gaps": ["Synthetic coverage notice."]},
    }


def test_repository_creates_review_finding_decision_and_report_tables(
    tmp_path: Path,
) -> None:
    database = tmp_path / "reviews.db"

    ReviewRepository(database)

    with sqlite3.connect(database) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    assert {"reviews", "findings", "decisions", "reports"} <= tables


def test_review_round_trip_preserves_the_public_snapshot(tmp_path: Path) -> None:
    repository = ReviewRepository(tmp_path / "reviews.db")
    expected = _snapshot("review-one")

    repository.create_review(expected)

    assert repository.get_review("review-one") == expected
    assert repository.get_review("missing") is None


def test_decision_batch_is_atomic_when_any_finding_is_unknown(tmp_path: Path) -> None:
    repository = ReviewRepository(tmp_path / "reviews.db")
    repository.create_review(_snapshot("review-one", finding_id="finding-one"))

    with pytest.raises(UnknownFindingError):
        repository.update_decisions(
            "review-one",
            [
                {"finding_id": "finding-one", "action": "accept"},
                {"finding_id": "missing", "action": "reject"},
            ],
        )

    review = repository.get_review("review-one")
    assert review is not None
    assert review["findings"][0]["decision"] is None


def test_decisions_are_isolated_by_review_id(tmp_path: Path) -> None:
    repository = ReviewRepository(tmp_path / "reviews.db")
    repository.create_review(_snapshot("review-one"))
    repository.create_review(_snapshot("review-two"))

    updated = repository.update_decisions(
        "review-one",
        [{"finding_id": "finding-shared", "action": "reject"}],
    )

    assert updated is not None
    assert updated["findings"][0]["decision"] == {"action": "reject"}
    untouched = repository.get_review("review-two")
    assert untouched is not None
    assert untouched["findings"][0]["decision"] is None


def test_file_database_can_be_reopened_with_reviews_and_reports_intact(
    tmp_path: Path,
) -> None:
    database = tmp_path / "reviews.db"
    first = ReviewRepository(database)
    first.create_review(_snapshot("review-one"))
    first.save_report("review-one", "# Confirmed synthetic report\n")

    reopened = ReviewRepository(database)

    assert reopened.get_review("review-one") == _snapshot("review-one")
    assert reopened.get_report("review-one") == "# Confirmed synthetic report\n"
