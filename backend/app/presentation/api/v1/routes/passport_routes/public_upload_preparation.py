"""Public passport preparation: focused capability and workflow owner."""

from __future__ import annotations

from typing import Literal

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    Response,
    UploadFile,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.security.public_upload_capability import public_upload_is_active
from app.domain.exceptions.exceptions import PassDetectionError
from app.domain.value_objects.upload_configuration import (
    MAX_PUBLIC_DOCUMENT_BYTES,
    configuration_for,
    validate_visa_photo_source,
)
from app.infrastructure.database.session import get_db_session
from app.infrastructure.repositories.client_group_repository import ClientGroupRepository
from app.presentation.api.v1.response_contracts import binary_responses

from .public_security import _validated_upload_file

router = APIRouter()


@router.post(
    "/upload/{token}/prepare-file",
    summary="Validate and preview one passport page or Visa Photo file (Public)",
    response_class=Response,
    responses=binary_responses("image/jpeg"),
)
async def prepare_public_upload_file(
    token: str,
    file: UploadFile = File(...),
    purpose: Literal["passport", "visa"] = Form(...),
    upload_session_id: str = Header(
        ..., alias="X-Upload-Session-ID", min_length=32, max_length=128
    ),
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    """Return canonical pixels only, after validating the public capability."""
    group = await ClientGroupRepository(session).get_by_token(token)
    if group is None or not public_upload_is_active(group):
        raise HTTPException(status_code=404, detail="Upload link was not found")
    config = configuration_for(group)
    try:
        if purpose == "passport":
            if not config.passport_enabled or not config.passport_upload_pages:
                raise HTTPException(
                    status_code=400, detail="Passport file upload is disabled for this link."
                )
            group.require_allowed_acquisition_mode("file")
        else:
            if not group.require_selfie:
                raise HTTPException(
                    status_code=400, detail="Visa Photo collection is disabled for this link."
                )
            validate_visa_photo_source(group, photo=file, source="file")
    except PassDetectionError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    # The capability lookup is read-only. Return its connection before the
    # security service opens a separate transaction to persist scan evidence.
    await session.rollback()
    prepared = await _validated_upload_file(
        file,
        label="passport page" if purpose == "passport" else "Visa Photo",
        max_size_bytes=MAX_PUBLIC_DOCUMENT_BYTES if purpose == "passport" else None,
        public_device_file=True,
    )
    return Response(
        content=prepared.content,
        media_type="image/jpeg",
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )


prepare_public_upload_file.__module__ = (
    "app.presentation.api.v1.routes.passport_routes.public_upload"
)
