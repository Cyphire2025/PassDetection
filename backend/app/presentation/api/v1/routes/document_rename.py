"""Document rename HTTP composition and stable call-time integration seams."""

from __future__ import annotations

import threading
import uuid
from collections.abc import AsyncIterator
from tempfile import SpooledTemporaryFile
from typing import Annotated, BinaryIO, Literal, cast

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import User
from app.infrastructure.database.session import get_db_session
from app.infrastructure.documents.document_matcher import (
    DocumentMatcher,
    classify_documents_bounded,
)
from app.infrastructure.documents.storage_cleanup import (
    process_storage_cleanup_job,
    stage_storage_cleanup_jobs,
)
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.storage.minio_repository import MinioStorageRepository
from app.presentation.api.v1.document_chunk_uploads import (
    resolve_document_chunk_metadata,
    validate_document_chunk_size,
)
from app.presentation.api.v1.document_uploads import read_bounded_document_uploads
from app.presentation.api.v1.response_contracts import binary_responses
from app.presentation.api.v1.routes import document_rename_batches as batch_handlers
from app.presentation.api.v1.routes import document_rename_downloads as download_handlers
from app.presentation.api.v1.routes.document_rename_archive_io import (
    _fetch_rename_archive_batch as _fetch_rename_archive_batch,
)
from app.presentation.api.v1.routes.document_rename_archive_io import (
    _stream_archive as _stream_archive_impl,
)
from app.presentation.api.v1.routes.document_rename_authority import (
    _batch_filters as _batch_filters,
)
from app.presentation.api.v1.routes.document_rename_authority import (
    _batch_filters_for_identity as _batch_filters_for_identity,
)
from app.presentation.api.v1.routes.document_rename_authority import (
    _ensure_allowed as _ensure_allowed,
)
from app.presentation.api.v1.routes.document_rename_authority import (
    _lock_active_rename_actor as _lock_active_rename_actor,
)
from app.presentation.api.v1.routes.document_rename_batch_contracts import RenameBatchServices
from app.presentation.api.v1.routes.document_rename_cleanup import (
    _cleanup_owned_rename_storage as _cleanup_owned_rename_storage,
)
from app.presentation.api.v1.routes.document_rename_download_contracts import RenameDownloadServices
from app.presentation.api.v1.routes.document_rename_finalization import finalize_rename_upload
from app.presentation.api.v1.routes.document_rename_preparation import prepare_rename_upload
from app.presentation.api.v1.routes.document_rename_staging import stage_rename_storage
from app.presentation.api.v1.routes.document_rename_upload_contracts import (
    RenameFinalizationServices,
    RenamePreparationServices,
    RenameStorageServices,
)
from app.presentation.api.v1.routes.document_rename_values import _batch_response as _batch_response
from app.presentation.api.v1.routes.document_rename_values import (
    _batch_summary_response as _batch_summary_response,
)
from app.presentation.api.v1.routes.document_rename_values import _document_label as _document_label
from app.presentation.api.v1.routes.document_rename_values import _item_response as _item_response
from app.presentation.api.v1.routes.document_rename_values import _reason as _reason
from app.presentation.api.v1.routes.document_rename_values import (
    _renamed_filename as _renamed_filename,
)
from app.presentation.api.v1.routes.document_rename_values import _role_value as _role_value
from app.presentation.api.v1.routes.document_rename_values import _safe_part as _safe_part
from app.presentation.api.v1.schemas.document_rename_schemas import (
    DeleteRenameBatchesRequest,
    DeleteRenameBatchesResponse,
    RenameDocumentBatchResponse,
    RenameDocumentBatchSummaryResponse,
)
from app.presentation.dependencies.auth import get_current_active_user
from app.presentation.dependencies.csrf import require_cookie_csrf

router = APIRouter()
MAX_RENAME_ARCHIVE_UNCOMPRESSED_BYTES = 512 * 1024 * 1024
RENAME_ARCHIVE_FETCH_BATCH_SIZE = 8
_RENAME_ARCHIVE_ADMISSION = threading.BoundedSemaphore(value=1)


def _batch_services() -> RenameBatchServices:
    return RenameBatchServices(
        _ensure_allowed,
        _batch_filters,
        _batch_summary_response,
        _batch_response,
        AuditLogRepository,
        stage_storage_cleanup_jobs,
        process_storage_cleanup_job,
    )


def _archive_spool(*, max_size: int, mode: Literal["w+b"]) -> BinaryIO:
    return cast(BinaryIO, SpooledTemporaryFile(max_size=max_size, mode=mode))


