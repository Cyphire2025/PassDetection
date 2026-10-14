"""Temporary fresh uploads share the returning draft worker and storage rules."""
import secrets
import uuid

from fastapi import APIRouter, Depends, File, Form, Request, Response, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from app.application.travellers.draft_contracts import DraftSave, DraftSide, DraftView
from app.application.travellers.draft_store import FreshDraftStore
from app.application.travellers.draft_uploads import store_draft_document
from app.application.travellers.drafts import draft_view, save_owned_draft
from app.application.travellers.errors import ReuseError, ReuseReason
from app.application.travellers.fresh_drafts import (
    fresh_secret,
    require_fresh_draft,
    start_fresh_draft,
)
from app.infrastructure.database.traveller_returning_draft_models import (
    TravellerDraftAssetModel as Asset,
)
from app.infrastructure.storage.minio_repository import MinioStorageRepository
from app.presentation.api.v1.routes.fresh_draft_dependencies import (
    FRESH_COOKIE,
    FRESH_COOKIE_PATH,
    fresh_store,
    fresh_token,
    upload_session,
)
from app.presentation.api.v1.routes.passport_routes.public_security import _validated_upload_file
from app.presentation.api.v1.routes.returning_dependencies import private_boundary

router = APIRouter(dependencies=[Depends(private_boundary)])


@router.post("/{group_token}", response_model=DraftView)
async def start(group_token: str, request: Request, response: Response, session_id: str = Depends(upload_session),
    service: FreshDraftStore = Depends(fresh_store),
) -> DraftView:
    browser = request.cookies.get(FRESH_COOKIE) or secrets.token_urlsafe(32)
    secret = fresh_secret(service, group_token, browser, session_id)
    result = await start_fresh_draft(service, group_token, secret, session_id)
    response.set_cookie(FRESH_COOKIE, browser, max_age=86400, httponly=True,
        secure=service.settings.is_production or service.settings.jwt.cookie_secure, samesite="strict", path=FRESH_COOKIE_PATH)
    return result


@router.get("/{group_token}", response_model=DraftView)
async def read(group_token: str, secret: str = Depends(fresh_token), service: FreshDraftStore = Depends(fresh_store)) -> DraftView:
    result = await draft_view(service, await require_fresh_draft(service, group_token, secret, submitted=True))
    await service.session.commit()
    return result


@router.put("/{group_token}", response_model=DraftView)
async def save(group_token: str, body: DraftSave, secret: str = Depends(fresh_token), service: FreshDraftStore = Depends(fresh_store)) -> DraftView:
    return await save_owned_draft(service, await require_fresh_draft(service, group_token, secret), body)


@router.post("/{group_token}/documents/{side}", response_model=DraftView)
async def upload(group_token: str, side: DraftSide, file: UploadFile = File(...), expected_revision: int = Form(..., ge=1),
    idempotency_key: str = Form(..., min_length=16, max_length=128), secret: str = Depends(fresh_token),
    service: FreshDraftStore = Depends(fresh_store),
) -> DraftView:
    await require_fresh_draft(service, group_token, secret)
    await service.session.commit()
    image = await _validated_upload_file(file, label="Passport document", max_size_bytes=2 * 1024 * 1024, public_device_file=True)
    return await store_draft_document(service, authorize=lambda: require_fresh_draft(service, group_token, secret), side=side,
        expected_revision=expected_revision, idempotency_key=idempotency_key, content=image.content,
        content_type=image.content_type, storage=MinioStorageRepository())


@router.get("/{group_token}/documents/{asset_id}")
async def image(group_token: str, asset_id: uuid.UUID, secret: str = Depends(fresh_token), service: FreshDraftStore = Depends(fresh_store)) -> StreamingResponse:
    draft = await require_fresh_draft(service, group_token, secret)
    asset = await service.session.scalar(select(Asset).where(Asset.id == asset_id, Asset.draft_id == draft.id,
        Asset.agency_id == draft.agency_id, Asset.state == "ready", Asset.is_current.is_(True)))
    if asset is None:
        raise ReuseError(ReuseReason.UNAVAILABLE)
    key, size, media = asset.object_key, asset.byte_size, asset.content_type
    await service.session.commit()
    return StreamingResponse(MinioStorageRepository().stream_file(key, start=0, expected_bytes=size), media_type=media,
        headers={"Cache-Control": "private, no-store, max-age=0", "Pragma": "no-cache", "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff", "Content-Disposition": "inline; filename=draft-document", "Content-Length": str(size)})
