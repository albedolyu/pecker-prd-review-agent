"""FastAPI application for the credential-free deterministic demo."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated, Literal

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .repository import ReviewRepository
from .service import InvalidDecisionError, ReviewNotFoundError, ReviewService


class CreateReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1)
    content: str = Field(min_length=1)

    @model_validator(mode="after")
    def reject_blank_fields(self) -> "CreateReviewRequest":
        if not self.title.strip() or not self.content.strip():
            raise ValueError("title and content must contain visible text")
        return self


class DecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    finding_id: str = Field(min_length=1)
    action: Literal["accept", "reject", "edit"]
    edited_title: str | None = None
    edited_recommendation: str | None = None

    @model_validator(mode="after")
    def validate_edited_fields(self) -> "DecisionRequest":
        if self.action == "edit":
            edited_values = (self.edited_title, self.edited_recommendation)
            if not any(value is not None for value in edited_values):
                raise ValueError("edit requires an edited title or recommendation")
            if any(value is not None and not value.strip() for value in edited_values):
                raise ValueError("provided edited fields must contain visible text")
        elif self.edited_title is not None or self.edited_recommendation is not None:
            raise ValueError("edited fields are allowed only for edit decisions")
        return self


def create_app(
    *,
    database_path: str | Path | None = None,
    samples_directory: str | Path | None = None,
) -> FastAPI:
    """Build an app whose SQLite repository is initialized on first use."""

    selected_database = Path(
        database_path
        if database_path is not None
        else os.environ.get("PECKER_DB_PATH", ".data/pecker-demo.db")
    )
    app = FastAPI(title="Pecker Public Demo API", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"^http://(?:localhost|127\.0\.0\.1)(?::\d+)?$",
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type"],
    )

    service: ReviewService | None = None

    def get_service() -> ReviewService:
        nonlocal service
        if service is None:
            service = ReviewService(
                ReviewRepository(selected_database),
                samples_directory=samples_directory,
            )
        return service

    @app.exception_handler(ReviewNotFoundError)
    async def handle_not_found(_request, error: ReviewNotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(error)})

    @app.exception_handler(InvalidDecisionError)
    async def handle_invalid_decision(
        _request, error: InvalidDecisionError
    ) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(error)})

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "mode": "deterministic-demo"}

    @app.get("/api/samples")
    async def samples() -> dict[str, list[dict]]:
        return {"samples": get_service().list_samples()}

    @app.post("/api/reviews", status_code=201)
    async def create_review(request: CreateReviewRequest) -> dict:
        return await get_service().create_review(request.title, request.content)

    @app.get("/api/reviews/{review_id}")
    async def get_review(review_id: str) -> dict:
        return get_service().get_review(review_id)

    @app.post("/api/reviews/{review_id}/decisions")
    async def decide_findings(
        review_id: str, decisions: Annotated[list[DecisionRequest], Field()]
    ) -> dict:
        return get_service().apply_decisions(
            review_id,
            [decision.model_dump(exclude_none=True) for decision in decisions],
        )

    @app.get("/api/reviews/{review_id}/report", response_class=PlainTextResponse)
    async def get_report(review_id: str) -> PlainTextResponse:
        markdown = get_service().generate_report(review_id)
        return PlainTextResponse(markdown, media_type="text/markdown")

    return app


app = create_app()


__all__ = ["app", "create_app"]
