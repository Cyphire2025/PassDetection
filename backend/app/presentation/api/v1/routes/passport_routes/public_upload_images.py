"""Public passport images: focused capability and workflow owner."""

from __future__ import annotations

import mimetypes
import uuid
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Response,
    status,
)
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.session import get_db_session
from app.infrastructure.storage.minio_repository import MinioStorageRepository
from app.presentation.api.v1.object_streaming import private_object_streaming_response
from app.presentation.api.v1.response_contracts import binary_responses

from .public_upload_scope import _get_public_upload_submission

router = APIRouter()


@router.get(
    "/upload/{token}/{submission_id}/image",
    status_code=status.HTTP_200_OK,
    summary="Stream a public upload passport image through the API",
    response_class=Response,
    responses=binary_responses("image/*", range_requests=True),
)
async def get_public_upload_passport_image(
    token: str,
    submission_id: uuid.UUID,
    upload_session_id: str = Header(
        ...,
        alias="X-Upload-Session-ID",
        min_length=32,
        max_length=128,
    ),
    range_header: Annotated[str | None, Header(alias="Range")] = None,
    session: AsyncSession = Depends(get_db_session),
) -> StreamingResponse:
    submission = await _get_public_upload_submission(
        session,
        token=token,
        submission_id=submission_id,
        upload_session_id=upload_session_id,
    )

    if not submission.image_s3_key:
        raise HTTPException(
            status_code=404, detail="The passport personal details page was not uploaded."
        )
    return await private_object_streaming_response(
        storage=MinioStorageRepository(),
        key=submission.image_s3_key,
        media_type=mimetypes.guess_type(submission.image_s3_key)[0] or "image/jpeg",
        content_disposition='inline; filename="passport.jpg"',
        range_header=range_header,
    )


@router.get(
    "/upload/{token}/{submission_id}/image/{document_type}",
    status_code=status.HTTP_200_OK,
    summary="Stream one stored public passport document through the API",
    response_class=Response,
    responses=binary_responses("image/*", range_requests=True),
)
async def get_public_upload_passport_document(
    token: str,
    submission_id: uuid.UUID,
    document_type: str,
    upload_session_id: str = Header(
        ...,
        alias="X-Upload-Session-ID",
        min_length=32,
        max_length=128,
    ),
    range_header: Annotated[str | None, Header(alias="Range")] = None,
    session: AsyncSession = Depends(get_db_session),
) -> StreamingResponse:
    submission = await _get_public_upload_submission(
        session,
        token=token,
        submission_id=submission_id,
        upload_session_id=upload_session_id,
    )

    keys = {
        "front": submission.image_s3_key,
        "back": submission.passport_back_s3_key,
        "photo": submission.passport_photo_s3_key,
        "cover": submission.passport_cover_s3_key,
        "back_cover": submission.passport_back_cover_s3_key,
    }
    if document_type not in keys:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Choose front, back, cover, back_cover, or photo.",
        )
    key = keys[document_type]
    if not key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The requested passport document was not uploaded.",
        )
    return await private_object_streaming_response(
        storage=MinioStorageRepository(),
        key=key,
        media_type=mimetypes.guess_type(key)[0] or "image/jpeg",
        content_disposition=f'inline; filename="passport-{document_type}"',
        range_header=range_header,
    )


get_public_upload_passport_image.__module__ = (
    "app.presentation.api.v1.routes.passport_routes.public_upload"
)
get_public_upload_passport_document.__module__ = (
    "app.presentation.api.v1.routes.passport_routes.public_upload"
)
