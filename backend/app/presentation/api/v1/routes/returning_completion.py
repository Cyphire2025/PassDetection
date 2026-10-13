"""Current-trip submission consumes reviewed versioned details, never old answers."""

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Header
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
    source_submission_id: uuid.UUID


@router.post("/complete", response_model=CompleteReuseResponse)
async def complete_returning_trip(
    body: CompleteReuseRequest, token: str = Depends(grant_secret), service: ReturningClaims = Depends(returning_service),
    upload_session_id: str | None = Header(default=None, alias="X-Upload-Session-ID", min_length=32, max_length=128),
) -> CompleteReuseResponse:
    participation_id, status, source_submission_id = await complete_reuse(service, token,
        expected_review_version=body.review_version,
        requirements_version=body.question_version, expected_participation_revision=body.expected_participation_revision,
        custom_answers=body.custom_answers, custom_detail_answers=body.custom_detail_answers,
        current_details=body.current_details, idempotency_key=body.idempotency_key,
        owned_source_id=body.owned_source.source_submission_id if body.owned_source else None,
        owned_source_revision=body.owned_source.expected_extraction_revision if body.owned_source else None,
        upload_session_id=upload_session_id)
    return CompleteReuseResponse.model_validate({"participation_id": participation_id, "status": status,
        "source_submission_id": source_submission_id})
