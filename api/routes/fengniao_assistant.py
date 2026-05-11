"""PM assistant endpoint for Fengniao knowledge and fact-layer evidence."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from api.deps import get_current_user
from api.fengniao_evidence import infer_include_fact_layer, search_fengniao_evidence

router = APIRouter(prefix="/review/assistant", tags=["review-assistant"])


class FengniaoAssistantRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=500)
    include_fact_layer: bool | None = None
    max_results: int = Field(default=5, ge=1, le=8)


class FengniaoAssistantResponse(BaseModel):
    answer: str
    hits: list[dict[str, Any]]
    searched_roots: list[dict[str, Any]]
    include_fact_layer: bool


@router.post("/fengniao", response_model=FengniaoAssistantResponse)
async def ask_fengniao_assistant(
    req: FengniaoAssistantRequest,
    _user: dict = Depends(get_current_user),
) -> FengniaoAssistantResponse:
    include_fact_layer = (
        infer_include_fact_layer(req.question)
        if req.include_fact_layer is None
        else req.include_fact_layer
    )
    result = search_fengniao_evidence(
        req.question,
        include_fact_layer=include_fact_layer,
        max_results=req.max_results,
    )
    return FengniaoAssistantResponse(**result)
