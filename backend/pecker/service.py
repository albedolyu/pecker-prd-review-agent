"""Review lifecycle orchestration and confirmed Markdown report generation."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .orchestrator import run_review
from .repository import ReviewRepository, UnknownFindingError


class ReviewNotFoundError(LookupError):
    """Raised when a review identifier is not persisted."""


class InvalidDecisionError(ValueError):
    """Raised when a decision batch is malformed or references another review."""


class ReviewService:
    """Coordinate deterministic reviews, PM decisions, and report generation."""

    def __init__(
        self,
        repository: ReviewRepository,
        *,
        samples_directory: str | Path | None = None,
    ) -> None:
        self.repository = repository
        self.samples_directory = Path(
            samples_directory
            if samples_directory is not None
            else Path(__file__).parents[2] / "samples"
        )

    def list_samples(self) -> list[dict[str, Any]]:
        """Return the two curated, explicitly labelled synthetic demo PRDs."""

        metadata = (
            (
                "export-center",
                "Atlas Export Center (Synthetic demo)",
                "A more complete export workflow with a few bounded omissions.",
            ),
            (
                "team-notes-search",
                "Lantern Notes Search (Synthetic demo)",
                "A deliberately incomplete collaborative-notes search PRD.",
            ),
        )
        return [
            {
                "id": sample_id,
                "label": label,
                "description": description,
                "synthetic": True,
                "content": (self.samples_directory / f"{sample_id}.md").read_text(
                    encoding="utf-8"
                ),
            }
            for sample_id, label, description in metadata
        ]

    async def create_review(self, title: str, content: str) -> dict[str, Any]:
        """Run all bounded workers and persist a completed public snapshot."""

        result = await run_review(title, content)
        snapshot: dict[str, Any] = {
            "review_id": f"review-{uuid4().hex}",
            "title": title,
            "content": content,
            "status": "completed",
            "mode": "deterministic-demo",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "findings": [
                {**finding.model_dump(), "decision": None}
                for finding in result.findings
            ],
            "worker_runs": {
                name: worker_run.model_dump()
                for name, worker_run in result.worker_runs.items()
            },
            "advisor": result.advisor.model_dump(),
        }
        self.repository.create_review(snapshot)
        return snapshot

    def get_review(self, review_id: str) -> dict[str, Any]:
        """Load a review or raise a stable lifecycle-level not-found error."""

        review = self.repository.get_review(review_id)
        if review is None:
            raise ReviewNotFoundError(f"review {review_id!r} was not found")
        return review

    def validate_decisions(
        self, decisions: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Validate a partial decision list before any repository write."""

        normalized: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for decision in decisions:
            finding_id = decision.get("finding_id")
            action = decision.get("action")
            edited_title = decision.get("edited_title")
            edited_recommendation = decision.get("edited_recommendation")
            if not isinstance(finding_id, str) or not finding_id.strip():
                raise InvalidDecisionError("finding_id must be a non-empty string")
            if finding_id in seen_ids:
                raise InvalidDecisionError("a finding may appear only once per batch")
            if action not in {"accept", "reject", "edit"}:
                raise InvalidDecisionError("action must be accept, reject, or edit")
            if action == "edit":
                edited_values = (edited_title, edited_recommendation)
                if not any(value is not None for value in edited_values):
                    raise InvalidDecisionError(
                        "edit requires an edited title or recommendation"
                    )
                if any(
                    value is not None
                    and (not isinstance(value, str) or not value.strip())
                    for value in edited_values
                ):
                    raise InvalidDecisionError(
                        "provided edited fields must contain visible text"
                    )
            elif edited_title is not None or edited_recommendation is not None:
                raise InvalidDecisionError(
                    "accepted and rejected findings cannot carry edited fields"
                )

            clean = {"finding_id": finding_id, "action": action}
            if edited_title is not None:
                clean["edited_title"] = edited_title
            if edited_recommendation is not None:
                clean["edited_recommendation"] = edited_recommendation
            normalized.append(clean)
            seen_ids.add(finding_id)
        return normalized

    def apply_decisions(
        self, review_id: str, decisions: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Validate and atomically apply complete or partial PM decisions."""

        normalized = self.validate_decisions(decisions)
        try:
            review = self.repository.update_decisions(review_id, normalized)
        except UnknownFindingError as error:
            raise InvalidDecisionError(str(error)) from error
        if review is None:
            raise ReviewNotFoundError(f"review {review_id!r} was not found")
        return review

    def generate_report(self, review_id: str) -> str:
        """Generate Markdown solely from accepted or edited findings."""

        review = self.get_review(review_id)
        confirmed = [
            finding
            for finding in review["findings"]
            if finding["decision"] is not None
            and finding["decision"]["action"] in {"accept", "edit"}
        ]
        lines = [
            f"# {review['title']} - Confirmed Review",
            "",
            "> Generated by the deterministic public demo from PM-confirmed findings.",
            "",
        ]
        if not confirmed:
            lines.extend(["No findings have been confirmed.", ""])
        for index, finding in enumerate(confirmed, start=1):
            decision = finding["decision"]
            title = decision.get("edited_title") or finding["title"]
            recommendation = (
                decision.get("edited_recommendation") or finding["recommendation"]
            )
            lines.extend(
                [
                    f"## {index}. {title}",
                    "",
                    f"- Decision: {decision['action'].title()}",
                    f"- Category: {finding['category']}",
                    f"- Severity: {finding['severity']}",
                    f"- Evidence (line {finding['line']}): {finding['evidence']}",
                    "",
                    "### Recommendation",
                    "",
                    recommendation,
                    "",
                ]
            )
        markdown = "\n".join(lines)
        self.repository.save_report(review_id, markdown)
        return markdown


__all__ = [
    "InvalidDecisionError",
    "ReviewNotFoundError",
    "ReviewService",
]
