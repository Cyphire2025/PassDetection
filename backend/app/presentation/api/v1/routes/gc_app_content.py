"""Versioned GC App itinerary, common-document, and announcement publishing."""

from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from contextlib import aclosing
from dataclasses import dataclass, field
from datetime import UTC, datetime
from urllib.parse import quote

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mobile.notification_service import (
    cancel_announcement_notifications,
    enqueue_announcement_notifications,
)
from app.application.mobile.sync_journal import append_mobile_sync_change
from app.core.config.settings import get_settings
from app.core.logging.logger import get_logger
from app.domain.entities.entities import GroupStatus, User, UserRole
from app.infrastructure.database.gc_mobile_models import (
    GCAnnouncementModel,
    GCCommonDocumentModel,
    GCGroupAccessModel,
    GCItineraryDayModel,
    GCItineraryItemModel,
    GCItineraryVersionModel,
)
from app.infrastructure.database.models import AuditLogModel, ClientGroupModel
from app.infrastructure.database.session import get_db_session
from app.infrastructure.email.pdf_validator import EmailPdfValidationError, EmailPdfValidator
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.storage.minio_repository import MinioStorageRepository
from app.presentation.api.v1.schemas.gc_app_schemas import (
    AnnouncementCreateRequest,
    AnnouncementResponse,
    CommonDocumentCategory,
    CommonDocumentReorderRequest,
    CommonDocumentResponse,
    GCAppAuditResponse,
    ItineraryDayInput,
    ItineraryDraftRequest,
    ItineraryItemInput,
    ItineraryVersionResponse,
)
from app.presentation.dependencies.auth import require_role
from app.presentation.dependencies.csrf import require_cookie_csrf
from app.presentation.security.client_ip import trusted_client_ip

router = APIRouter()
GC_CONTENT_ROLES = [UserRole.SUPER_ADMIN, UserRole.AGENCY_ADMIN, UserRole.AGENCY_MANAGER]
logger = get_logger(__name__)
_GC_PREVIEW_STREAM_SLOTS = asyncio.Semaphore(8)


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


@dataclass(frozen=True, slots=True)
class _CommonDocumentPreviewPlan:
    """Immutable values retained after the request database session closes."""

    storage_key: str
    safe_filename: str
    media_type: str
    byte_size: int


