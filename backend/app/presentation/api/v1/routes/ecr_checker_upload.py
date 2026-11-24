"""Stage validated ECR uploads and commit only freshly authorized rows."""

from __future__ import annotations

import asyncio
import uuid
from contextlib import suppress
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.settings import get_settings
from app.domain.entities.entities import User
from app.infrastructure.security.upload_security import UploadSecurityService
from app.infrastructure.storage.minio_repository import MinioStorageRepository
from app.presentation.api.v1.routes.ecr_checker_inputs import (
    _parse_client_ids,
    _run_admitted_upload,
    read_ecr_uploads,
)
from app.presentation.api.v1.routes.ecr_checker_staging import (
    EcrUploadStaging,
    accept_staged_ecr_items,
    stage_ecr_uploads,
)
from app.presentation.api.v1.routes.ecr_checker_support import (
    _MUTATION,
    SessionDep,
    UserDep,
    _batch,
    _items,
    _lock_active_actor,
    _response,
    logger,
)
from app.presentation.api.v1.schemas.ecr_schemas import EcrBatchResponse

router = APIRouter()


@router.post("/batches/{batch_id}/items", response_model=EcrBatchResponse, dependencies=_MUTATION)
async def upload_ecr_items(
    batch_id: uuid.UUID,
    current_user: UserDep,
    session: SessionDep,
    files: Annotated[list[UploadFile], File()],
    client_ids: Annotated[str, Form(max_length=300)],
) -> EcrBatchResponse:
    # Authentication may have opened a read transaction. Waiting for image
    # admission must not retain a pooled DB connection; authorization is checked
    # again inside the mutation before any durable rows are committed.
    await session.commit()
    return await _run_admitted_upload(
        lambda: _upload_ecr_items_admitted(
            batch_id=batch_id,
            current_user=current_user,
            session=session,
            files=files,
            client_ids=client_ids,
        )
    )


async def _upload_ecr_items_admitted(
    *,
    batch_id: uuid.UUID,
    current_user: User,
    session: AsyncSession,
    files: list[UploadFile],
    client_ids: str,
) -> EcrBatchResponse:
    initial_batch = await _batch(session, current_user, batch_id)
    agency_id = initial_batch.agency_id
    initial_status = initial_batch.status
    expected_count = initial_batch.expected_count
    initial_items = {
        item.client_id: (item.sha256, item.original_filename)
        for item in await _items(session, batch_id)
    }
    # Authentication opens a read transaction on this request session. Release
    # it before image reads, scanning, normalization and storage I/O so parallel
    # chunks cannot exhaust the DB pool or wait behind a long batch row lock.
    await session.commit()
    if not 1 <= len(files) <= 5:
        raise HTTPException(422, "Upload between 1 and 5 images per request")
    ids = _parse_client_ids(client_ids, len(files))
    limit = get_settings().ecr_image_max_bytes
    uploads = await read_ecr_uploads(ids, files, limit)
    new_uploads = []
    for upload in uploads:
        old = initial_items.get(upload.client_id)
        if old is not None:
            if old != (upload.sha256, upload.filename):
                raise HTTPException(
                    409, "An upload identifier was reused with different file content"
                )
        else:
            new_uploads.append(upload)
    if not new_uploads:
        current_user = await _lock_active_actor(session, current_user)
        return await _response(session, await _batch(session, current_user, batch_id))
    if initial_status != "uploading":
        raise HTTPException(409, "This batch has already started. Create a new batch to add files")
    if len(initial_items) + len(new_uploads) > expected_count:
        raise HTTPException(409, "This upload exceeds the batch's selected file count")
    security = UploadSecurityService()
    storage = MinioStorageRepository()
    staging = EcrUploadStaging()
    try:
        await stage_ecr_uploads(
            new_uploads, agency_id=agency_id, batch_id=batch_id,
            current_user=current_user, limit=limit, security=security,
            storage=storage, staging=staging,
        )

        # Storage work is now complete. Recheck fresh authorization, batch
        # state, idempotency keys and capacity under a short batch row lock.
        current_user = await _lock_active_actor(session, current_user)
        batch = await _batch(session, current_user, batch_id, lock=True)
        existing = {item.client_id: item for item in await _items(session, batch_id)}
        accept_staged_ecr_items(session, batch=batch, existing=existing, staging=staging)
        # A commit exception can mean the database committed but its reply was
        # lost. Once commit begins, only the orphan reconciler may delete staged
        # keys after proving that no durable row references them.
        staging.commit_started = True
        await session.commit()
    except BaseException:
        with suppress(Exception):
            await session.rollback()
        if staging.stored_keys and not staging.commit_started:
            try:
                await asyncio.shield(storage.delete_files(staging.stored_keys))
            except Exception:
                logger.warning("ecr_upload_cleanup_deferred", batch_id=str(batch_id))
        raise
    # Concurrent replay losers have attempt-unique unused objects. The existing
    # age-gated namespace reconciler cleans these without touching winning rows.
    return await _response(session, batch)
