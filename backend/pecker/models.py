"""Validated public result models for deterministic reviews."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Finding(BaseModel):
    """One review issue grounded in an exact submitted line."""

    model_config = ConfigDict(frozen=True)

    id: str
    worker: str
    category: str
    severity: Literal["low", "medium", "high"]
    title: str
    evidence: str
    line: int = Field(ge=1)
    recommendation: str
    confidence: float = Field(ge=0.0, le=1.0)


class WorkerRun(BaseModel):
    """Standard isolated worker return value."""

    status: Literal["completed", "failed"]
    output: list[Finding] = Field(default_factory=list, max_length=3)
    confidence: float = Field(ge=0.0, le=1.0)
    tokens_used: int = Field(ge=0)


class AdvisorReview(BaseModel):
    """Post-consolidation coverage notices, never replacement findings."""

    gaps: list[str] = Field(default_factory=list, max_length=2)


class ReviewResult(BaseModel):
    """Consolidated deterministic result in dispatch order."""

    title: str
    findings: list[Finding]
    worker_runs: dict[str, WorkerRun]
    advisor: AdvisorReview
