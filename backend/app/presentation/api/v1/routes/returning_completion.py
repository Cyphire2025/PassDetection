"""Current-trip submission consumes reviewed versioned details, never old answers."""

import uuid
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.application.travellers.claims import ReturningClaims
from app.application.travellers.completion import complete_reuse
from app.presentation.api.v1.routes.returning_dependencies import (
    grant_secret,
    private_boundary,
    returning_service,
)
from app.presentation.api.v1.schemas.returning_schemas import CompleteReuseRequest

router = APIRouter(dependencies=[Depends(private_boundary)])


class CompleteReuseResponse(BaseModel):
    participation_id: uuid.UUID
    status: Literal["submitted", "accepted"]


@router.post("/complete", response_model=CompleteReuseResponse)
async def complete_returning_trip(
    body: CompleteReuseRequest, token: str = Depends(grant_secret), service: ReturningClaims = Depends(returning_service),
) -> CompleteReuseResponse:
    participation_id, status = await complete_reuse(service, token,
        expected_review_version=body.review_version,
        requirements_version=body.question_version, expected_participation_revision=body.expected_participation_revision,
        custom_answers=body.custom_answers, custom_detail_answers=body.custom_detail_answers,
        current_details=body.current_details, idempotency_key=body.idempotency_key)
    return CompleteReuseResponse.model_validate({"participation_id": participation_id, "status": status})
