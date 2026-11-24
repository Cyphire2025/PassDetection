"""Private scoped PDF/ZIP delivery and archive resource ownership."""

from __future__ import annotations

import asyncio
import uuid
import zipfile
from typing import BinaryIO
from urllib.parse import quote

from fastapi import Depends, HTTPException, status
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import User
from app.domain.value_objects.travel_document_taxonomy import (
    SUPPORTED_TRAVEL_DOCUMENT_TYPES,
)
from app.infrastructure.database.models import (
    DocumentRenameBatchModel,
    DocumentRenameItemModel,
)
from app.infrastructure.database.session import get_db_session
from app.infrastructure.documents.storage_transfers import (
    run_bounded_storage_operations,
)
from app.presentation.api.v1.routes.document_rename_download_contracts import RenameDownloadServices
from app.presentation.dependencies.auth import get_current_active_user


async def download_renamed_document(
    item_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
    *,
    services: RenameDownloadServices,
) -> Response:
    agency_id = services.ensure_allowed(current_user)
    result = await session.execute(
        select(DocumentRenameItemModel)
        .join(
            DocumentRenameBatchModel,
            DocumentRenameBatchModel.id == DocumentRenameItemModel.batch_id,
        )
        .where(
            DocumentRenameItemModel.id == item_id,
            DocumentRenameItemModel.agency_id == agency_id,
            DocumentRenameItemModel.detected_type.in_(SUPPORTED_TRAVEL_DOCUMENT_TYPES),
            DocumentRenameItemModel.status != "rejected",
            DocumentRenameItemModel.storage_key != "",
            *services.batch_filters(current_user, agency_id),
        )
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Renamed document was not found"
        )
    storage_key = item.storage_key
    renamed_filename = item.renamed_filename
    await session.rollback()
    content = await services.storage_factory().get_file(storage_key)
    quoted = quote(renamed_filename)
    return Response(
        content,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quoted}",
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
        },
    )


async def download_renamed_zip(
    batch_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
    *,
    services: RenameDownloadServices,
) -> StreamingResponse:
    agency_id = services.ensure_allowed(current_user)
    batch_result = await session.execute(
        select(DocumentRenameBatchModel).where(
            DocumentRenameBatchModel.id == batch_id,
            *services.batch_filters(current_user, agency_id),
        )
    )
    batch = batch_result.scalar_one_or_none()
    if not batch:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Rename batch was not found"
        )
    if getattr(batch, "status", "completed") != "completed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="This rename upload is still processing"
        )
    items_result = await session.execute(
        select(DocumentRenameItemModel)
        .where(
            DocumentRenameItemModel.batch_id == batch.id,
            DocumentRenameItemModel.agency_id == agency_id,
            DocumentRenameItemModel.detected_type.in_(SUPPORTED_TRAVEL_DOCUMENT_TYPES),
            DocumentRenameItemModel.status != "rejected",
            DocumentRenameItemModel.storage_key != "",
        )
        .order_by(DocumentRenameItemModel.created_at.asc())
    )
    items = [
        (item.id, item.detected_type, item.status, item.storage_key, item.renamed_filename)
        for item in items_result.scalars().all()
    ]
    resolved_batch_id = batch.id
    await session.rollback()
    if not items:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="This batch has no verified visa or flight-ticket PDFs to download.",
        )
    downloadable_items = [
        item
        for item in items
        if item[1] in SUPPORTED_TRAVEL_DOCUMENT_TYPES and item[2] != "rejected" and bool(item[3])
    ]
    if not downloadable_items:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="This batch has no verified visa or flight-ticket PDFs to download.",
        )
    if not services.admission.acquire(blocking=False):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="A large renamed ZIP is already being prepared; retry shortly",
            headers={"Retry-After": "30"},
        )
    archive: BinaryIO | None = None
    total_uncompressed_bytes = 0
    try:
        storage = services.storage_factory()
        active_archive = services.spool_factory(max_size=16 * 1024 * 1024, mode="w+b")
        archive = active_archive
        with zipfile.ZipFile(
            active_archive, "w", compression=zipfile.ZIP_STORED, allowZip64=True
        ) as zip_file:
            used: set[str] = set()
            for offset in range(0, len(downloadable_items), services.fetch_batch_size):
                item_batch = downloadable_items[offset : offset + services.fetch_batch_size]
                contents = await services.fetch_batch(storage, item_batch)
                for item, content in zip(item_batch, contents, strict=True):
                    item_id, _, _, _, renamed_filename = item
                    total_uncompressed_bytes += len(content)
                    if total_uncompressed_bytes > services.max_uncompressed_bytes:
                        raise HTTPException(
                            status_code=413,
                            detail="The renamed ZIP exceeds the 512 MB safety limit",
                        )
                    filename = renamed_filename
                    if filename in used:
                        stem = filename[:-4] if filename.lower().endswith(".pdf") else filename
                        filename = f"{stem}_{item_id.hex[:6]}.pdf"
                    used.add(filename)

                    async def write_entry() -> None:
                        await asyncio.to_thread(zip_file.writestr, filename, content)

                    await run_bounded_storage_operations([write_entry], concurrency=1)
        active_archive.seek(0, 2)
        archive_size = active_archive.tell()
        active_archive.seek(0)
    except BaseException:
        if archive is not None:
            archive.close()
        services.admission.release()
        raise
    assert archive is not None
    zip_name = f"renamed-documents-{resolved_batch_id}.zip"
    try:
        response = StreamingResponse(
            services.stream_archive(archive, release_admission=True),
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="{zip_name}"',
                "Content-Length": str(archive_size),
                "X-Content-Type-Options": "nosniff",
                "Cache-Control": "private, no-store",
            },
        )
    except BaseException:
        archive.close()
        services.admission.release()
        raise
    return response
