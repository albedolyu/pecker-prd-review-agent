from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


Severity = Literal["low", "medium", "high"]
WorkerName = Literal["structure", "quality", "data", "implementation"]


class Finding(BaseModel):
    id: str
    worker: WorkerName
    title: str
    severity: Severity = "medium"
    issue: str
    evidence: str = ""
    recommendation: str
    how_to_fix: str
    acceptance_check: str


class WorkerResult(BaseModel):
    status: Literal["ok", "degraded", "error"]
    worker: WorkerName
    output: list[Finding] = Field(default_factory=list)
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    tokens_used: int = 0
    error: str | None = None


class ReviewRequest(BaseModel):
    title: str = "Untitled PRD"
    content: str
    mode: Literal["light", "standard"] = "standard"
    max_findings_per_worker: int = Field(default=3, ge=1, le=10)


class ReviewResult(BaseModel):
    title: str
    status: Literal["ok", "partial", "error"]
    findings: list[Finding]
    workers: list[WorkerResult]
    trace: list[str]
    summary: str


class ChannelCandidate(BaseModel):
    name: str
    provider: str = "openai"
    model: str
    base_url: str
    api_key_env: str = "OPENAI_API_KEY"
    routes: list[str] = Field(default_factory=list)


class ChannelScore(BaseModel):
    name: str
    provider: str
    model: str
    base_url: str
    success_rate: float
    p95_latency_ms: float
    cost_per_run_usd: float
    passed_gate: bool


class PromptVariant(BaseModel):
    name: str
    role: str
    prompt: str
    expected_controls: list[str] = Field(default_factory=list)


class PromptQualityScore(BaseModel):
    name: str
    role: str
    instruction_coverage: float
    evidence_contract: float
    output_schema: float
    improvement_guidance: float
    safety_boundary: float
    overall: float
    missing_controls: list[str] = Field(default_factory=list)
