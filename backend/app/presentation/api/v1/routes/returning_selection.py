"""Person-scoped selection never changes an accepted master default."""

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from app.application.travellers.claims import ReturningClaims
from app.application.travellers.history import read_history
from app.application.travellers.passport_selection import select_passport
from app.presentation.api.v1.routes.returning_dependencies import (
    grant_secret,
    private_boundary,
    returning_service,
)
from app.presentation.api.v1.schemas.returning_history_schemas import ReturningHistoryResponse

router = APIRouter(dependencies=[Depends(private_boundary)])


class PassportSelectionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    passport_id: uuid.UUID
    group_token: str | None = Field(default=None, min_length=1, max_length=128)


@router.post("/passport-selection", response_model=ReturningHistoryResponse)
async def choose_current_trip_passport(body: PassportSelectionBody, token: str = Depends(grant_secret),
    service: ReturningClaims = Depends(returning_service)) -> ReturningHistoryResponse:
    await select_passport(service, token, body.passport_id, expected_group_token=body.group_token)
    return ReturningHistoryResponse.model_validate(await read_history(service, token, expected_group_token=body.group_token))
