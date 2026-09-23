"""Authenticated ECR batch ingestion, progress and Excel export."""

from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from collections.abc import Awaitable, Callable
from contextlib import suppress
from datetime import UTC, datetime
from typing import Annotated
from weakref import WeakKeyDictionary

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.application.security.access_level_actor import (
    actual_user_agency_id,
    actual_user_role,
    refresh_access_level_actor,
)
from app.core.config.settings import get_settings
from app.core.logging.logger import get_logger
from app.domain.entities.entities import User, UserRole
from app.domain.exceptions.exceptions import ImageValidationError
from app.infrastructure.ai.gemini_ecr_service import EcrImageValidationError, prepare_ecr_image
from app.infrastructure.database.ecr_models import EcrBatchModel, EcrItemModel
from app.infrastructure.database.models import AgencyModel, UserModel, UserSecurityStateModel
from app.infrastructure.database.session import get_db_session
from app.infrastructure.export.ecr_excel_exporter import build_ecr_workbook
from app.infrastructure.security.upload_security import UploadSecurityContext, UploadSecurityService
from app.infrastructure.security.upload_validator import (
    DocumentIngestionDisabledError,
    MalwareScannerUnavailableError,
)
from app.infrastructure.storage.minio_repository import MinioStorageRepository
from app.presentation.api.v1.schemas.ecr_schemas import (
    CreateEcrBatch,
    EcrBatchResponse,
    EcrBatchSummary,
    EcrItemResponse,
)
from app.presentation.dependencies.auth import get_current_active_user
from app.presentation.dependencies.csrf import require_cookie_csrf

router = APIRouter()
logger = get_logger(__name__)
UserDep = Annotated[User, Depends(get_current_active_user)]
SessionDep = Annotated[AsyncSession, Depends(get_db_session)]
_MUTATION = [Depends(require_cookie_csrf)]
_ALLOWED_ROLES = {
    UserRole.SUPER_ADMIN,
    UserRole.AGENCY_ADMIN,
    UserRole.AGENCY_MANAGER,
    UserRole.AGENCY_STAFF,
}
_UPLOAD_GATES: WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore] = WeakKeyDictionary()


async def _run_admitted_upload(
    operation: Callable[[], Awaitable[EcrBatchResponse]],
) -> EcrBatchResponse:
    """One decoded ECR upload per API process, including cancellation cleanup.

    Waiting requests keep their UploadFile spools without materializing the
    original chunks. A disconnected caller must not release admission while a
    decoder thread or staged storage operation is still using its memory or
    request session, so admitted work settles before cancellation propagates.
    """
    loop = asyncio.get_running_loop()
    gate = _UPLOAD_GATES.setdefault(loop, asyncio.Semaphore(1))
    async with gate:
        work = asyncio.ensure_future(operation())
        try:
            return await asyncio.shield(work)
        except asyncio.CancelledError:
            while not work.done():
                try:
                    await asyncio.shield(work)
                except asyncio.CancelledError:
                    continue
                except BaseException:
                    break
            # Retrieve any exception so a disconnected upload cannot emit an
            # unhandled-task warning. Cancellation remains the caller outcome.
            with suppress(BaseException):
                work.result()
            raise


def _scope(user: User) -> list[ColumnElement[bool]]:
    if not user.agency_id or user.role not in _ALLOWED_ROLES:
        raise HTTPException(403, "Insufficient permissions")
    filters = [
        EcrBatchModel.agency_id == user.agency_id,
        select(AgencyModel.id)
        .where(AgencyModel.id == user.agency_id, AgencyModel.is_active.is_(True))
        .exists(),
    ]
    if user.role == UserRole.AGENCY_STAFF:
        filters.append(EcrBatchModel.created_by_user_id == user.id)
    return filters


