"""Private 24-hour returning draft, still bound to current verified authority."""
import uuid

from fastapi import APIRouter, Depends, File, Form, Header, Request, Response, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from app.application.travellers.claims import ReturningClaims
from app.application.travellers.draft_completion import complete_draft
from app.application.travellers.draft_contracts import (
    DraftComplete,
    DraftSave,
    DraftSide,
    DraftStart,
    DraftView,
)
from app.application.travellers.draft_uploads import upload_draft_document
from app.application.travellers.drafts import draft_view, require_draft, save_draft, start_draft
from app.application.travellers.errors import ReuseError, ReuseReason
from app.infrastructure.database.traveller_returning_draft_models import (
    TravellerDraftAssetModel as Asset,
)
from app.infrastructure.database.traveller_returning_draft_models import (
    TravellerReturningDraftModel as Draft,
)
from app.infrastructure.storage.minio_repository import MinioStorageRepository
from app.presentation.api.v1.routes.passport_routes.public_security import _validated_upload_file
from app.presentation.api.v1.routes.returning_completion import CompleteReuseResponse
from app.presentation.api.v1.routes.returning_dependencies import (
    grant_secret,
    private_boundary,
    returning_service,
    set_secret_cookie,
)

DRAFT_COOKIE = "pd_returning_draft"
router = APIRouter(dependencies=[Depends(private_boundary)])


async def draft_secret(request: Request,
    expected_id: uuid.UUID = Header(..., alias="X-Returning-Draft-ID"),
    service: ReturningClaims = Depends(returning_service),
) -> str:
    secret = request.cookies.get(DRAFT_COOKIE)
    if not secret:
        raise ReuseError(ReuseReason.EXPIRED)
    # Cookies are shared by tabs. Bind the displayed draft to its immutable
    # capability before any reads, writes, OTP staging or receipt replay.
    matched = await service.session.scalar(select(Draft.id).where(
        Draft.id == expected_id, Draft.mode == "returning",
        Draft.secret_hash == service.crypto.digest("returning-draft", secret),
    ))
    if matched is None:
        raise ReuseError(ReuseReason.REVISION_CONFLICT)
    return secret


@router.post("/draft", response_model=DraftView)
async def begin_draft(body: DraftStart, request: Request, response: Response,
    token: str = Depends(grant_secret), service: ReturningClaims = Depends(returning_service),
) -> DraftView:
    secret, result = await start_draft(service, token, expected_review_version=body.review_version,
        existing_secret=request.cookies.get(DRAFT_COOKIE))
    set_secret_cookie(response, DRAFT_COOKIE, secret, 86400)
    return result


@router.get("/draft", response_model=DraftView)
async def read_draft(secret: str = Depends(draft_secret), token: str = Depends(grant_secret),
    service: ReturningClaims = Depends(returning_service),
) -> DraftView:
    result = await draft_view(service, await require_draft(service, token, secret))
    await service.session.commit()
    return result


@router.put("/draft", response_model=DraftView)
async def update_draft(body: DraftSave, secret: str = Depends(draft_secret), token: str = Depends(grant_secret),
    service: ReturningClaims = Depends(returning_service),
) -> DraftView:
    return await save_draft(service, token, secret, body)


@router.post("/draft/documents/{side}", response_model=DraftView)
async def upload_document(side: DraftSide, file: UploadFile = File(...),
    expected_revision: int = Form(..., ge=1), idempotency_key: str = Form(..., min_length=16, max_length=128),
    expected_asset_id: uuid.UUID | None = Form(default=None),
    secret: str = Depends(draft_secret), token: str = Depends(grant_secret),
    service: ReturningClaims = Depends(returning_service),
) -> DraftView:
    await require_draft(service, token, secret)
    await service.session.commit()  # Scanner owns a separate short evidence transaction.
    image = await _validated_upload_file(file, label="Passport document", max_size_bytes=2 * 1024 * 1024, public_device_file=True)
    return await upload_draft_document(service, token, secret, side=side, expected_revision=expected_revision,
        idempotency_key=idempotency_key, content=image.content, content_type=image.content_type,
        storage=MinioStorageRepository(), expected_asset_id=expected_asset_id)


@router.get("/draft/documents/{asset_id}")
async def draft_document(asset_id: uuid.UUID, secret: str = Depends(draft_secret), token: str = Depends(grant_secret),
    service: ReturningClaims = Depends(returning_service),
) -> StreamingResponse:
    draft = await require_draft(service, token, secret)
    asset = await service.session.scalar(select(Asset).where(Asset.id == asset_id, Asset.draft_id == draft.id,
        Asset.agency_id == draft.agency_id, Asset.company_id == draft.company_id, Asset.is_current.is_(True), Asset.state == "ready"))
    if asset is None:
        raise ReuseError(ReuseReason.UNAVAILABLE)
    key, size, media = asset.object_key, asset.byte_size, asset.content_type
    await service.session.commit()
    return StreamingResponse(MinioStorageRepository().stream_file(key, start=0, expected_bytes=size), media_type=media,
        headers={"Cache-Control": "private, no-store, max-age=0", "Pragma": "no-cache", "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff", "Content-Disposition": "inline; filename=draft-document", "Content-Length": str(size)})


@router.post("/draft/complete", response_model=CompleteReuseResponse)
async def submit_draft(body: DraftComplete, request: Request, secret: str = Depends(draft_secret),
    service: ReturningClaims = Depends(returning_service),
    upload_session_id: str | None = Header(default=None, alias="X-Upload-Session-ID", min_length=32, max_length=128),
) -> CompleteReuseResponse:
    # A successful contact promotion revokes the old grant. The exact draft
    # receipt can safely return IDs on retry; all first publication needs it.
    from app.presentation.api.v1.routes.returning_dependencies import GRANT_COOKIE
    result = await complete_draft(service, request.cookies.get(GRANT_COOKIE) or "", secret, body, upload_session_id=upload_session_id)
    return CompleteReuseResponse.model_validate({"participation_id": result[0], "status": result[1], "source_submission_id": result[2]})
