"""A fresh upload remains subject to the normal review and acceptance process."""

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, ConfigDict, Field

from app.application.travellers.claims import ReturningClaims
from app.application.travellers.replacement import link_replacement_candidate
from app.presentation.api.v1.routes.returning_dependencies import (
    grant_secret,
    private_boundary,
    returning_service,
)

router = APIRouter(dependencies=[Depends(private_boundary)])


class ReplacementCandidateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_submission_id: uuid.UUID
    expected_extraction_revision: int = Field(ge=0)
    review_version: str = Field(min_length=32, max_length=128)
    change_kind: Literal["renewal", "scan", "correction"]
    idempotency_key: str = Field(min_length=1, max_length=128)


class ReplacementCandidateResponse(BaseModel):
    match_case_id: uuid.UUID
    status: Literal["candidate_pending_review"] = "candidate_pending_review"


@router.post("/replacement-candidate", response_model=ReplacementCandidateResponse, status_code=202)
async def returning_replacement_candidate(
    body: ReplacementCandidateBody,
    upload_session_id: str = Header(..., alias="X-Upload-Session-ID", min_length=32, max_length=128),
    token: str = Depends(grant_secret), service: ReturningClaims = Depends(returning_service),
) -> ReplacementCandidateResponse:
    match_case_id = await link_replacement_candidate(service, token,
        source_submission_id=body.source_submission_id, upload_session_id=upload_session_id,
        expected_extraction_revision=body.expected_extraction_revision,
        expected_review_version=body.review_version, change_kind=body.change_kind,
        idempotency_key=body.idempotency_key)
    return ReplacementCandidateResponse(match_case_id=match_case_id)