def _download_services() -> RenameDownloadServices:
    return RenameDownloadServices(
        _ensure_allowed,
        _batch_filters,
        MinioStorageRepository,
        _RENAME_ARCHIVE_ADMISSION,
        MAX_RENAME_ARCHIVE_UNCOMPRESSED_BYTES,
        RENAME_ARCHIVE_FETCH_BATCH_SIZE,
        _archive_spool,
        _fetch_rename_archive_batch,
        _stream_archive,
    )


async def _stream_archive(
    archive: BinaryIO, *, release_admission: bool = False
) -> AsyncIterator[bytes]:
    stream = _stream_archive_impl(
        archive, release_admission=release_admission, admission=_RENAME_ARCHIVE_ADMISSION
    )
    try:
        async for chunk in stream:
            yield chunk
    finally:
        await stream.aclose()


@router.get("/batches", response_model=list[RenameDocumentBatchSummaryResponse])
async def list_rename_batches(
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> list[RenameDocumentBatchSummaryResponse]:
    return await batch_handlers.list_rename_batches(
        current_user,
        session,
        services=_batch_services(),
    )


@router.post(
    "/batches/bulk-delete",
    response_model=DeleteRenameBatchesResponse,
    dependencies=[Depends(require_cookie_csrf)],
)
async def delete_rename_batches(
    payload: DeleteRenameBatchesRequest,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> DeleteRenameBatchesResponse:
    return await batch_handlers.delete_rename_batches(
        payload,
        current_user,
        session,
        services=_batch_services(),
    )


@router.get("/batches/{batch_id}", response_model=RenameDocumentBatchResponse)
async def get_rename_batch(
    batch_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> RenameDocumentBatchResponse:
    return await batch_handlers.get_rename_batch(
        batch_id,
        current_user,
        session,
        services=_batch_services(),
    )


@router.post(
    "/batches",
    response_model=RenameDocumentBatchResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_cookie_csrf)],
)
async def analyze_and_rename_documents(
    files: list[UploadFile] = File(...),
    title: str = Form(...),
    upload_id: Annotated[uuid.UUID | None, Form()] = None,
    chunk_id: Annotated[uuid.UUID | None, Form()] = None,
    chunk_index: Annotated[int | None, Form()] = None,
    expected_chunk_count: Annotated[int | None, Form()] = None,
    expected_file_count: Annotated[int | None, Form()] = None,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> RenameDocumentBatchResponse:
    agency_id = _ensure_allowed(current_user)
    actor_id = current_user.id
    expected_actor_role = current_user.role
    title = " ".join(title.split())[:160]
    if not title:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Enter a title for this rename batch"
        )
    chunk_metadata = resolve_document_chunk_metadata(
        upload_id=upload_id,
        chunk_id=chunk_id,
        chunk_index=chunk_index,
        expected_chunk_count=expected_chunk_count,
        expected_file_count=expected_file_count,
    )
    validate_document_chunk_size(chunk_metadata, file_count=len(files))
    prepared = await prepare_rename_upload(
        files,
        title,
        current_user,
        session,
        agency_id=agency_id,
        actor_id=actor_id,
        expected_actor_role=expected_actor_role,
        chunk_metadata=chunk_metadata,
        services=RenamePreparationServices(
            read_bounded_document_uploads, _batch_filters, _batch_response
        ),
    )
    if isinstance(prepared, RenameDocumentBatchResponse):
        return prepared
    staged = await stage_rename_storage(
        prepared,
        services=RenameStorageServices(
            DocumentMatcher,
            MinioStorageRepository,
            classify_documents_bounded,
            _cleanup_owned_rename_storage,
        ),
    )
    return await finalize_rename_upload(
        prepared,
        staged,
        current_user,
        session,
        services=RenameFinalizationServices(
            _lock_active_rename_actor,
            _batch_response,
            AuditLogRepository,
            _cleanup_owned_rename_storage,
        ),
    )


@router.get(
    "/items/{item_id}/download",
    response_class=Response,
    responses=binary_responses("application/pdf"),
)
async def download_renamed_document(
    item_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    return await download_handlers.download_renamed_document(
        item_id,
        current_user,
        session,
        services=_download_services(),
    )


@router.get(
    "/batches/{batch_id}/download.zip",
    response_class=Response,
    responses=binary_responses("application/zip"),
)
async def download_renamed_zip(
    batch_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> StreamingResponse:
    return await download_handlers.download_renamed_zip(
        batch_id,
        current_user,
        session,
        services=_download_services(),
    )
