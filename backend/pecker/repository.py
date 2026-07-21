"""SQLite persistence for deterministic public review snapshots."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


class UnknownFindingError(ValueError):
    """Raised before a decision batch writes when a finding is not in the review."""


class ReviewRepository:
    """Persist review jobs, findings, decisions, and generated reports."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._create_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _create_schema(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS reviews (
                    review_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    status TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    worker_runs_json TEXT NOT NULL,
                    advisor_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS findings (
                    review_id TEXT NOT NULL,
                    finding_id TEXT NOT NULL,
                    position INTEGER NOT NULL,
                    finding_json TEXT NOT NULL,
                    PRIMARY KEY (review_id, finding_id),
                    FOREIGN KEY (review_id) REFERENCES reviews(review_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS decisions (
                    review_id TEXT NOT NULL,
                    finding_id TEXT NOT NULL,
                    decision_json TEXT NOT NULL,
                    PRIMARY KEY (review_id, finding_id),
                    FOREIGN KEY (review_id, finding_id)
                        REFERENCES findings(review_id, finding_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS reports (
                    review_id TEXT PRIMARY KEY,
                    markdown TEXT NOT NULL,
                    FOREIGN KEY (review_id) REFERENCES reviews(review_id) ON DELETE CASCADE
                );
                """
            )

    def create_review(self, snapshot: dict[str, Any]) -> None:
        """Create a completed review and its ordered findings in one transaction."""

        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO reviews (
                    review_id, title, content, status, mode, created_at,
                    worker_runs_json, advisor_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot["review_id"],
                    snapshot["title"],
                    snapshot["content"],
                    snapshot["status"],
                    snapshot["mode"],
                    snapshot["created_at"],
                    json.dumps(snapshot["worker_runs"], ensure_ascii=False),
                    json.dumps(snapshot["advisor"], ensure_ascii=False),
                ),
            )
            for position, finding in enumerate(snapshot["findings"]):
                stored_finding = dict(finding)
                decision = stored_finding.pop("decision", None)
                connection.execute(
                    """
                    INSERT INTO findings (
                        review_id, finding_id, position, finding_json
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (
                        snapshot["review_id"],
                        finding["id"],
                        position,
                        json.dumps(stored_finding, ensure_ascii=False),
                    ),
                )
                if decision is not None:
                    connection.execute(
                        """
                        INSERT INTO decisions (review_id, finding_id, decision_json)
                        VALUES (?, ?, ?)
                        """,
                        (
                            snapshot["review_id"],
                            finding["id"],
                            json.dumps(decision, ensure_ascii=False),
                        ),
                    )

    def get_review(self, review_id: str) -> dict[str, Any] | None:
        """Return one persisted public snapshot, or ``None`` when absent."""

        with self._connect() as connection:
            review = connection.execute(
                "SELECT * FROM reviews WHERE review_id = ?", (review_id,)
            ).fetchone()
            if review is None:
                return None
            finding_rows = connection.execute(
                """
                SELECT findings.finding_json, decisions.decision_json
                FROM findings
                LEFT JOIN decisions
                    ON decisions.review_id = findings.review_id
                    AND decisions.finding_id = findings.finding_id
                WHERE findings.review_id = ?
                ORDER BY findings.position
                """,
                (review_id,),
            ).fetchall()

        findings: list[dict[str, Any]] = []
        for row in finding_rows:
            finding = json.loads(row["finding_json"])
            finding["decision"] = (
                json.loads(row["decision_json"])
                if row["decision_json"] is not None
                else None
            )
            findings.append(finding)
        return {
            "review_id": review["review_id"],
            "title": review["title"],
            "content": review["content"],
            "status": review["status"],
            "mode": review["mode"],
            "created_at": review["created_at"],
            "findings": findings,
            "worker_runs": json.loads(review["worker_runs_json"]),
            "advisor": json.loads(review["advisor_json"]),
        }

    def update_decisions(
        self, review_id: str, decisions: list[dict[str, Any]]
    ) -> dict[str, Any] | None:
        """Apply a complete or partial decision list as one atomic transaction."""

        with self._connect() as connection:
            review_exists = connection.execute(
                "SELECT 1 FROM reviews WHERE review_id = ?", (review_id,)
            ).fetchone()
            if review_exists is None:
                return None

            requested_ids = [decision["finding_id"] for decision in decisions]
            if requested_ids:
                placeholders = ", ".join("?" for _ in requested_ids)
                rows = connection.execute(
                    f"""
                    SELECT finding_id FROM findings
                    WHERE review_id = ? AND finding_id IN ({placeholders})
                    """,
                    (review_id, *requested_ids),
                ).fetchall()
                known_ids = {row["finding_id"] for row in rows}
                if any(finding_id not in known_ids for finding_id in requested_ids):
                    raise UnknownFindingError("decision references an unknown finding")

            for decision in decisions:
                payload = {
                    key: value
                    for key, value in decision.items()
                    if key != "finding_id" and value is not None
                }
                connection.execute(
                    """
                    INSERT INTO decisions (review_id, finding_id, decision_json)
                    VALUES (?, ?, ?)
                    ON CONFLICT(review_id, finding_id)
                    DO UPDATE SET decision_json = excluded.decision_json
                    """,
                    (
                        review_id,
                        decision["finding_id"],
                        json.dumps(payload, ensure_ascii=False),
                    ),
                )

        return self.get_review(review_id)

    def save_report(self, review_id: str, markdown: str) -> None:
        """Persist the latest generated Markdown report for a review."""

        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO reports (review_id, markdown) VALUES (?, ?)
                ON CONFLICT(review_id) DO UPDATE SET markdown = excluded.markdown
                """,
                (review_id, markdown),
            )

    def get_report(self, review_id: str) -> str | None:
        """Return the latest generated report, if any."""

        with self._connect() as connection:
            row = connection.execute(
                "SELECT markdown FROM reports WHERE review_id = ?", (review_id,)
            ).fetchone()
        return None if row is None else str(row["markdown"])


__all__ = ["ReviewRepository", "UnknownFindingError"]
