"""Authenticated, read-only access to collected passport booklet covers."""

from __future__ import annotations

import mimetypes
import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.security.authorization_policy import AuthorizationPolicy
from app.domain.entities.entities import User
from app.domain.exceptions.exceptions import AuthorizationError
from app.infrastructure.database.session import get_db_session
from app.infrastructure.repositories.passport_submission_repository import (
    PassportSubmissionRepository,
)
from app.infrastructure.storage.minio_repository import MinioStorageRepository
from app.presentation.api.v1.object_streaming import private_object_streaming_response
from app.presentation.dependencies.auth import get_current_active_user

router = APIRouter()


@router.get("/{submission_id}/covers/{cover_type}", summary="View a collected passport cover")
async def get_passport_cover(
    submission_id: uuid.UUID,
    cover_type: Literal["cover", "back_cover"],
    range_header: Annotated[str | None, Header(alias="Range")] = None,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> StreamingResponse:
    submission = await PassportSubmissionRepository(session).get_by_id(submission_id)
    if submission is None:
        raise HTTPException(status_code=404, detail="Passport submission was not found")
    try:
        await AuthorizationPolicy(session).require_view_passport(current_user, submission)
    except AuthorizationError as exc:
        raise HTTPException(status_code=403, detail=exc.message) from exc
    key = getattr(submission, f"passport_{cover_type}_s3_key", None)
    if not key:
        raise HTTPException(status_code=404, detail="This passport cover was not uploaded.")
    return await private_object_streaming_response(
        storage=MinioStorageRepository(),
        key=key,
        media_type=mimetypes.guess_type(key)[0] or "image/jpeg",
        content_disposition=f'inline; filename="passport-{cover_type}"',
        range_header=range_header,
    )