async def _lock_active_actor(session: AsyncSession, user: User) -> User:
    """Revalidate the actor under short shared locks before every mutation.

    Shared locks let upload chunks proceed together while excluding concurrent
    account/agency revocation until the mutation commits. The restricted access
    level of a super administrator is preserved by the common actor helper.
    """

    _scope(user)
    actual_agency_id = actual_user_agency_id(user)
    actor = await session.scalar(
        select(UserModel)
        .join(AgencyModel, AgencyModel.id == user.agency_id)
        .where(
            UserModel.id == user.id,
            UserModel.agency_id == actual_agency_id
            if actual_agency_id is not None
            else UserModel.agency_id.is_(None),
            UserModel.role == actual_user_role(user).value,
            UserModel.is_active.is_(True),
            UserModel.deleted_at.is_(None),
            AgencyModel.is_active.is_(True),
        )
        .with_for_update(read=True, of=[UserModel.id, AgencyModel.id])
        .execution_options(populate_existing=True)
    )
    if actor is None:
        raise HTTPException(403, "Your account or agency is no longer authorized for ECR checking")
    await session.scalar(
        select(UserSecurityStateModel)
        .where(UserSecurityStateModel.user_id == user.id)
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    )
    return await refresh_access_level_actor(session, user)


async def _batch(
    session: AsyncSession, user: User, batch_id: uuid.UUID, *, lock: bool = False
) -> EcrBatchModel:
    query = select(EcrBatchModel).where(EcrBatchModel.id == batch_id, *_scope(user))
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    batch = (await session.execute(query)).scalar_one_or_none()
    if batch is None:
        raise HTTPException(404, "ECR batch not found")
    return batch


async def _items(session: AsyncSession, batch_id: uuid.UUID) -> list[EcrItemModel]:
    return list(
        (
            await session.execute(
                select(EcrItemModel)
                .where(EcrItemModel.batch_id == batch_id)
                .order_by(EcrItemModel.created_at, EcrItemModel.id)
            )
        ).scalars()
    )


def _summary(batch: EcrBatchModel, items: list[EcrItemModel]) -> EcrBatchSummary:
    return EcrBatchSummary(
        batch_id=batch.id,
        title=batch.title,
        status=batch.status,
        total_count=len(items),
        expected_count=batch.expected_count,
        processed_count=sum(item.status in {"completed", "failed"} for item in items),
        ecr_count=sum(item.result == "ECR" for item in items),
        na_count=sum(item.result == "NA" for item in items),
        review_count=sum(item.result == "NEEDS_REVIEW" for item in items),
        failed_count=sum(item.status == "failed" for item in items),
        created_at=batch.created_at,
    )


async def _response(session: AsyncSession, batch: EcrBatchModel) -> EcrBatchResponse:
    items = await _items(session, batch.id)
    return EcrBatchResponse(
        **_summary(batch, items).model_dump(),
        items=[EcrItemResponse.model_validate(item) for item in items],
    )


@router.post("/batches", response_model=EcrBatchResponse, dependencies=_MUTATION, status_code=201)
async def create_ecr_batch(
    body: CreateEcrBatch, current_user: UserDep, session: SessionDep
) -> EcrBatchResponse:
    current_user = await _lock_active_actor(session, current_user)
    batch = EcrBatchModel(
        agency_id=current_user.agency_id,
        created_by_user_id=current_user.id,
        title=body.title.strip() or "ECR check",
        expected_count=body.expected_count,
    )
    session.add(batch)
    await session.commit()
    return await _response(session, batch)


@router.get("/batches", response_model=list[EcrBatchSummary])
async def list_ecr_batches(current_user: UserDep, session: SessionDep) -> list[EcrBatchSummary]:
    batches = list(
        (
            await session.execute(
                select(EcrBatchModel)
                .where(*_scope(current_user))
                .order_by(EcrBatchModel.created_at.desc())
                .limit(50)
            )
        ).scalars()
    )
    if not batches:
        return []
    counts = {
        row["batch_id"]: row
        for row in (
            await session.execute(
                select(
                    EcrItemModel.batch_id,
                    func.count().label("total_count"),
                    func.sum(
                        case((EcrItemModel.status.in_(["completed", "failed"]), 1), else_=0)
                    ).label("processed_count"),
                    func.sum(case((EcrItemModel.result == "ECR", 1), else_=0)).label("ecr_count"),
                    func.sum(case((EcrItemModel.result == "NA", 1), else_=0)).label("na_count"),
                    func.sum(case((EcrItemModel.result == "NEEDS_REVIEW", 1), else_=0)).label(
                        "review_count"
                    ),
                    func.sum(case((EcrItemModel.status == "failed", 1), else_=0)).label(
                        "failed_count"
                    ),
                )
                .where(EcrItemModel.batch_id.in_([batch.id for batch in batches]))
                .group_by(EcrItemModel.batch_id)
            )
        ).mappings()
    }
    return [
        EcrBatchSummary(
            batch_id=batch.id,
            title=batch.title,
            status=batch.status,
            expected_count=batch.expected_count,
            created_at=batch.created_at,
            **{
                name: int(counts.get(batch.id, {}).get(name, 0))
                for name in (
                    "total_count",
                    "processed_count",
                    "ecr_count",
                    "na_count",
                    "review_count",
                    "failed_count",
                )
            },
        )
        for batch in batches
    ]