@router.get(
    "/groups/{group_id}/itineraries/preview",
    response_model=ItineraryVersionResponse,
)
async def preview_itinerary(
    group_id: uuid.UUID,
    agency_id: uuid.UUID | None = None,
    current_user: User = Depends(require_role(GC_CONTENT_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> ItineraryVersionResponse:
    access, _group = await _admin_access_context(
        session, current_user, group_id, agency_id=agency_id, lock=False
    )
    itinerary = await _latest_itinerary(session, access, prefer_draft=True)
    if itinerary is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Itinerary not found")
    return await _itinerary_response(session, itinerary)


@router.post(
    "/groups/{group_id}/itineraries/drafts",
    response_model=ItineraryVersionResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_cookie_csrf)],
)
async def create_itinerary_draft(
    group_id: uuid.UUID,
    body: ItineraryDraftRequest,
    request: Request,
    agency_id: uuid.UUID | None = None,
    current_user: User = Depends(require_role(GC_CONTENT_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> ItineraryVersionResponse:
    access, group = await _admin_access_context(
        session, current_user, group_id, agency_id=agency_id, lock=True
    )
    _require_publishable_group(group)
    _require_access_revision(access, body.expected_access_revision)
    max_version = int(
        (
            await session.execute(
                select(func.coalesce(func.max(GCItineraryVersionModel.version), 0)).where(
                    GCItineraryVersionModel.gc_group_access_id == access.id
                )
            )
        ).scalar_one()
    )
    now = datetime.now(tz=UTC)
    checksum = _json_checksum(body.model_dump(mode="json", by_alias=True))
    itinerary = GCItineraryVersionModel(
        id=uuid.uuid4(),
        agency_id=access.agency_id,
        group_id=group_id,
        gc_group_access_id=access.id,
        version=max_version + 1,
        revision=1,
        status="draft",
        title=body.title,
        content_checksum=checksum,
        created_by_user_id=current_user.id,
        created_at=now,
        updated_at=now,
    )
    session.add(itinerary)
    await session.flush()
    for day_index, day in enumerate(body.days):
        day_model = GCItineraryDayModel(
            id=uuid.uuid4(),
            agency_id=access.agency_id,
            group_id=group_id,
            gc_group_access_id=access.id,
            itinerary_version_id=itinerary.id,
            day_number=day.day_number,
            trip_date=day.trip_date,
            title=day.title or f"Day {day.day_number}",
            sort_order=day_index,
            created_at=now,
            updated_at=now,
        )
        session.add(day_model)
        await session.flush()
        for item_index, item in enumerate(day.items):
            session.add(
                GCItineraryItemModel(
                    id=uuid.uuid4(),
                    agency_id=access.agency_id,
                    group_id=group_id,
                    gc_group_access_id=access.id,
                    itinerary_version_id=itinerary.id,
                    itinerary_day_id=day_model.id,
                    item_type="activity",
                    title=item.title,
                    description=item.description,
                    starts_at=item.starts_at,
                    ends_at=item.ends_at,
                    location_name=item.location_name,
                    latitude=item.latitude,
                    longitude=item.longitude,
                    sort_order=item.sort_order if item.sort_order else item_index,
                    public_metadata={},
                    created_at=now,
                    updated_at=now,
                )
            )
    access.revision += 1
    access.updated_by_user_id = current_user.id
    access.updated_at = now
    await session.flush()
    await _content_audit(
        session,
        request,
        current_user,
        access,
        action="gc_app.itinerary_draft_created",
        entity_type="gc_itinerary_version",
        entity_id=itinerary.id,
    )
    return await _itinerary_response(session, itinerary)


@router.post(
    "/groups/{group_id}/itineraries/{version_id}/publish",
    response_model=ItineraryVersionResponse,
    dependencies=[Depends(require_cookie_csrf)],
)
async def publish_itinerary(
    group_id: uuid.UUID,
    version_id: uuid.UUID,
    request: Request,
    agency_id: uuid.UUID | None = None,
    current_user: User = Depends(require_role(GC_CONTENT_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> ItineraryVersionResponse:
    access, group = await _admin_access_context(
        session, current_user, group_id, agency_id=agency_id, lock=True
    )
    _require_publishable_group(group)
    itinerary = await _get_itinerary(session, access, version_id, lock=True)
    if itinerary.status != "draft":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only a draft itinerary can be published")
    now = datetime.now(tz=UTC)
    previous = list(
        (
            await session.execute(
                select(GCItineraryVersionModel)
                .where(
                    GCItineraryVersionModel.gc_group_access_id == access.id,
                    GCItineraryVersionModel.status == "published",
                    GCItineraryVersionModel.id != itinerary.id,
                )
                .with_for_update()
            )
        ).scalars()
    )
    for item in previous:
        item.status = "retired"
        item.updated_at = now
    itinerary.status = "published"
    itinerary.published_at = now
    itinerary.published_by_user_id = current_user.id
    itinerary.updated_at = now
    access.itinerary_version += 1
    access.manifest_version += 1
    access.revision += 1
    access.updated_by_user_id = current_user.id
    access.updated_at = now
    await append_mobile_sync_change(
        session,
        access=access,
        entity_type="itinerary",
        entity_id=itinerary.id,
        operation="upsert",
        version=access.itinerary_version,
        changed_by_user_id=current_user.id,
        payload={
            "resource_path": f"/api/v1/mobile/trips/{group_id}/itinerary",
            "itinerary_version_id": str(itinerary.id),
        },
    )
    await _content_audit(
        session,
        request,
        current_user,
        access,
        action="gc_app.itinerary_published",
        entity_type="gc_itinerary_version",
        entity_id=itinerary.id,
    )
    return await _itinerary_response(session, itinerary)


@router.post(
    "/groups/{group_id}/itineraries/{version_id}/unpublish",
    response_model=ItineraryVersionResponse,
    dependencies=[Depends(require_cookie_csrf)],
)
async def unpublish_itinerary(
    group_id: uuid.UUID,
    version_id: uuid.UUID,
    request: Request,
    agency_id: uuid.UUID | None = None,
    current_user: User = Depends(require_role(GC_CONTENT_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> ItineraryVersionResponse:
    access, _group = await _admin_access_context(
        session, current_user, group_id, agency_id=agency_id, lock=True
    )
    itinerary = await _get_itinerary(session, access, version_id, lock=True)
    if itinerary.status != "published":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Itinerary is not published")
    now = datetime.now(tz=UTC)
    itinerary.status = "retired"
    itinerary.updated_at = now
    access.itinerary_version += 1
    access.manifest_version += 1
    access.revision += 1
    access.updated_by_user_id = current_user.id
    access.updated_at = now
    await append_mobile_sync_change(
        session,
        access=access,
        entity_type="itinerary",
        entity_id=itinerary.id,
        operation="revoke",
        version=access.itinerary_version,
        changed_by_user_id=current_user.id,
        payload={"resource_path": f"/api/v1/mobile/trips/{group_id}/itinerary"},
    )
    await _content_audit(
        session,
        request,
        current_user,
        access,
        action="gc_app.itinerary_unpublished",
        entity_type="gc_itinerary_version",
        entity_id=itinerary.id,
    )
    return await _itinerary_response(session, itinerary)


@router.get(
    "/groups/{group_id}/common-documents",
    response_model=list[CommonDocumentResponse],
)
async def list_common_documents(
    group_id: uuid.UUID,
    agency_id: uuid.UUID | None = None,
    current_user: User = Depends(require_role(GC_CONTENT_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> list[CommonDocumentResponse]:
    access, _group = await _admin_access_context(
        session, current_user, group_id, agency_id=agency_id, lock=False
    )
    items = list(
        (
            await session.execute(
                select(GCCommonDocumentModel)
                .where(
                    GCCommonDocumentModel.gc_group_access_id == access.id,
                    GCCommonDocumentModel.status.in_(("draft", "published")),
                )
                .order_by(
                    GCCommonDocumentModel.sort_order.asc(),
                    GCCommonDocumentModel.logical_document_id.asc(),
                    GCCommonDocumentModel.version.desc(),
                )
                .limit(200)
            )
        ).scalars()
    )
    return [_common_document_response(item) for item in items]


@router.post(
    "/groups/{group_id}/common-documents",
    response_model=CommonDocumentResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_cookie_csrf)],
)
async def upload_common_document(
    group_id: uuid.UUID,
    request: Request,
    file: UploadFile = File(...),
    category: CommonDocumentCategory = Form(...),
    display_name: str = Form(..., min_length=1, max_length=255),
    offline_available: bool = Form(default=True),
    expected_access_revision: int = Form(..., ge=1),
    agency_id: uuid.UUID | None = None,
    current_user: User = Depends(require_role(GC_CONTENT_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> CommonDocumentResponse:
    return await _store_common_document_version(
        session,
        request=request,
        current_user=current_user,
        group_id=group_id,
        agency_id=agency_id,
        expected_access_revision=expected_access_revision,
        file=file,
        category=category,
        display_name=display_name,
        offline_available=offline_available,
    )


@router.put(
    "/groups/{group_id}/common-documents/reorder",
    response_model=list[CommonDocumentResponse],
    dependencies=[Depends(require_cookie_csrf)],
)
async def reorder_common_documents(
    group_id: uuid.UUID,
    body: CommonDocumentReorderRequest,
    request: Request,
    agency_id: uuid.UUID | None = None,
    current_user: User = Depends(require_role(GC_CONTENT_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> list[CommonDocumentResponse]:
    access, _group = await _admin_access_context(
        session, current_user, group_id, agency_id=agency_id, lock=True
    )
    _require_access_revision(access, body.expected_access_revision)
    unique_ids = list(dict.fromkeys(body.ordered_document_ids))
    documents = list(
        (
            await session.execute(
                select(GCCommonDocumentModel)
                .where(
                    GCCommonDocumentModel.gc_group_access_id == access.id,
                    GCCommonDocumentModel.id.in_(unique_ids),
                    GCCommonDocumentModel.status.in_(("draft", "published")),
                )
                .with_for_update()
            )
        ).scalars()
    )
    if len(documents) != len(unique_ids):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Document order contains unavailable items")
    by_id = {item.id: item for item in documents}
    now = datetime.now(tz=UTC)
    for sort_order, document_id in enumerate(unique_ids):
        by_id[document_id].sort_order = sort_order
        by_id[document_id].updated_at = now
    access.common_document_version += 1
    access.manifest_version += 1
    access.revision += 1
    access.updated_by_user_id = current_user.id
    access.updated_at = now
    await append_mobile_sync_change(
        session,
        access=access,
        entity_type="common_document_order",
        entity_id=None,
        operation="upsert",
        version=access.common_document_version,
        changed_by_user_id=current_user.id,
        payload={"resource_path": f"/api/v1/mobile/trips/{group_id}/common-documents"},
    )
    await _content_audit(
        session,
        request,
        current_user,
        access,
        action="gc_app.common_documents_reordered",
        entity_type="gc_group_access",
        entity_id=access.id,
    )
    return [_common_document_response(by_id[item]) for item in unique_ids]


@router.get(
    "/groups/{group_id}/common-documents/{document_id}/content",
    response_class=StreamingResponse,
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

    async def chunks():  # type: ignore[no-untyped-def]
        async with _GC_PREVIEW_STREAM_SLOTS:
            # Explicit closure releases the S3 response body when the browser
            # closes the preview, cancels navigation, or the ASGI task stops.
            async with aclosing(
                storage.stream_file(
                    stream_plan.storage_key,
                    expected_bytes=stream_plan.byte_size,
                )
            ) as object_stream:
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


@router.post(
    "/groups/{group_id}/common-documents/{document_id}/replace",
    response_model=CommonDocumentResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_cookie_csrf)],
)
async def replace_common_document(
    group_id: uuid.UUID,
    document_id: uuid.UUID,
    request: Request,
    file: UploadFile = File(...),
    category: CommonDocumentCategory = Form(...),
    display_name: str = Form(..., min_length=1, max_length=255),
    offline_available: bool = Form(default=True),
    expected_access_revision: int = Form(..., ge=1),
    agency_id: uuid.UUID | None = None,
    current_user: User = Depends(require_role(GC_CONTENT_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> CommonDocumentResponse:
    return await _store_common_document_version(
        session,
        request=request,
        current_user=current_user,
        group_id=group_id,
        agency_id=agency_id,
        expected_access_revision=expected_access_revision,
        file=file,
        category=category,
        display_name=display_name,
        offline_available=offline_available,
        replace_document_id=document_id,
    )


@router.post(
    "/groups/{group_id}/common-documents/{document_id}/publish",
    response_model=CommonDocumentResponse,
    dependencies=[Depends(require_cookie_csrf)],
)
async def publish_common_document(
    group_id: uuid.UUID,
    document_id: uuid.UUID,
    request: Request,
    agency_id: uuid.UUID | None = None,
    current_user: User = Depends(require_role(GC_CONTENT_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> CommonDocumentResponse:
    access, group = await _admin_access_context(
        session, current_user, group_id, agency_id=agency_id, lock=True
    )
    _require_publishable_group(group)
    document = await _get_common_document(session, access, document_id, lock=True)
    if document.status != "draft":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only a draft document can be published")
    now = datetime.now(tz=UTC)
    previous = list(
        (
            await session.execute(
                select(GCCommonDocumentModel)
                .where(
                    GCCommonDocumentModel.gc_group_access_id == access.id,
                    GCCommonDocumentModel.logical_document_id == document.logical_document_id,
                    GCCommonDocumentModel.status == "published",
                    GCCommonDocumentModel.id != document.id,
                )
                .with_for_update()
            )
        ).scalars()
    )
    for item in previous:
        item.status = "retired"
        item.retired_at = now
        item.updated_at = now
    document.status = "published"
    document.passenger_visible = True
    document.client_manager_visible = True
    document.coordinator_visible = True
    document.published_at = now
    document.published_by_user_id = current_user.id
    document.updated_at = now
    access.common_document_version += 1
    access.manifest_version += 1
    access.revision += 1
    access.updated_by_user_id = current_user.id
    access.updated_at = now
    await append_mobile_sync_change(
        session,
        access=access,
        entity_type="common_document",
        entity_id=document.id,
        operation="upsert",
        version=access.common_document_version,
        changed_by_user_id=current_user.id,
        payload={
            "resource_path": f"/api/v1/mobile/trips/{group_id}/common-documents/{document.id}"
        },
    )
    await _content_audit(
        session,
        request,
        current_user,
        access,
        action="gc_app.common_document_published",
        entity_type="gc_common_document",
        entity_id=document.id,
    )
    return _common_document_response(document)


@router.post(
    "/groups/{group_id}/common-documents/{document_id}/unpublish",
    response_model=CommonDocumentResponse,
    dependencies=[Depends(require_cookie_csrf)],
)
async def unpublish_common_document(
    group_id: uuid.UUID,
    document_id: uuid.UUID,
    request: Request,
    agency_id: uuid.UUID | None = None,
    current_user: User = Depends(require_role(GC_CONTENT_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> CommonDocumentResponse:
    access, _group = await _admin_access_context(
        session, current_user, group_id, agency_id=agency_id, lock=True
    )
    document = await _get_common_document(session, access, document_id, lock=True)
    if document.status != "published":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Document is not published")
    now = datetime.now(tz=UTC)
    document.status = "retired"
    document.retired_at = now
    document.updated_at = now
    access.common_document_version += 1
    access.manifest_version += 1
    access.revision += 1
    access.updated_by_user_id = current_user.id
    access.updated_at = now
    await append_mobile_sync_change(
        session,
        access=access,
        entity_type="common_document",
        entity_id=document.id,
        operation="revoke",
        version=access.common_document_version,
        changed_by_user_id=current_user.id,
        payload={"resource_path": f"/api/v1/mobile/trips/{group_id}/common-documents"},
    )
    await _content_audit(
        session,
        request,
        current_user,
        access,
        action="gc_app.common_document_unpublished",
        entity_type="gc_common_document",
        entity_id=document.id,
    )
    return _common_document_response(document)


@router.delete(
    "/groups/{group_id}/common-documents/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    dependencies=[Depends(require_cookie_csrf)],
)
async def delete_common_document(
    group_id: uuid.UUID,
    document_id: uuid.UUID,
    request: Request,
    agency_id: uuid.UUID | None = None,
    current_user: User = Depends(require_role(GC_CONTENT_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    access, _group = await _admin_access_context(
        session, current_user, group_id, agency_id=agency_id, lock=True
    )
    document = await _get_common_document(session, access, document_id, lock=True)
    now = datetime.now(tz=UTC)
    storage_key = document.storage_key
    delete_storage_after_commit = document.status == "draft"
    if delete_storage_after_commit:
        await session.delete(document)
        await session.flush()
    else:
        document.status = "revoked"
        document.revoked_at = now
        document.updated_at = now
        access.common_document_version += 1
        access.manifest_version += 1
        access.revision += 1
        access.updated_by_user_id = current_user.id
        access.updated_at = now
        await append_mobile_sync_change(
            session,
            access=access,
            entity_type="common_document",
            entity_id=document.id,
            operation="delete",
            version=access.common_document_version,
            changed_by_user_id=current_user.id,
            payload={"resource_path": f"/api/v1/mobile/trips/{group_id}/common-documents"},
        )
    await _content_audit(
        session,
        request,
        current_user,
        access,
        action="gc_app.common_document_deleted",
        entity_type="gc_common_document",
        entity_id=document_id,
    )
    if delete_storage_after_commit:
        # Relational state is authoritative. Commit the deletion and its audit
        # before removing the object so a failed commit can never leave a live
        # draft row pointing at missing bytes. A later object-delete failure is
        # an orphan-cleanup concern and must not resurrect the database record.
        await session.commit()
        try:
            await MinioStorageRepository().delete_files([storage_key])
        except Exception as exc:
            logger.warning(
                "gc_common_document_orphan_cleanup_failed",
                agency_id=str(access.agency_id),
                group_id=str(group_id),
                document_id=str(document_id),
                error_type=type(exc).__name__,
            )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/groups/{group_id}/announcements",
    response_model=list[AnnouncementResponse],
)
async def list_announcements(
    group_id: uuid.UUID,
    agency_id: uuid.UUID | None = None,
    current_user: User = Depends(require_role(GC_CONTENT_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> list[AnnouncementResponse]:
    access, _group = await _admin_access_context(
        session, current_user, group_id, agency_id=agency_id, lock=False
    )
    items = list(
        (
            await session.execute(
                select(GCAnnouncementModel)
                .where(GCAnnouncementModel.gc_group_access_id == access.id)
                .order_by(GCAnnouncementModel.created_at.desc())
                .limit(200)
            )
        ).scalars()
    )
    return [_announcement_response(item) for item in items]


@router.post(
    "/groups/{group_id}/announcements",
    response_model=AnnouncementResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_cookie_csrf)],
)
async def create_announcement(
    group_id: uuid.UUID,
    body: AnnouncementCreateRequest,
    request: Request,
    agency_id: uuid.UUID | None = None,
    current_user: User = Depends(require_role(GC_CONTENT_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> AnnouncementResponse:
    access, group = await _admin_access_context(
        session, current_user, group_id, agency_id=agency_id, lock=True
    )
    _require_publishable_group(group)
    _require_access_revision(access, body.expected_access_revision)
    return await _create_announcement_version(
        session,
        request=request,
        current_user=current_user,
        access=access,
        body=body,
        logical_id=uuid.uuid4(),
        version=1,
    )


@router.put(
    "/groups/{group_id}/announcements/{announcement_id}",
    response_model=AnnouncementResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_cookie_csrf)],
)
async def update_announcement(
    group_id: uuid.UUID,
    announcement_id: uuid.UUID,
    body: AnnouncementCreateRequest,
    request: Request,
    agency_id: uuid.UUID | None = None,
    current_user: User = Depends(require_role(GC_CONTENT_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> AnnouncementResponse:
    access, group = await _admin_access_context(
        session, current_user, group_id, agency_id=agency_id, lock=True
    )
    _require_publishable_group(group)
    _require_access_revision(access, body.expected_access_revision)
    previous = await _get_announcement(session, access, announcement_id, lock=True)
    existing_drafts = list(
        (
            await session.execute(
                select(GCAnnouncementModel)
                .where(
                    GCAnnouncementModel.gc_group_access_id == access.id,
                    GCAnnouncementModel.logical_announcement_id
                    == previous.logical_announcement_id,
                    GCAnnouncementModel.status == "draft",
                )
                .with_for_update()
            )
        ).scalars()
    )
    for draft in existing_drafts:
        await session.delete(draft)
    max_version = int(
        (
            await session.execute(
                select(func.max(GCAnnouncementModel.version)).where(
                    GCAnnouncementModel.gc_group_access_id == access.id,
                    GCAnnouncementModel.logical_announcement_id
                    == previous.logical_announcement_id,
                )
            )
        ).scalar_one()
        or previous.version
    )
    return await _create_announcement_version(
        session,
        request=request,
        current_user=current_user,
        access=access,
        body=body,
        logical_id=previous.logical_announcement_id,
        version=max_version + 1,
    )


@router.post(
    "/groups/{group_id}/announcements/{announcement_id}/publish",
    response_model=AnnouncementResponse,
    dependencies=[Depends(require_cookie_csrf)],
)
async def publish_announcement(
    group_id: uuid.UUID,
    announcement_id: uuid.UUID,
    request: Request,
    agency_id: uuid.UUID | None = None,
    current_user: User = Depends(require_role(GC_CONTENT_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> AnnouncementResponse:
    access, group = await _admin_access_context(
        session, current_user, group_id, agency_id=agency_id, lock=True
    )
    _require_publishable_group(group)
    announcement = await _get_announcement(session, access, announcement_id, lock=True)
    if announcement.status != "draft":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only a draft announcement can be published")
    now = datetime.now(tz=UTC)
    previous = list(
        (
            await session.execute(
                select(GCAnnouncementModel)
                .where(
                    GCAnnouncementModel.gc_group_access_id == access.id,
                    GCAnnouncementModel.logical_announcement_id
                    == announcement.logical_announcement_id,
                    GCAnnouncementModel.status == "published",
                    GCAnnouncementModel.id != announcement.id,
                )
                .with_for_update()
            )
        ).scalars()
    )
    for item in previous:
        item.status = "retired"
        item.retired_at = now
        item.updated_at = now
    announcement.status = "published"
    announcement.passenger_visible = True
    announcement.client_manager_visible = True
    announcement.coordinator_visible = True
    announcement.published_at = now
    announcement.published_by_user_id = current_user.id
    announcement.updated_at = now
    access.announcement_version += 1
    access.manifest_version += 1
    access.revision += 1
    access.updated_by_user_id = current_user.id
    access.updated_at = now
    await append_mobile_sync_change(
        session,
        access=access,
        entity_type="announcement",
        entity_id=announcement.id,
        operation="upsert",
        version=access.announcement_version,
        changed_by_user_id=current_user.id,
        payload={
            "resource_path": f"/api/v1/mobile/trips/{group_id}/announcements/{announcement.id}"
        },
    )
    await enqueue_announcement_notifications(
        session,
        access=access,
        announcement=announcement,
        now=now,
    )
    await _content_audit(
        session,
        request,
        current_user,
        access,
        action="gc_app.announcement_published",
        entity_type="gc_announcement",
        entity_id=announcement.id,
    )
    return _announcement_response(announcement)


@router.post(
    "/groups/{group_id}/announcements/{announcement_id}/unpublish",
    response_model=AnnouncementResponse,
    dependencies=[Depends(require_cookie_csrf)],
)
async def unpublish_announcement(
    group_id: uuid.UUID,
    announcement_id: uuid.UUID,
    request: Request,
    agency_id: uuid.UUID | None = None,
    current_user: User = Depends(require_role(GC_CONTENT_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> AnnouncementResponse:
    access, _group = await _admin_access_context(
        session, current_user, group_id, agency_id=agency_id, lock=True
    )
    announcement = await _get_announcement(session, access, announcement_id, lock=True)
    if announcement.status != "published":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Announcement is not published")
    now = datetime.now(tz=UTC)
    announcement.status = "retired"
    announcement.retired_at = now
    announcement.updated_at = now
    access.announcement_version += 1
    access.manifest_version += 1
    access.revision += 1
    access.updated_by_user_id = current_user.id
    access.updated_at = now
    await append_mobile_sync_change(
        session,
        access=access,
        entity_type="announcement",
        entity_id=announcement.id,
        operation="revoke",
        version=access.announcement_version,
        changed_by_user_id=current_user.id,
        payload={"resource_path": f"/api/v1/mobile/trips/{group_id}/announcements"},
    )
    await cancel_announcement_notifications(
        session,
        access=access,
        announcement_id=announcement.id,
        now=now,
    )
    await _content_audit(
        session,
        request,
        current_user,
        access,
        action="gc_app.announcement_unpublished",
        entity_type="gc_announcement",
        entity_id=announcement.id,
    )
    return _announcement_response(announcement)


@router.delete(
    "/groups/{group_id}/announcements/{announcement_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    dependencies=[Depends(require_cookie_csrf)],
)
async def delete_announcement(
    group_id: uuid.UUID,
    announcement_id: uuid.UUID,
    request: Request,
    agency_id: uuid.UUID | None = None,
    current_user: User = Depends(require_role(GC_CONTENT_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    access, _group = await _admin_access_context(
        session, current_user, group_id, agency_id=agency_id, lock=True
    )
    announcement = await _get_announcement(session, access, announcement_id, lock=True)
    now = datetime.now(tz=UTC)
    if announcement.status == "draft":
        await session.delete(announcement)
        await session.flush()
    else:
        announcement.status = "revoked"
        announcement.revoked_at = now
        announcement.updated_at = now
        access.announcement_version += 1
        access.manifest_version += 1
        access.revision += 1
        access.updated_by_user_id = current_user.id
        access.updated_at = now
        await append_mobile_sync_change(
            session,
            access=access,
            entity_type="announcement",
            entity_id=announcement.id,
            operation="delete",
            version=access.announcement_version,
            changed_by_user_id=current_user.id,
            payload={"resource_path": f"/api/v1/mobile/trips/{group_id}/announcements"},
        )
    await _content_audit(
        session,
        request,
        current_user,
        access,
        action="gc_app.announcement_deleted",
        entity_type="gc_announcement",
        entity_id=announcement_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/groups/{group_id}/audit",
    response_model=list[GCAppAuditResponse],
)
async def list_group_gc_audit(
    group_id: uuid.UUID,
    limit: int = 200,
    agency_id: uuid.UUID | None = None,
    current_user: User = Depends(require_role(GC_CONTENT_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> list[GCAppAuditResponse]:
    access, _group = await _admin_access_context(
        session, current_user, group_id, agency_id=agency_id, lock=False
    )
    bounded_limit = max(1, min(limit, 200))
    candidates = list(
        (
            await session.execute(
                select(AuditLogModel)
                .where(
                    AuditLogModel.agency_id == access.agency_id,
                    AuditLogModel.action.like("gc_app.%"),
                )
                .order_by(AuditLogModel.created_at.desc())
                .limit(500)
            )
        ).scalars()
    )
    matches = [
        item
        for item in candidates
        if (item.metadata_json or {}).get("group_id") == str(group_id)
        or item.entity_id == str(access.id)
    ][:bounded_limit]
    return [
        GCAppAuditResponse(
            id=item.id,
            action=item.action,
            entity_type=item.entity_type,
            entity_id=item.entity_id,
            actor_email=item.actor_email,
            metadata=item.metadata_json or {},
            created_at=item.created_at,
        )
        for item in matches
    ]


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
            version = int(
                (
                    await session.execute(
                        select(func.coalesce(func.max(GCCommonDocumentModel.version), 0)).where(
                            GCCommonDocumentModel.gc_group_access_id == access.id,
                            GCCommonDocumentModel.logical_document_id
                            == previous.logical_document_id,
                        )
                    )
                ).scalar_one()
            ) + 1
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
        await session.rollback()
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
    storage_key = (
        f"gc-app/{agency_id}/{group_id}/common/"
        f"{logical_document_id}/{document_id}.pdf"
    )
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
        await storage.upload_file(
            validated.content,
            storage_key,
            validated.content_type,
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
        await asyncio.shield(staged.storage.delete_files([staged.storage_key]))
    except BaseException as cleanup_error:
        logger.error(
            "gc_common_document_compensation_failed",
            storage_key_hash=hashlib.sha256(staged.storage_key.encode()).hexdigest()[:12],
            error_type=type(cleanup_error).__name__,
        )


async def _create_announcement_version(
    session: AsyncSession,
    *,
    request: Request,
    current_user: User,
    access: GCGroupAccessModel,
    body: AnnouncementCreateRequest,
    logical_id: uuid.UUID,
    version: int,
) -> AnnouncementResponse:
    _validate_window(body.available_from, body.available_until)
    now = datetime.now(tz=UTC)
    announcement = GCAnnouncementModel(
        id=uuid.uuid4(),
        agency_id=access.agency_id,
        group_id=access.group_id,
        gc_group_access_id=access.id,
        logical_announcement_id=logical_id,
        version=version,
        category="emergency" if body.priority == "emergency" else "general",
        priority="high" if body.priority == "important" else body.priority,
        title=body.title,
        body=body.message,
        status="draft",
        passenger_visible=False,
        client_manager_visible=False,
        coordinator_visible=False,
        offline_available=True,
        availability_starts_at=body.available_from,
        availability_expires_at=body.available_until,
        created_by_user_id=current_user.id,
        created_at=now,
        updated_at=now,
    )
    session.add(announcement)
    access.revision += 1
    access.updated_by_user_id = current_user.id
    access.updated_at = now
    await session.flush()
    await _content_audit(
        session,
        request,
        current_user,
        access,
        action="gc_app.announcement_draft_created",
        entity_type="gc_announcement",
        entity_id=announcement.id,
    )
    return _announcement_response(announcement)


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
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Common document must be a safe, readable PDF") from exc


async def _admin_access_context(
    session: AsyncSession,
    current_user: User,
    group_id: uuid.UUID,
    *,
    agency_id: uuid.UUID | None,
    lock: bool,
) -> tuple[GCGroupAccessModel, ClientGroupModel]:
    if current_user.role == UserRole.SUPER_ADMIN:
        if agency_id is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="agency_id is required for super-admin GC App operations",
            )
        tenant_id = agency_id
    else:
        if current_user.agency_id is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Account has no agency",
            )
        if agency_id is not None and agency_id != current_user.agency_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Agency scope mismatch",
            )
        tenant_id = current_user.agency_id
    stmt = (
        select(GCGroupAccessModel, ClientGroupModel)
        .join(ClientGroupModel, ClientGroupModel.id == GCGroupAccessModel.group_id)
        .where(
            GCGroupAccessModel.group_id == group_id,
            GCGroupAccessModel.agency_id == tenant_id,
            GCGroupAccessModel.agency_id == ClientGroupModel.agency_id,
        )
    )
    if lock:
        stmt = stmt.with_for_update(of=(GCGroupAccessModel, ClientGroupModel))
    row = (await session.execute(stmt)).first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="GC App group not found")
    return row


async def _latest_itinerary(
    session: AsyncSession,
    access: GCGroupAccessModel,
    *,
    prefer_draft: bool,
) -> GCItineraryVersionModel | None:
    statuses = ("draft", "published") if prefer_draft else ("published",)
    for item_status in statuses:
        item = (
            await session.execute(
                select(GCItineraryVersionModel)
                .where(
                    GCItineraryVersionModel.gc_group_access_id == access.id,
                    GCItineraryVersionModel.status == item_status,
                )
                .order_by(GCItineraryVersionModel.version.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if item is not None:
            return item
    return None


async def _get_itinerary(
    session: AsyncSession,
    access: GCGroupAccessModel,
    version_id: uuid.UUID,
    *,
    lock: bool,
) -> GCItineraryVersionModel:
    stmt = select(GCItineraryVersionModel).where(
        GCItineraryVersionModel.id == version_id,
        GCItineraryVersionModel.gc_group_access_id == access.id,
        GCItineraryVersionModel.agency_id == access.agency_id,
        GCItineraryVersionModel.group_id == access.group_id,
    )
    if lock:
        stmt = stmt.with_for_update()
    item = (await session.execute(stmt)).scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Itinerary version not found")
    return item


async def _get_common_document(
    session: AsyncSession,
    access: GCGroupAccessModel,
    document_id: uuid.UUID,
    *,
    lock: bool,
) -> GCCommonDocumentModel:
    stmt = select(GCCommonDocumentModel).where(
        GCCommonDocumentModel.id == document_id,
        GCCommonDocumentModel.gc_group_access_id == access.id,
        GCCommonDocumentModel.agency_id == access.agency_id,
        GCCommonDocumentModel.group_id == access.group_id,
    )
    if lock:
        stmt = stmt.with_for_update()
    item = (await session.execute(stmt)).scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Common document not found")
    return item


async def _get_announcement(
    session: AsyncSession,
    access: GCGroupAccessModel,
    announcement_id: uuid.UUID,
    *,
    lock: bool,
) -> GCAnnouncementModel:
    stmt = select(GCAnnouncementModel).where(
        GCAnnouncementModel.id == announcement_id,
        GCAnnouncementModel.gc_group_access_id == access.id,
        GCAnnouncementModel.agency_id == access.agency_id,
        GCAnnouncementModel.group_id == access.group_id,
    )
    if lock:
        stmt = stmt.with_for_update()
    item = (await session.execute(stmt)).scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Announcement not found")
    return item


async def _itinerary_response(
    session: AsyncSession, itinerary: GCItineraryVersionModel
) -> ItineraryVersionResponse:
    days = list(
        (
            await session.execute(
                select(GCItineraryDayModel)
                .where(GCItineraryDayModel.itinerary_version_id == itinerary.id)
                .order_by(GCItineraryDayModel.sort_order.asc())
                .limit(365)
            )
        ).scalars()
    )
    items = list(
        (
            await session.execute(
                select(GCItineraryItemModel)
                .where(GCItineraryItemModel.itinerary_version_id == itinerary.id)
                .order_by(
                    GCItineraryItemModel.itinerary_day_id.asc(),
                    GCItineraryItemModel.sort_order.asc(),
                )
                .limit(1_500)
            )
        ).scalars()
    )
    by_day: dict[uuid.UUID, list[ItineraryItemInput]] = {}
    for item in items:
        by_day.setdefault(item.itinerary_day_id, []).append(
            ItineraryItemInput(
                title=item.title,
                description=item.description,
                starts_at=item.starts_at,
                ends_at=item.ends_at,
                location_name=item.location_name,
                latitude=item.latitude,
                longitude=item.longitude,
                sort_order=item.sort_order,
            )
        )
    return ItineraryVersionResponse(
        id=itinerary.id,
        group_id=itinerary.group_id,
        version=itinerary.version,
        status=itinerary.status,
        title=itinerary.title,
        published_at=itinerary.published_at,
        created_at=itinerary.created_at,
        updated_at=itinerary.updated_at,
        days=[
            ItineraryDayInput(
                day_number=day.day_number,
                trip_date=day.trip_date,
                title=day.title,
                items=by_day.get(day.id, []),
            )
            for day in days
        ],
    )


def _common_document_response(item: GCCommonDocumentModel) -> CommonDocumentResponse:
    return CommonDocumentResponse(
        id=item.id,
        group_id=item.group_id,
        category=item.category,
        display_name=item.title,
        original_filename=item.safe_filename,
        content_type=item.media_type,
        size_bytes=item.byte_size,
        checksum_sha256=item.checksum_sha256,
        version=item.version,
        status=item.status,
        sort_order=item.sort_order,
        available_from=item.availability_starts_at,
        available_until=item.availability_expires_at,
        published_at=item.published_at,
        updated_at=item.updated_at,
    )


def _announcement_response(item: GCAnnouncementModel) -> AnnouncementResponse:
    return AnnouncementResponse(
        id=item.id,
        group_id=item.group_id,
        title=item.title,
        message=item.body,
        priority="important" if item.priority == "high" else item.priority,
        status=item.status,
        version=item.version,
        available_from=item.availability_starts_at,
        available_until=item.availability_expires_at,
        published_at=item.published_at,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def _require_access_revision(access: GCGroupAccessModel, expected: int) -> None:
    if access.revision != expected:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="GC App content changed; refresh and retry")


def _require_publishable_group(group: ClientGroupModel) -> None:
    if group.status not in {GroupStatus.ACTIVE.value, GroupStatus.CLOSED.value}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Archived or deleted groups cannot publish mobile content")


def _validate_window(starts_at: datetime | None, expires_at: datetime | None) -> None:
    if starts_at is not None and expires_at is not None and expires_at <= starts_at:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Availability expiry must be after its start")


def _json_checksum(value: dict[str, object]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


async def _content_audit(
    session: AsyncSession,
    request: Request,
    actor: User,
    access: GCGroupAccessModel,
    *,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID,
) -> None:
    await AuditLogRepository(session).record(
        action=action,
        entity_type=entity_type,
        agency_id=access.agency_id,
        user_id=actor.id,
        actor_email=actor.email,
        entity_id=str(entity_id),
        ip_address=trusted_client_ip(request),
        metadata={"group_id": str(access.group_id)},
    )
