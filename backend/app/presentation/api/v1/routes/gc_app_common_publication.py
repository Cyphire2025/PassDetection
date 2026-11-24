"""GC common-document publication and retained deletion routes."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
    Response,
    status,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mobile.sync_journal import append_mobile_sync_change
from app.domain.entities.entities import User
from app.infrastructure.database.gc_mobile_models import (
    GCCommonDocumentModel,
)
from app.infrastructure.database.session import get_db_session
from app.infrastructure.storage.minio_repository import MinioStorageRepository
from app.presentation.api.v1.routes.gc_app_content_lookup import (
    _get_common_document,
)
from app.presentation.api.v1.routes.gc_app_content_projection import (
    _common_document_response,
)
from app.presentation.api.v1.routes.gc_app_content_scope import (
    GC_CONTENT_ROLES,
    _admin_access_context,
    _content_audit,
    _require_publishable_group,
    logger,
)
from app.presentation.api.v1.schemas.gc_app_schemas import (
    CommonDocumentResponse,
)
from app.presentation.dependencies.auth import require_role
from app.presentation.dependencies.csrf import require_cookie_csrf

router = APIRouter()


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
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Only a draft document can be published"
        )
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
    await session.flush()
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
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Document is not published"
        )
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