@router.get("/batches/{batch_id}", response_model=EcrBatchResponse)
async def get_ecr_batch(
    batch_id: uuid.UUID, current_user: UserDep, session: SessionDep
) -> EcrBatchResponse:
    return await _response(session, await _batch(session, current_user, batch_id))


def _parse_client_ids(value: str, file_count: int) -> list[uuid.UUID]:
    try:
        raw = json.loads(value)
        if not isinstance(raw, list) or len(raw) != file_count:
            raise ValueError
        ids = [uuid.UUID(item) for item in raw]
        if len(set(ids)) != len(ids):
            raise ValueError
        return ids
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(422, "Provide one distinct client_id for each file") from None


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
    uploads: list[tuple[uuid.UUID, str, str, str, bytes]] = []
    total = 0
    try:
        for client_id, file in zip(ids, files, strict=True):
            content = await file.read(limit + 1)
            total += len(content)
            if len(content) > limit or total > 20 * 1024 * 1024:
                raise HTTPException(
                    413, "Each image must be at most 10 MiB and each upload at most 20 MiB"
                )
            filename = (file.filename or "image").replace("\\", "/").rsplit("/", 1)[-1]
            filename = "".join(char for char in filename if ord(char) >= 32)[:255] or "image"
            uploads.append(
                (
                    client_id,
                    filename,
                    file.content_type or "application/octet-stream",
                    hashlib.sha256(content).hexdigest(),
                    content,
                )
            )
    finally:
        for file in files:
            await file.close()
    new_uploads = []
    for upload in uploads:
        old = initial_items.get(upload[0])
        if old is not None:
            if old != (upload[3], upload[1]):
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
    stored_keys: list[str] = []
    staged_items: list[EcrItemModel] = []
    commit_started = False
    try:
        for client_id, filename, content_type, digest, content in new_uploads:
            item = EcrItemModel(
                id=uuid.uuid4(),
                batch_id=batch_id,
                client_id=client_id,
                original_filename=filename,
                content_type=content_type,
                sha256=digest,
            )
            try:
                if content_type not in {
                    "image/jpeg",
                    "image/png",
                    "image/webp",
                    "application/octet-stream",
                }:
                    raise ImageValidationError("Unsupported ECR image format")
                await security.validate_image(
                    content=content,
                    filename=filename,
                    declared_content_type=content_type,
                    context=UploadSecurityContext(
                        ingestion_flow="ecr_checker",
                        agency_id=current_user.agency_id,
                        user_id=current_user.id,
                    ),
                    max_bytes=limit,
                    max_dimension=get_settings().ecr_image_max_dimension,
                )
                prepared = await asyncio.to_thread(prepare_ecr_image, content)
                # Each attempt gets a fresh object ID. Concurrent replays never
                # replace or remove another attempt's committed source image.
                key = f"ecr-checks/{agency_id}/{batch_id}/{item.id}.jpg"
                stored_keys.append(key)
                await storage.upload_file(prepared, key, "image/jpeg")
                item.object_key, item.content_type = key, "image/jpeg"
            except (DocumentIngestionDisabledError, MalwareScannerUnavailableError):
                raise HTTPException(
                    503, "Image security scanning is unavailable; retry this upload"
                ) from None
            except (ImageValidationError, EcrImageValidationError):
                item.status, item.reason = "failed", "invalid_image_upload"
            staged_items.append(item)

        # Storage work is now complete. Recheck fresh authorization, batch
        # state, idempotency keys and capacity under a short batch row lock.
        current_user = await _lock_active_actor(session, current_user)
        batch = await _batch(session, current_user, batch_id, lock=True)
        existing = {item.client_id: item for item in await _items(session, batch_id)}
        accepted: list[EcrItemModel] = []
        for item in staged_items:
            existing_item = existing.get(item.client_id)
            if existing_item is None:
                accepted.append(item)
            elif (
                existing_item.sha256 != item.sha256
                or existing_item.original_filename != item.original_filename
            ):
                raise HTTPException(
                    409, "An upload identifier was reused with different file content"
                )
        if accepted:
            if batch.status != "uploading":
                raise HTTPException(
                    409, "This batch has already started. Create a new batch to add files"
                )
            if len(existing) + len(accepted) > batch.expected_count:
                raise HTTPException(409, "This upload exceeds the batch's selected file count")
            session.add_all(accepted)
            batch.updated_at = datetime.now(UTC)
        # A commit exception can mean the database committed but its reply was
        # lost. Once commit begins, only the orphan reconciler may delete staged
        # keys after proving that no durable row references them.
        commit_started = True
        await session.commit()
    except BaseException:
        with suppress(Exception):
            await session.rollback()
        if stored_keys and not commit_started:
            try:
                await asyncio.shield(storage.delete_files(stored_keys))
            except Exception:
                logger.warning("ecr_upload_cleanup_deferred", batch_id=str(batch_id))
        raise
    # Concurrent replay losers have attempt-unique unused objects. The existing
    # age-gated namespace reconciler cleans these without touching winning rows.
    return await _response(session, batch)


