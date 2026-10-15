"""Protected review and bounded private document streaming."""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from app.application.travellers.asset_policy import is_reviewable_asset
from app.application.travellers.audit import record_history_action
from app.application.travellers.claims import ReturningClaims
from app.application.travellers.errors import ReuseError, ReuseReason
from app.application.travellers.history import read_history, review_context
from app.infrastructure.database.traveller_reuse_models import TravellerDocumentAssetModel
from app.infrastructure.storage.minio_repository import MinioStorageRepository
from app.presentation.api.v1.routes.returning_dependencies import (
    grant_secret,
    private_boundary,
    returning_service,
)
from app.presentation.api.v1.schemas.returning_history_schemas import ReturningHistoryResponse

router = APIRouter(dependencies=[Depends(private_boundary)])


@router.get("/history", response_model=ReturningHistoryResponse)
async def historical_review(
    token: str = Depends(grant_secret), service: ReturningClaims = Depends(returning_service),
    group_token: str | None = Query(default=None, min_length=1, max_length=128),
) -> ReturningHistoryResponse:
    return ReturningHistoryResponse.model_validate(await read_history(service, token, expected_group_token=group_token))


@router.get("/documents/{asset_id}")
async def historical_document(
    asset_id: uuid.UUID, token: str = Depends(grant_secret), service: ReturningClaims = Depends(returning_service),
) -> StreamingResponse:
    grant, _, person, _, revision, _ = await review_context(service, token)
    if "document:read" not in grant.allowed_actions or revision is None:
        raise ReuseError(ReuseReason.UNAVAILABLE)
    asset = await service.session.scalar(select(TravellerDocumentAssetModel).where(
        TravellerDocumentAssetModel.id == asset_id,
        TravellerDocumentAssetModel.agency_id == grant.agency_id,
        TravellerDocumentAssetModel.company_id == grant.company_id,
        TravellerDocumentAssetModel.traveller_id == person.id,
        TravellerDocumentAssetModel.document_revision_id == revision.id,
        TravellerDocumentAssetModel.availability == "available",
        TravellerDocumentAssetModel.purged_at.is_(None),
    ))
    now = datetime.now(UTC)
    if asset is None or not is_reviewable_asset(asset, now) or asset.object_key is None:
        raise ReuseError(ReuseReason.UNAVAILABLE)
    key, length, media = asset.object_key, asset.byte_size, asset.content_type
    await record_history_action(service.session, grant, "document_viewed", reference=str(asset.id))
    # All authority checks finish before private delivery. Stream in 64 KiB
    # chunks and release DB locks; no public/signed storage URL is produced.
    await service.session.commit()
    storage = MinioStorageRepository()
    return StreamingResponse(storage.stream_file(key, start=0, expected_bytes=length), media_type=media,
        headers={"Cache-Control": "private, no-store, max-age=0", "Pragma": "no-cache",
            "Referrer-Policy": "no-referrer", "X-Content-Type-Options": "nosniff",
            "Content-Disposition": "inline; filename=passport-document", "Content-Length": str(length)})
