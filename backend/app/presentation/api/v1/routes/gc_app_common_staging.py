"""GC PDF validation, owned storage staging and transaction compensation."""

from __future__ import annotations

import asyncio
import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from fastapi import (
    HTTPException,
    Request,
    UploadFile,
    status,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.settings import get_settings
from app.domain.entities.entities import User
from app.infrastructure.database.gc_mobile_models import (
    GCCommonDocumentModel,
)
from app.infrastructure.documents.storage_transfers import (
    finish_cleanup_despite_cancellation,
    run_bounded_storage_operations,
)
from app.infrastructure.email.pdf_validator import EmailPdfValidationError, EmailPdfValidator
from app.infrastructure.storage.minio_repository import MinioStorageRepository
from app.presentation.api.v1.routes.gc_app_common_authority import (
    require_current_common_document_actor,
)
from app.presentation.api.v1.routes.gc_app_content_lookup import (
    _get_common_document,
)
from app.presentation.api.v1.routes.gc_app_content_projection import (
    _common_document_response,
)
from app.presentation.api.v1.routes.gc_app_content_scope import (
    _admin_access_context,
    _content_audit,
    _require_access_revision,
    _require_publishable_group,
    logger,
)
from app.presentation.api.v1.schemas.gc_app_schemas import (
    CommonDocumentResponse,
)


@dataclass(frozen=True, slots=True)
class _StagedCommonDocument:
    """Validated object stored before the short relational write transaction."""

    document_id: uuid.UUID
    logical_document_id: uuid.UUID
    storage_key: str
    safe_filename: str
    media_type: str
    byte_size: int
    checksum_sha256: str
    storage: MinioStorageRepository = field(repr=False)


async def _store_common_document_version(
    session: AsyncSession,
    *,
    request: Request,
    current_user: User,
    group_id: uuid.UUID,
    agency_id: uuid.UUID | None,
    expected_access_revision: int,
    file: UploadFile,
    category: str,
    display_name: str,
    offline_available: bool,
    replace_document_id: uuid.UUID | None = None,
) -> CommonDocumentResponse:
    # The first lookup is deliberately non-locking. It authorizes the tenant,
    # rejects obviously stale requests before object storage work, and captures
    # only immutable scope identifiers. End this read-only transaction before
    # reading/scanning the PDF or calling object storage so no database
    # transaction remains open during the slow, externally controlled work.
    initial_access, initial_group = await _admin_access_context(
        session,
        current_user,
        group_id,
        agency_id=agency_id,
        lock=False,
    )
    _require_publishable_group(initial_group)
    _require_access_revision(initial_access, expected_access_revision)
    initial_access_id = initial_access.id
    initial_agency_id = initial_access.agency_id
    initial_group_id = initial_access.group_id
    if replace_document_id is None:
        logical_document_id = uuid.uuid4()
    else:
        initial_previous = await _get_common_document(
            session,
            initial_access,
            replace_document_id,
            lock=False,
        )
        logical_document_id = initial_previous.logical_document_id

    await session.rollback()
    staged = await _stage_common_document(
        file,
        agency_id=initial_agency_id,
        group_id=initial_group_id,
        logical_document_id=logical_document_id,
    )

    try:
        current_user = await require_current_common_document_actor(session, current_user)
        # Re-authorize and revalidate under the short row lock. The access row
        # serializes revision checks and replacement version allocation without
        # holding a lock during validation or object storage.
        access, group = await _admin_access_context(
            session,
            current_user,
            group_id,
            agency_id=agency_id,
            lock=True,
        )
        if access.id != initial_access_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="GC App content changed; refresh and retry",
            )
        _require_publishable_group(group)
        _require_access_revision(access, expected_access_revision)

        if replace_document_id is None:
            version = 1
            sort_order = 0
        else:
            previous = await _get_common_document(
                session,
                access,
                replace_document_id,
                lock=True,
            )
            if previous.logical_document_id != staged.logical_document_id:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="GC App content changed; refresh and retry",
                )
            version = (
                int(
                    (
                        await session.execute(
                            select(func.coalesce(func.max(GCCommonDocumentModel.version), 0)).where(
                                GCCommonDocumentModel.gc_group_access_id == access.id,
                                GCCommonDocumentModel.logical_document_id
                                == previous.logical_document_id,
                            )
                        )
                    ).scalar_one()
                )
                + 1
            )
            sort_order = previous.sort_order

        now = datetime.now(tz=UTC)
        document = GCCommonDocumentModel(
            id=staged.document_id,
            agency_id=access.agency_id,
            group_id=access.group_id,
            gc_group_access_id=access.id,
            logical_document_id=staged.logical_document_id,
            version=version,
            category=category,
            title=" ".join(display_name.split()),
            storage_key=staged.storage_key,
            safe_filename=staged.safe_filename,
            media_type=staged.media_type,
            byte_size=staged.byte_size,
            checksum_sha256=staged.checksum_sha256,
            status="draft",
            passenger_visible=False,
            client_manager_visible=False,
            coordinator_visible=False,
            offline_available=offline_available,
            availability_starts_at=access.access_starts_at,
            availability_expires_at=access.access_expires_at,
            sort_order=sort_order,
            created_by_user_id=current_user.id,
            created_at=now,
            updated_at=now,
        )
        session.add(document)
        access.revision += 1
        access.updated_by_user_id = current_user.id
        access.updated_at = now
        await session.flush()
        await _content_audit(
            session,
            request,
            current_user,
            access,
            action="gc_app.common_document_uploaded",
            entity_type="gc_common_document",
            entity_id=document.id,
        )
        response = _common_document_response(document)
        # Commit while compensation still owns the staged object. The request
        # dependency's final commit is then a no-op, while a real commit
        # failure removes the unreferenced object.
        await session.commit()
        return response
    except BaseException:
        try:
            await session.rollback()
        finally:
            await _discard_staged_common_document(staged)
        raise