async def _dispatch(batch_id: uuid.UUID) -> None:
    from app.infrastructure.ecr import dispatch_ecr_batch

    try:
        await dispatch_ecr_batch(batch_id)
    except Exception:
        # The committed queued row is the outbox; scheduled recovery republishes it.
        logger.warning("ecr_dispatch_deferred", batch_id=str(batch_id))


@router.post("/batches/{batch_id}/start", response_model=EcrBatchResponse, dependencies=_MUTATION)
async def start_ecr_batch(
    batch_id: uuid.UUID, current_user: UserDep, session: SessionDep
) -> EcrBatchResponse:
    current_user = await _lock_active_actor(session, current_user)
    batch = await _batch(session, current_user, batch_id, lock=True)
    if batch.status != "uploading":
        return await _response(session, batch)
    items = await _items(session, batch_id)
    if len(items) != batch.expected_count:
        raise HTTPException(409, "Finish uploading every selected file before starting")
    batch.status = "queued"
    await session.commit()
    await _dispatch(batch.id)
    return await _response(session, batch)


@router.post("/batches/{batch_id}/retry", response_model=EcrBatchResponse, dependencies=_MUTATION)
async def retry_ecr_batch(
    batch_id: uuid.UUID, current_user: UserDep, session: SessionDep
) -> EcrBatchResponse:
    current_user = await _lock_active_actor(session, current_user)
    batch = await _batch(session, current_user, batch_id, lock=True)
    if batch.status not in {"completed", "completed_with_errors"}:
        raise HTTPException(409, "Wait until this batch finishes before retrying failed checks")
    retry = [
        item
        for item in await _items(session, batch_id)
        if item.status == "failed" and item.object_key
    ]
    if not retry:
        raise HTTPException(
            409, "No retryable images remain. Upload invalid or expired images in a new batch"
        )
    for item in retry:
        item.status, item.result, item.reason = "queued", None, None
    batch.status, batch.lease_token, batch.lease_expires_at = "queued", None, None
    await session.commit()
    await _dispatch(batch.id)
    return await _response(session, batch)


@router.get("/batches/{batch_id}/export.xlsx")
async def export_ecr_batch(
    batch_id: uuid.UUID, current_user: UserDep, session: SessionDep
) -> Response:
    batch = await _batch(session, current_user, batch_id)
    items = await _items(session, batch.id)
    if (
        batch.status not in {"completed", "completed_with_errors"}
        or len(items) != batch.expected_count
    ):
        raise HTTPException(
            409, "Wait until every file has finished before downloading the Excel sheet"
        )
    rows = [
        (
            item.original_filename,
            "ERROR"
            if item.status == "failed"
            else "REVIEW"
            if item.result == "NEEDS_REVIEW"
            else item.result or "PENDING",
        )
        for item in items
    ]
    content = await asyncio.to_thread(build_ecr_workbook, rows)
    return Response(
        content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="ECR-{batch.id}.xlsx"',
            "Cache-Control": "no-store",
        },
    )
