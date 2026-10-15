"""An owned fresh extraction may offer proof; it reveals no saved identity data."""

import uuid

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, ConfigDict, Field

from app.application.travellers.authority import active_scope, eligible_person
from app.application.travellers.claims import ReturningClaims
from app.application.travellers.errors import ReuseError
from app.application.travellers.owned_extraction import owned_extraction_candidate
from app.presentation.api.v1.routes.returning_dependencies import (
    private_boundary,
    returning_service,
)

router = APIRouter(dependencies=[Depends(private_boundary)])


class DetectedHistoryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    group_token: str = Field(min_length=1, max_length=128)
    source_submission_id: uuid.UUID
    expected_extraction_revision: int = Field(ge=0)


class DetectedHistoryResponse(BaseModel):
    available: bool = False


@router.post("/detected-history", response_model=DetectedHistoryResponse)
async def detected_history(body: DetectedHistoryRequest,
    upload_session_id: str = Header(..., alias="X-Upload-Session-ID", min_length=32, max_length=128),
    service: ReturningClaims = Depends(returning_service),
) -> DetectedHistoryResponse:
    from datetime import UTC, datetime
    try:
        scope = await active_scope(service.session, group_token=body.group_token)
        candidate = await owned_extraction_candidate(service.session, group=scope.group,
            source_submission_id=body.source_submission_id, expected_extraction_revision=body.expected_extraction_revision,
            upload_session_id=upload_session_id, crypto=service.crypto)
        if candidate is None:
            return DetectedHistoryResponse()
        await eligible_person(service.session, scope, candidate, datetime.now(UTC))
        return DetectedHistoryResponse(available=True)
    except ReuseError:
        return DetectedHistoryResponse()