async def _stage_common_document(
    file: UploadFile,
    *,
    agency_id: uuid.UUID,
    group_id: uuid.UUID,
    logical_document_id: uuid.UUID,
) -> _StagedCommonDocument:
    """Validate and store a unique object without holding a database lock."""

    validated = await _validated_common_pdf(file)
    document_id = uuid.uuid4()
    # The immutable document UUID, rather than a version allocated later under
    # lock, makes this key globally unique while keeping all storage I/O outside
    # the critical section.
    storage_key = f"gc-app/{agency_id}/{group_id}/common/{logical_document_id}/{document_id}.pdf"
    storage = MinioStorageRepository()
    staged = _StagedCommonDocument(
        document_id=document_id,
        logical_document_id=logical_document_id,
        storage_key=storage_key,
        safe_filename=validated.filename,
        media_type=validated.content_type,
        byte_size=len(validated.content),
        checksum_sha256=validated.sha256_hex,
        storage=storage,
    )
    try:
        await run_bounded_storage_operations(
            [lambda: storage.upload_file(validated.content, storage_key, validated.content_type)],
            concurrency=1,
        )
    except BaseException:
        # A provider can accept an object and still fail the client response.
        # The random key is owned exclusively by this attempt, so best-effort
        # deletion is always safe.
        await _discard_staged_common_document(staged)
        raise
    return staged


async def _discard_staged_common_document(staged: _StagedCommonDocument) -> None:
    try:
        await finish_cleanup_despite_cancellation(staged.storage.delete_files([staged.storage_key]))
    except asyncio.CancelledError:
        raise
    except BaseException as cleanup_error:
        logger.error(
            "gc_common_document_compensation_failed",
            storage_key_hash=hashlib.sha256(staged.storage_key.encode()).hexdigest()[:12],
            error_type=type(cleanup_error).__name__,
        )


async def _validated_common_pdf(file: UploadFile):  # type: ignore[no-untyped-def]
    max_bytes = get_settings().mobile.common_document_max_bytes
    payload = await file.read(max_bytes + 1)
    await file.close()
    if len(payload) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="Common document exceeds the configured size limit",
        )
    try:
        return await asyncio.to_thread(
            EmailPdfValidator().validate,
            content=payload,
            filename=file.filename,
            declared_content_type=file.content_type,
        )
    except EmailPdfValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Common document must be a safe, readable PDF",
        ) from exc
