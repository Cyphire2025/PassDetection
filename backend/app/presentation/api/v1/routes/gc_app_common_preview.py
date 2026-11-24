"""Bounded private GC document preview streams after DB release."""

from __future__ import annotations

import asyncio
import uuid
from contextlib import aclosing
from dataclasses import dataclass
from typing import AsyncGenerator, AsyncIterator, cast
from urllib.parse import quote

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    status,
)
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.settings import get_settings
from app.domain.entities.entities import User
from app.infrastructure.database.session import get_db_session
from app.infrastructure.storage.minio_repository import MinioStorageRepository
from app.presentation.api.v1.response_contracts import binary_responses
from app.presentation.api.v1.routes.gc_app_content_lookup import (
    _get_common_document,
)
from app.presentation.api.v1.routes.gc_app_content_scope import (
    GC_CONTENT_ROLES,
    _admin_access_context,
)
from app.presentation.dependencies.auth import require_role

router = APIRouter()


@dataclass(frozen=True, slots=True)
class _CommonDocumentPreviewPlan:
    """Immutable values retained after the request database session closes."""

    storage_key: str
    safe_filename: str
    media_type: str
    byte_size: int


_GC_PREVIEW_STREAM_SLOTS = asyncio.Semaphore(8)


@router.get(
    "/groups/{group_id}/common-documents/{document_id}/content",
    response_class=StreamingResponse,
    responses=binary_responses("application/pdf"),
)
async def preview_common_document_content(
    group_id: uuid.UUID,
    document_id: uuid.UUID,
    agency_id: uuid.UUID | None = None,
    current_user: User = Depends(require_role(GC_CONTENT_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> StreamingResponse:
    access, _group = await _admin_access_context(
        session, current_user, group_id, agency_id=agency_id, lock=False
    )
    document = await _get_common_document(session, access, document_id, lock=False)
    if document.status == "revoked":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Common document not found",
        )
    expected_size = int(document.byte_size)
    maximum_size = get_settings().mobile.common_document_max_bytes
    if expected_size < 1 or expected_size > maximum_size:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="Document is outside the configured preview limit",
        )
    storage = MinioStorageRepository()
    signature = await storage.get_file_range(
        document.storage_key,
        start=0,
        end=min(expected_size, 16) - 1,
    )
    if not signature.startswith(b"%PDF-"):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Document content did not match its declared type",
        )
    # Copy only immutable, already-authorized values into the stream plan.
    # Release the request's database connection before this response can wait
    # for a preview slot or a slow client. The dependency finalizer can safely
    # close/commit the reset session again; no ORM state is used below.
    stream_plan = _CommonDocumentPreviewPlan(
        storage_key=document.storage_key,
        safe_filename=document.safe_filename,
        media_type=document.media_type,
        byte_size=expected_size,
    )
    await session.commit()
    await session.close()

    async def chunks() -> AsyncIterator[bytes]:
        async with _GC_PREVIEW_STREAM_SLOTS:
            # Explicit closure releases the S3 response body when the browser
            # closes the preview, cancels navigation, or the ASGI task stops.
            object_stream = cast(
                AsyncGenerator[bytes, None],
                storage.stream_file(
                    stream_plan.storage_key,
                    start=0,
                    expected_bytes=stream_plan.byte_size,
                ),
            )
            async with aclosing(object_stream) as object_stream:
                async for chunk in object_stream:
                    yield chunk

    safe_name = quote(stream_plan.safe_filename, safe="")
    return StreamingResponse(
        chunks(),
        media_type=stream_plan.media_type,
        headers={
            "Cache-Control": "private, no-store, max-age=0",
            "Content-Disposition": f"inline; filename*=UTF-8''{safe_name}",
            "Content-Length": str(stream_plan.byte_size),
            "X-Content-Type-Options": "nosniff",
        },
    )
